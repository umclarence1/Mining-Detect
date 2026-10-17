"""Build the one-page results dashboard: outputs/dashboard/index.html.

Run from the project folder (after app.build_map):
    python -m app.build_dashboard

Everything (images, numbers) is embedded, so the file works offline and can be
published as is. Alert locations are aggregated to ~1 km cells and rounded to
0.01 degrees so the page never acts as a precise target list.
"""
import base64
import io
import json

import geopandas as gpd
import numpy as np
from PIL import Image
from rasterio.features import rasterize

from analysis.rasters import PRED_DIR, burn, read, remove_small
from app.build_map import rgb_image
from common.config import ROOT, load_config
from gee.labels import licensed_gdf, maus_gdf

OUT = ROOT / "outputs" / "dashboard"
TEMPLATE = ROOT / "app" / "dashboard_template.html"
CELL_PX = 100  # 1 km at 10 m
RED = (229, 72, 77)


def jpeg_uri(img: Image.Image, width: int, quality: int = 82) -> str:
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def tint(img: Image.Image, mask: np.ndarray, colour=RED, alpha=0.6) -> Image.Image:
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    m = mask.astype(bool)
    arr[m] = arr[m] * (1 - alpha) + np.array(colour) * alpha
    return Image.fromarray(arr.astype(np.uint8))


def outline(img: Image.Image, gdf: gpd.GeoDataFrame, profile: dict, colour=(80, 220, 255)) -> Image.Image:
    """Draw polygon boundaries on a mosaic-sized image."""
    if gdf.empty:
        return img
    shape = (profile["height"], profile["width"])
    filled = rasterize(((g, 1) for g in gdf.to_crs(profile["crs"]).geometry), out_shape=shape,
                       transform=profile["transform"], dtype="uint8").astype(bool)
    edge = filled & ~(np.roll(filled, 7, 0) & np.roll(filled, -7, 0) & np.roll(filled, 7, 1) & np.roll(filled, -7, 1))
    arr = np.asarray(img).copy()
    arr[edge] = colour
    return Image.fromarray(arr)


def cell_grid(mask: np.ndarray) -> list[list[float]]:
    """Hectares of mask per ~1 km cell."""
    h, w = mask.shape
    rows, cols = h // CELL_PX, w // CELL_PX
    m = mask[: rows * CELL_PX, : cols * CELL_PX].reshape(rows, CELL_PX, cols, CELL_PX)
    return (m.sum(axis=(1, 3)) * 0.01).round(1).tolist()


def alert_chips(alerts: gpd.GeoDataFrame, rgb0, rgb1, profile, verdicts: dict, n: int = 4) -> list[dict]:
    """Before/after crops of the top alerts, with the result of a visual check."""
    chips = []
    t = profile["transform"]
    for r in alerts.head(n).to_crs(profile["crs"]).itertuples():
        x0, y0, x1, y1 = r.geometry.bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        half = max(x1 - x0, y1 - y0) / 2 + 400
        c0, c1 = int((cx - half - t.c) / t.a), int((cx + half - t.c) / t.a)
        r0, r1 = int((cy + half - t.f) / t.e), int((cy - half - t.f) / t.e)
        c0, r0 = max(c0, 0), max(r0, 0)
        def crop(im: Image.Image, win=(c0, r0, c1, r1)) -> Image.Image:
            return im.crop((win[0], win[1], min(win[2], im.width), min(win[3], im.height))).resize((360, 360), Image.LANCZOS)

        after = crop(rgb1)
        poly = gpd.GeoSeries([r.geometry], crs=profile["crs"])
        mask = rasterize(((g, 1) for g in poly), out_shape=(profile["height"], profile["width"]),
                         transform=t, dtype="uint8")[r0:r1, c0:c1]
        mask_img = Image.fromarray(mask * 255).resize((360, 360), Image.NEAREST)
        m = np.asarray(mask_img) > 0
        edge = m & ~(np.roll(m, 2, 0) & np.roll(m, -2, 0) & np.roll(m, 2, 1) & np.roll(m, -2, 1))
        a = np.asarray(after).copy()
        a[edge] = (255, 0, 255)
        chips.append({
            "rank": int(r.rank), "area_ha": float(r.area_ha), "verdict": verdicts.get(int(r.rank), "Not checked"),
            "before": jpeg_uri(crop(rgb0), 360), "after": jpeg_uri(Image.fromarray(a), 360),
        })
    return chips


def main():
    cfg = load_config()
    change = json.loads((ROOT / "report" / "change.json").read_text(encoding="utf-8"))
    results = json.loads((ROOT / "report" / "results.json").read_text(encoding="utf-8"))

    rgb0_arr, profile = read("baseline_rgb")
    rgb1_arr, _ = read("recent_rgb")
    m0, _ = read("baseline_mask")
    m1, _ = read("recent_mask")
    new = np.load(PRED_DIR / "new_mining.npy").astype(bool)
    rgb0, rgb1 = rgb_image(rgb0_arr), rgb_image(rgb1_arr)

    licensed, licensed_source = licensed_gdf(cfg)
    industrial = burn(licensed, profile).astype(bool)
    galamsey_new = remove_small(new & ~industrial, int(cfg["analysis"]["min_patch_ha"] / 0.01)).astype(bool)

    alerts = gpd.read_file(ROOT / "outputs" / "maps" / "alerts.geojson")
    # Top alerts checked by eye against the 2020/2026 composites (see report 5.3).
    verdicts = {1: "New industrial works", 2: "Industrial pit expansion", 3: "Galamsey along a stream",
                4: "Galamsey along a stream"}

    data = {
        "change": change,
        "results": {k: v for k, v in results.items() if isinstance(v, dict)},
        "alerts_total": int(len(alerts)),
        "alerts_ha": round(float(alerts.area_ha.sum())),
        "alerts_near_river": int(alerts.near_river.sum()),
        "alerts_protected": int(alerts.in_protected_area.sum()),
        "top": [
            {"rank": int(r.rank), "area_ha": float(r.area_ha), "lat": round(float(r.lat), 2), "lon": round(float(r.lon), 2),
             "near_river": bool(r.near_river), "protected": bool(r.in_protected_area), "confidence": float(r.confidence)}
            for r in alerts.head(10).itertuples()
        ],
        "grid": cell_grid(galamsey_new),
        "grid_km": CELL_PX * 10 / 1000,
        "extent_cells": [profile["width"] / CELL_PX, profile["height"] / CELL_PX],
        "licensed_source": licensed_source,
    }

    images = {
        "IMG_BEFORE": jpeg_uri(rgb0, 1400),
        "IMG_AFTER": jpeg_uri(rgb1, 1400),
        "IMG_BEFORE_MASK": jpeg_uri(tint(rgb0, m0), 1400),
        "IMG_AFTER_MASK": jpeg_uri(tint(rgb1, m1), 1400),
        "IMG_GRID_BASE": jpeg_uri(rgb1.convert("L").convert("RGB"), 1000, 70),
        "IMG_MAUS": jpeg_uri(outline(tint(rgb1, m1, alpha=0.55), maus_gdf(cfg), profile), 1100),
    }
    data["chips"] = alert_chips(alerts, rgb0, rgb1, profile, verdicts)

    html = TEMPLATE.read_text(encoding="utf-8")
    for key, uri in images.items():
        html = html.replace("{{" + key + "}}", uri)
    html = html.replace("/*{{DATA}}*/null", json.dumps(data))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    # index.html is the publishable body; preview.html wraps it in a document for local browsers.
    shell = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>')
    (OUT / "preview.html").write_text(shell + html + "</body></html>", encoding="utf-8")
    print(f"Saved {OUT / 'index.html'} and preview.html ({len(html) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
