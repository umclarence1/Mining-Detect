"""Galamsey Detector web app.

Run from the project folder (after webapp.build_assets):
    python -m webapp.server            # then open http://localhost:8050
    python -m webapp.server --port 9000

API
    GET /api/summary                      every headline number and layer bounds
    GET /api/alerts                       new-mining sites as GeoJSON; filters:
        ?min_area=5&near_river=true&protected=true&sort=priority|area&limit=100
    GET /api/alerts/{rank}                one site
    GET /api/alerts/{rank}/chip/{year}    before/after crop (year = 2020 or 2026), JPEG
    GET /api/alerts.csv                   the filtered list as CSV
"""
import io
import json
from functools import lru_cache

import geopandas as gpd
import rasterio
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from rasterio.windows import Window

from app.build_map import rgb_image
from common.config import ROOT

STATIC = ROOT / "webapp" / "static"
PRED = ROOT / "outputs" / "predictions"
# Top alerts checked by eye against the 2020/2026 composites (report section 5.3).
VERDICTS = {1: "New industrial works", 2: "Industrial pit expansion", 3: "Galamsey along a stream", 4: "Galamsey along a stream"}

app = FastAPI(title="Galamsey Detector", docs_url="/api/docs")


@lru_cache
def alerts() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(ROOT / "outputs" / "maps" / "alerts.geojson")
    gdf["verdict"] = gdf["rank"].map(VERDICTS).fillna("")
    return gdf


@lru_cache
def raster(year: str):
    name = {"2020": "baseline_rgb.tif", "2026": "recent_rgb.tif"}[year]
    return rasterio.open(PRED / name)


def filtered(min_area: float, near_river: bool | None, protected: bool | None, sort: str, limit: int) -> gpd.GeoDataFrame:
    gdf = alerts()
    gdf = gdf[gdf.area_ha >= min_area]
    if near_river is not None:
        gdf = gdf[gdf.near_river == near_river]
    if protected is not None:
        gdf = gdf[gdf.in_protected_area == protected]
    gdf = gdf.sort_values("area_ha" if sort == "area" else "priority", ascending=False)
    return gdf.head(limit)


@app.get("/api/summary")
def summary():
    return json.loads((STATIC / "data" / "summary.json").read_text(encoding="utf-8"))


@app.get("/api/alerts")
def list_alerts(min_area: float = 0, near_river: bool | None = None, protected: bool | None = None,
                sort: str = Query("priority", pattern="^(priority|area)$"), limit: int = Query(200, le=2000)):
    gdf = filtered(min_area, near_river, protected, sort, limit)
    out = json.loads(gdf.to_json())
    out["total_matching"] = int(len(filtered(min_area, near_river, protected, sort, 100000)))
    return out


@app.get("/api/alerts.csv")
def alerts_csv(min_area: float = 0, near_river: bool | None = None, protected: bool | None = None,
               sort: str = Query("priority", pattern="^(priority|area)$")):
    gdf = filtered(min_area, near_river, protected, sort, 100000)
    csv = gdf.drop(columns="geometry").to_csv(index=False)
    return Response(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=galamsey_alerts.csv"})


@app.get("/api/alerts/{rank}")
def get_alert(rank: int):
    gdf = alerts()
    row = gdf[gdf["rank"] == rank]
    if row.empty:
        raise HTTPException(404, f"No alert with rank {rank}")
    return json.loads(row.to_json())["features"][0]


@app.get("/api/alerts/{rank}/chip/{year}")
def chip(rank: int, year: str, size: int = Query(320, ge=64, le=800)):
    if year not in ("2020", "2026"):
        raise HTTPException(400, "year must be 2020 or 2026")
    gdf = alerts()
    row = gdf[gdf["rank"] == rank]
    if row.empty:
        raise HTTPException(404, f"No alert with rank {rank}")
    src = raster(year)
    geom = row.to_crs(src.crs).geometry.iloc[0]
    x0, y0, x1, y1 = geom.bounds
    half = max(x1 - x0, y1 - y0) / 2 + 300
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r0, c0 = src.index(cx - half, cy + half)
    r1, c1 = src.index(cx + half, cy - half)
    win = Window(c0, r0, c1 - c0, r1 - r0)
    arr = src.read(window=win, boundless=True, fill_value=0)
    img = rgb_image(arr).resize((size, size), Image.LANCZOS)
    if year == "2026":
        draw = ImageDraw.Draw(img)
        sx, sy = size / (c1 - c0), size / (r1 - r0)
        polys = getattr(geom, "geoms", [geom])
        for p in polys:
            pts = [((src.index(x, y)[1] - c0) * sx, (src.index(x, y)[0] - r0) * sy) for x, y in p.exterior.coords]
            draw.line(pts + pts[:1], fill=(236, 72, 153), width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8050)
    uvicorn.run("webapp.server:app", host="127.0.0.1", port=parser.parse_args().port)
