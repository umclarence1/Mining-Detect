"""Export 256x256 image + label tiles and make spatial-block splits.

Training tiles are sampled from the wide training region (mining-rich tiles
plus empty ones), excluding a buffer around the Tarkwa test block. Every tile
covering the Tarkwa block is exported for testing and for the change analysis.

Run from the project folder:
    python -m gee.export_tiles               # select, download, split
    python -m gee.export_tiles --splits-only # redo the splits from data/tiles/index.csv
    python -m gee.export_tiles --relabel     # after hand labelling: refresh only the tiles it touches
"""
import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box
from tqdm import tqdm

from common.config import ROOT, load_config
from gee.labels import checked_image, hand_polygons, label_image, maus_gdf, maus_polygons
from gee.utils import build_composite, init_ee, region_geometry


def utm_bounds(cfg: dict, region: str) -> tuple[float, float, float, float]:
    to_utm = Transformer.from_crs("EPSG:4326", cfg["tiles"]["crs"], always_xy=True)
    min_lon, min_lat, max_lon, max_lat = cfg["regions"][region]
    xs, ys = to_utm.transform([min_lon, min_lon, max_lon, max_lon], [min_lat, max_lat, min_lat, max_lat])
    return min(xs), min(ys), max(xs), max(ys)


def tile_grid(cfg: dict) -> pd.DataFrame:
    """All tiles of a grid aligned to multiples of the tile size, covering the training region."""
    step = cfg["tiles"]["size_px"] * cfg["imagery"]["scale_m"]
    xmin, ymin, xmax, ymax = utm_bounds(cfg, "train")
    x0s = np.arange(np.floor(xmin / step) * step, xmax - step + 1, step)
    y0s = np.arange(np.ceil(ymax / step) * step, ymin + step - 1, -step)  # top edges
    rows = [{"x0": x, "y0": y} for y in y0s for x in x0s]
    df = pd.DataFrame(rows)
    df["tile"] = [f"{int(x)}_{int(y)}" for x, y in zip(df.x0, df.y0)]

    txmin, tymin, txmax, tymax = utm_bounds(cfg, "test_tarkwa")
    cx, cy = df.x0 + step / 2, df.y0 - step / 2
    df["is_test"] = (cx >= txmin) & (cx <= txmax) & (cy >= tymin) & (cy <= tymax)
    buf = cfg["tiles"]["test_buffer_m"]
    near_test = box(txmin - buf, tymin - buf, txmax + buf, tymax + buf)
    df["near_test"] = [box(x, y - step, x + step, y).intersects(near_test) for x, y in zip(df.x0, df.y0)]
    return df


def tile_rect(cfg: dict, x0: float, y0: float) -> ee.Geometry:
    step = cfg["tiles"]["size_px"] * cfg["imagery"]["scale_m"]
    return ee.Geometry.Rectangle([x0, y0 - step, x0 + step, y0], proj=cfg["tiles"]["crs"], geodesic=False)


def mining_fractions(cfg: dict, df: pd.DataFrame, period: str, chunk: int = 400) -> np.ndarray:
    """Approximate share of mining pixels per tile (computed at 40 m to stay cheap)."""
    geom = region_geometry(cfg, "train")
    label = label_image(cfg, period, geom, maus_polygons(cfg), build_composite(cfg, period, geom, clip=False))
    out = np.zeros(len(df))
    for start in tqdm(range(0, len(df), chunk), desc=f"mining share {period}"):
        part = df.iloc[start:start + chunk]
        fc = ee.FeatureCollection([ee.Feature(tile_rect(cfg, x, y), {"k": int(k)})
                                   for k, x, y in zip(part.index, part.x0, part.y0)])
        res = label.reduceRegions(fc, ee.Reducer.mean(), scale=40, crs=cfg["tiles"]["crs"]).getInfo()
        for f in res["features"]:
            out[f["properties"]["k"]] = f["properties"].get("mean") or 0.0
    return out


def select_tiles(cfg: dict, grid: pd.DataFrame) -> pd.DataFrame:
    tcfg = cfg["tiles"]
    rng = random.Random(cfg["project"]["seed"])
    rows = []
    pool = grid[~grid.near_test].reset_index(drop=True)
    for period in cfg["periods"]:
        frac = mining_fractions(cfg, pool, period)
        pos = [i for i in range(len(pool)) if frac[i] >= tcfg["positive_min_fraction"]]
        neg = [i for i in range(len(pool)) if frac[i] == 0]
        pos = rng.sample(pos, min(len(pos), tcfg["max_positive_per_period"]))
        neg = rng.sample(neg, min(len(neg), tcfg["max_negative_per_period"]))
        print(f"{period}: {len(pos)} mining tiles, {len(neg)} empty tiles selected")
        for i in pos + neg:
            rows.append({**pool.iloc[i][["tile", "x0", "y0"]].to_dict(), "period": period,
                         "set": "trainval", "est_fraction": frac[i]})
        for _, t in grid[grid.is_test].iterrows():
            rows.append({"tile": t.tile, "x0": t.x0, "y0": t.y0, "period": period, "set": "test", "est_fraction": np.nan})
    df = pd.DataFrame(rows)
    df["file"] = [f"{s}/{p}_{t}.npz" for s, p, t in zip(df["set"], df.period, df.tile)]
    return df


def download_tile(cfg: dict, row, maus_all, hand, overwrite: bool = False) -> dict:
    tcfg = cfg["tiles"]
    size, scale = tcfg["size_px"], cfg["imagery"]["scale_m"]
    out = ROOT / tcfg["out_dir"] / row.file
    if out.exists() and not overwrite:
        return {"file": row.file, "status": "exists"}

    geom = region_geometry(cfg, "train")
    step = size * scale
    to_ll = Transformer.from_crs(tcfg["crs"], "EPSG:4326", always_xy=True)
    lons, lats = to_ll.transform([row.x0, row.x0 + step], [row.y0 - step, row.y0])
    maus = maus_all.cx[min(lons) - 0.01:max(lons) + 0.01, min(lats) - 0.01:max(lats) + 0.01]

    composite = build_composite(cfg, row.period, geom, clip=False)
    label = label_image(cfg, row.period, geom, maus_polygons(cfg, maus), composite, hand.get(row.period))
    image = composite.toInt16().addBands(label.toInt16()).addBands(checked_image(cfg).toInt16())
    request = {
        "expression": image,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": size, "height": size},
            "affineTransform": {"scaleX": scale, "shearX": 0, "translateX": float(row.x0),
                                "shearY": 0, "scaleY": -scale, "translateY": float(row.y0)},
            "crsCode": tcfg["crs"],
        },
    }
    for attempt in range(4):
        try:
            arr = ee.data.computePixels(request)
            break
        except Exception as e:
            if attempt == 3:
                return {"file": row.file, "status": f"failed: {e}"}
            time.sleep(5 * (attempt + 1))

    bands = cfg["imagery"]["bands_all"]
    img = np.stack([arr[b] for b in bands]).astype(np.int16)
    lab = arr["label"].astype(np.uint8)
    checked = arr["checked"].astype(np.uint8)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, image=img, label=lab, checked=checked, x0=row.x0, y0=row.y0)
    return {"file": row.file, "status": "ok", "fraction": float(lab.mean())}


def tiles_touching_hand_labels(cfg: dict, index: pd.DataFrame) -> set[str]:
    """Files of tiles that overlap hand-labelled polygons or squares (only these need re-downloading)."""
    shapes = []
    for path in (ROOT / cfg["labels"]["hand_labels"], ROOT / cfg["labels"]["hand_label_areas"]):
        if path.exists():
            gdf = gpd.read_file(path)
            if not gdf.empty:
                shapes.append(gdf.to_crs(cfg["tiles"]["crs"]).geometry)
    if not shapes:
        return set()
    union = pd.concat(shapes).union_all()
    step = cfg["tiles"]["size_px"] * cfg["imagery"]["scale_m"]
    return {f for f, x, y in zip(index.file, index.x0, index.y0) if box(x, y - step, x + step, y).intersects(union)}


def make_splits(cfg: dict, index: pd.DataFrame) -> None:
    """Assign whole geographic blocks to train or val, so neighbouring tiles never straddle the split."""
    scfg = cfg["splits"]
    block = scfg["block_km"] * 1000
    tv = index[index["set"] == "trainval"].copy()
    tv["block"] = [f"{int(x // block)}_{int(y // block)}" for x, y in zip(tv.x0, tv.y0)]
    blocks = sorted(tv.block.unique())
    rng = random.Random(cfg["project"]["seed"])
    val_blocks = set(rng.sample(blocks, max(1, round(len(blocks) * scfg["val_fraction"]))))

    out_dir = ROOT / scfg["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": tv[~tv.block.isin(val_blocks)].file,
        "val": tv[tv.block.isin(val_blocks)].file,
        "test": index[index["set"] == "test"].file,
    }
    for name, files in splits.items():
        (out_dir / f"{name}.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
        print(f"{name}: {len(files)} tiles")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--splits-only", action="store_true")
    parser.add_argument("--relabel", action="store_true",
                        help="re-download only tiles touching hand labels, so the new labels take effect")
    args = parser.parse_args()

    cfg = load_config()
    index_path = ROOT / cfg["tiles"]["out_dir"] / "index.csv"

    if not args.splits_only:
        init_ee(cfg)
        if index_path.exists():
            index = pd.read_csv(index_path)
            print(f"Using existing tile selection: {index_path}")
        else:
            index = select_tiles(cfg, tile_grid(cfg))
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index.to_csv(index_path, index=False)

        maus_all = maus_gdf(cfg)
        hand = {p: hand_polygons(cfg, p) for p in cfg["periods"]}
        redo = tiles_touching_hand_labels(cfg, index) if args.relabel else set()
        if args.relabel:
            print(f"Re-downloading {len(redo)} tiles that touch hand labels")
        results = []
        with ThreadPoolExecutor(cfg["tiles"]["workers"]) as pool:
            futures = [pool.submit(download_tile, cfg, row, maus_all, hand, row.file in redo) for row in index.itertuples()]
            for f in tqdm(as_completed(futures), total=len(futures), desc="downloading tiles"):
                results.append(f.result())
        failed = [r for r in results if r["status"].startswith("failed")]
        print(f"Downloaded {sum(r['status'] == 'ok' for r in results)}, "
              f"already had {sum(r['status'] == 'exists' for r in results)}, failed {len(failed)}")
        for r in failed[:5]:
            print("  ", r["file"], r["status"])

    index = pd.read_csv(index_path)
    index = index[[(ROOT / cfg["tiles"]["out_dir"] / f).exists() for f in index.file]]
    make_splits(cfg, index)


if __name__ == "__main__":
    main()
