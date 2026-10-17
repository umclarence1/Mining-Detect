"""Prepare map layers for the web app from the pipeline outputs.

Run from the project folder (after run_pipeline.py), once or whenever results change:
    python -m webapp.build_assets

Writes webapp/static/data/: imagery and mask overlays (EPSG:4326 PNG/JPEG),
a 1 km new-mining grid, mine footprints and forest reserves (GeoJSON), and
summary.json with every number the app shows.
"""
import json

import geopandas as gpd
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box

from analysis.rasters import PRED_DIR, burn, read, remove_small
from app.build_map import mask_image, rgb_image, to_wgs84
from common.config import ROOT, load_config
from gee.labels import licensed_gdf

DATA = ROOT / "webapp" / "static" / "data"
CELL_PX = 100  # 1 km at 10 m


def save(img: Image.Image, name: str, fmt: str) -> str:
    path = DATA / name
    img.save(path, format=fmt, **({"quality": 85, "optimize": True} if fmt == "JPEG" else {"optimize": True}))
    return f"data/{name}"


def grid_cells(mask: np.ndarray, profile: dict) -> dict:
    """GeoJSON of ~1 km cells with hectares of new mining in each."""
    t = profile["transform"]
    to_ll = Transformer.from_crs(profile["crs"], "EPSG:4326", always_xy=True)
    feats = []
    rows, cols = mask.shape[0] // CELL_PX, mask.shape[1] // CELL_PX
    for r in range(rows):
        for c in range(cols):
            ha = float(mask[r * CELL_PX:(r + 1) * CELL_PX, c * CELL_PX:(c + 1) * CELL_PX].sum() * 0.01)
            if ha <= 0:
                continue
            x0, y0 = t.c + c * CELL_PX * t.a, t.f + r * CELL_PX * t.e
            x1, y1 = x0 + CELL_PX * t.a, y0 + CELL_PX * t.e
            (lo0, lo1), (la0, la1) = to_ll.transform([x0, x1], [y0, y1])
            feats.append({"type": "Feature", "properties": {"ha": round(ha, 1)},
                          "geometry": box(lo0, la1, lo1, la0).__geo_interface__})
    return {"type": "FeatureCollection", "features": feats}


def reserves(cfg: dict) -> gpd.GeoDataFrame:
    """Protected areas from WDPA (needs Earth Engine; cached after the first run)."""
    cache = DATA / "reserves.geojson"
    if cache.exists():
        return gpd.read_file(cache)
    from analysis.alerts import protected_areas
    from gee.utils import init_ee

    init_ee(cfg)
    return protected_areas(cfg)


def main():
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)

    rgb0, profile = read("baseline_rgb")
    rgb1, _ = read("recent_rgb")
    m0, _ = read("baseline_mask")
    m1, _ = read("recent_mask")
    new = np.load(PRED_DIR / "new_mining.npy").astype(bool)

    licensed, licensed_source = licensed_gdf(cfg)
    industrial = burn(licensed, profile).astype(bool)
    galamsey_new = remove_small(new & ~industrial, int(cfg["analysis"]["min_patch_ha"] / 0.01)).astype(bool)

    layers = {}
    for key, arr, kind in [
        ("imagery_2020", rgb0, "rgb"), ("imagery_2026", rgb1, "rgb"),
        ("mining_2020", m0, (255, 196, 0)), ("mining_2026", m1, (239, 68, 68)),
        ("new_mining", new.astype(np.uint8), (236, 72, 153)),
    ]:
        warped, bounds = to_wgs84(arr, profile, nearest=kind != "rgb")
        if kind == "rgb":
            url = save(rgb_image(warped), f"{key}.jpg", "JPEG")
        else:
            url = save(mask_image(warped, kind), f"{key}.png", "PNG")
        layers[key] = {"url": url, "bounds": bounds}

    (DATA / "grid.geojson").write_text(json.dumps(grid_cells(galamsey_new, profile)), encoding="utf-8")

    min_lon, min_lat, max_lon, max_lat = cfg["regions"]["test_tarkwa"]
    pad = 0.03
    area = box(min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad)
    fp = licensed[licensed.intersects(area)]
    fp.to_file(DATA / "footprint.geojson", driver="GeoJSON")
    res = reserves(cfg)
    res.to_file(DATA / "reserves.geojson", driver="GeoJSON")

    change = json.loads((ROOT / "report" / "change.json").read_text(encoding="utf-8"))
    results = json.loads((ROOT / "report" / "results.json").read_text(encoding="utf-8"))
    turbidity = json.loads((ROOT / "report" / "turbidity.json").read_text(encoding="utf-8"))
    alerts = gpd.read_file(ROOT / "outputs" / "maps" / "alerts.geojson")
    summary = {
        "region": {"name": "Tarkwa, Western Region, Ghana", "bbox": cfg["regions"]["test_tarkwa"],
                   "periods": {k: f"{v['start']} to {v['end']}" for k, v in cfg["periods"].items()}},
        "change": change,
        "models": {k: v for k, v in results.items() if isinstance(v, dict)},
        "turbidity": turbidity,
        "alerts": {"count": int(len(alerts)), "ha": round(float(alerts.area_ha.sum()), 1),
                   "near_river": int(alerts.near_river.sum()), "protected": int(alerts.in_protected_area.sum())},
        "licensed_source": licensed_source,
        "reserves": sorted(set(res["NAME"])) if not res.empty else [],
        "layers": layers,
    }
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote layers and summary to {DATA}")


if __name__ == "__main__":
    main()
