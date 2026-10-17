"""Write the Tarkwa test tiles as numbered squares, for choosing which ones to hand-label.

Run from the project folder (works offline):
    python -m gee.label_squares

Writes labels/test_squares.geojson. Copy the squares you finish labelling into
labels/hand_label_areas.geojson (see docs/labeling_guide.md).
"""
import geopandas as gpd
from shapely.geometry import box

from common.config import ROOT, load_config
from gee.export_tiles import tile_grid


def main():
    cfg = load_config()
    step = cfg["tiles"]["size_px"] * cfg["imagery"]["scale_m"]
    test = tile_grid(cfg).query("is_test").sort_values(["y0", "x0"], ascending=[False, True]).reset_index(drop=True)
    gdf = gpd.GeoDataFrame(
        {"square": range(1, len(test) + 1), "tile": test.tile},
        geometry=[box(x, y - step, x + step, y) for x, y in zip(test.x0, test.y0)],
        crs=cfg["tiles"]["crs"],
    ).to_crs(4326)
    out = ROOT / "labels" / "test_squares.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"Wrote {len(gdf)} squares (numbered left to right, top to bottom) to {out}")


if __name__ == "__main__":
    main()
