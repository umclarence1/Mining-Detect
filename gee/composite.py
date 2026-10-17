"""Build cloud-masked dry-season composites and save an interactive preview map.

Run from the project folder:
    python -m gee.composite                      # Tarkwa test block, both periods
    python -m gee.composite --region train       # the wider training region

Opens nothing by itself - open outputs/maps/composite_preview.html in a browser.
Earth Engine tile links in the preview expire after a few hours; rerun to refresh.
"""
import argparse

import ee
import folium

from common.config import ROOT
from gee.utils import build_composite, clear_collection, init_ee, region_geometry

VIS = {
    "True colour": {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000},
    # SWIR false colour: bare/mined ground shows bright, vegetation green, water dark.
    "SWIR false colour": {"bands": ["B12", "B8", "B4"], "min": 0, "max": 4000},
}


def coverage_stats(cfg: dict, period: str, geom: ee.Geometry) -> dict:
    """How much of the region has at least one clear observation, and how many on average."""
    clear = clear_collection(cfg, period, geom).select("B4")
    count = clear.count().unmask(0).clip(geom)
    stats = (
        count.gte(1).rename("covered")
        .addBands(count.rename("clear_obs"))
        .reduceRegion(ee.Reducer.mean(), geom, scale=100, maxPixels=1e9)
        .getInfo()
    )
    stats["scenes"] = clear.size().getInfo()
    return stats


def tile_url(image: ee.Image, vis: dict) -> str:
    return image.getMapId(vis)["tile_fetcher"].url_format


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="test_tarkwa", help="region name in config.yaml")
    parser.add_argument("--periods", nargs="+", default=["baseline", "recent"], help="period names in config.yaml")
    args = parser.parse_args()

    cfg = init_ee()
    geom = region_geometry(cfg, args.region)
    min_lon, min_lat, max_lon, max_lat = cfg["regions"][args.region]
    center = [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2]

    fmap = folium.Map(location=center, zoom_start=12 if args.region == "test_tarkwa" else 9, tiles=None)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="High-res basemap (Esri)",
    ).add_to(fmap)

    for period in args.periods:
        p = cfg["periods"][period]
        stats = coverage_stats(cfg, period, geom)
        print(
            f"{period:9s} {p['start']} to {p['end']}: {stats['scenes']} scenes, "
            f"{stats['covered']:.1%} of area has a clear pixel, "
            f"{stats['clear_obs']:.1f} clear observations per pixel on average"
        )

        composite = build_composite(cfg, period, geom)
        for name, vis in VIS.items():
            folium.TileLayer(
                tiles=tile_url(composite, vis), attr="Google Earth Engine / Copernicus Sentinel-2",
                name=f"{period} - {name}", overlay=True, show=(name == "True colour" and period == args.periods[0]),
            ).add_to(fmap)

    folium.GeoJson(geom.getInfo(), name=f"{args.region} boundary",
                   style_function=lambda _: {"color": "yellow", "fill": False, "weight": 2}).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    out = ROOT / "outputs" / "maps" / f"composite_preview_{args.region}.html"
    fmap.save(out)
    print(f"Preview saved: {out}")


if __name__ == "__main__":
    main()
