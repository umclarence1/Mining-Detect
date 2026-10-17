"""Training labels as an Earth Engine image (1 = mining, 0 = background).

Until hand labels exist, labels are provisional:
  - Maus et al. polygons, keeping only bare ground and water inside them
    (the polygons are coarse and include forest), plus
  - a galamsey rule: bare soil or muddy water close to a stream, not built-up.
Hand-labelled polygons in labels/hand_labels.geojson override both:
class 1 polygons are forced to mining, class 0 polygons to background.

Run from the project folder to save a QA snapshot of the labels:
    python -m gee.labels
"""
import argparse
import urllib.request

import ee
import geopandas as gpd

from common.config import ROOT
from gee.utils import build_composite, init_ee, region_geometry


def _fc_from_gdf(gdf: gpd.GeoDataFrame) -> ee.FeatureCollection:
    return ee.FeatureCollection(gdf.to_crs(4326).__geo_interface__)


def maus_gdf(cfg: dict) -> gpd.GeoDataFrame:
    """Maus polygons inside the training region, in EPSG:4326."""
    min_lon, min_lat, max_lon, max_lat = cfg["regions"]["train"]
    gdf = gpd.read_file(ROOT / cfg["labels"]["maus_file"], bbox=(min_lon, min_lat, max_lon, max_lat))
    gdf["geometry"] = gdf.geometry.simplify(0.0001)
    return gdf[["geometry"]]


def maus_polygons(cfg: dict, gdf: gpd.GeoDataFrame | None = None) -> ee.FeatureCollection:
    gdf = maus_gdf(cfg) if gdf is None else gdf
    if gdf.empty:
        return ee.FeatureCollection([])
    return _fc_from_gdf(gdf)


def licensed_gdf(cfg: dict) -> tuple[gpd.GeoDataFrame, str]:
    """Licensed-mining footprint: concession boundaries if available, else Maus as a rough proxy."""
    path = ROOT / cfg["labels"]["concessions_file"]
    if path.exists():
        gdf = gpd.read_file(path)
        if not gdf.empty:
            return gdf.to_crs(4326)[["geometry"]], "concessions"
    return maus_gdf(cfg), "Maus industrial footprint (proxy)"


def hand_labels_exist(cfg: dict) -> bool:
    path = ROOT / cfg["labels"]["hand_labels"]
    return path.exists() and not gpd.read_file(path).empty


def hand_area_gdf(cfg: dict) -> gpd.GeoDataFrame | None:
    """Squares that have been labelled completely by hand (both periods)."""
    path = ROOT / cfg["labels"]["hand_label_areas"]
    if not path.exists():
        return None
    gdf = gpd.read_file(path)
    return None if gdf.empty else gdf.to_crs(4326)[["geometry"]]


def checked_image(cfg: dict) -> ee.Image:
    """1 inside completely hand-labelled squares, else 0."""
    gdf = hand_area_gdf(cfg)
    if gdf is None:
        return ee.Image(0).toUint8().rename("checked")
    return ee.Image(0).paint(_fc_from_gdf(gdf), 1).toUint8().rename("checked")


def hand_polygons(cfg: dict, period: str | None = None) -> ee.FeatureCollection | None:
    """Hand-labelled polygons for a period (all periods if the file has no 'period' field)."""
    path = ROOT / cfg["labels"]["hand_labels"]
    if not path.exists():
        return None
    gdf = gpd.read_file(path)
    if period is not None and "period" in gdf.columns:
        gdf = gdf[gdf["period"] == period]
    if gdf.empty:
        return None
    gdf["class"] = gdf["class"].astype(int)
    return _fc_from_gdf(gdf[["class", "geometry"]])


def indices(composite: ee.Image) -> dict:
    return {
        "ndvi": composite.normalizedDifference(["B8", "B4"]),
        "mndwi": composite.normalizedDifference(["B3", "B11"]),
        "red": composite.select("B4"),
    }


def label_image(
    cfg: dict,
    period: str,
    geom: ee.Geometry,
    maus: ee.FeatureCollection | None = None,
    composite: ee.Image | None = None,
    hand: ee.FeatureCollection | None = None,
) -> ee.Image:
    rule = cfg["labels"]["rule"]
    composite = build_composite(cfg, period, geom) if composite is None else composite
    idx = indices(composite)
    water = idx["mndwi"].gt(0)
    bare = idx["ndvi"].lt(rule["ndvi_max"]).And(idx["mndwi"].lte(rule["mndwi_bare_max"]))
    turbid = water.And(idx["red"].gt(rule["turbid_red_min"]))

    built = ee.ImageCollection(rule["worldcover"]).first().select("Map").eq(50)
    streams = ee.Image("MERIT/Hydro/v1_0_1").select("upa").gte(rule["stream_upa_km2"])
    near_stream = streams.selfMask().focalMax(radius=rule["stream_buffer_m"], units="meters").unmask(0)

    in_maus = ee.Image(0).paint(maus if maus is not None else maus_polygons(cfg), 1)

    galamsey = bare.Or(turbid).And(near_stream).And(built.Not())
    industrial = in_maus.And(bare.Or(water)).And(built.Not())
    label = galamsey.Or(industrial)

    # Remove thin roads and specks.
    label = label.focalMin(1, "square", "pixels").focalMax(1, "square", "pixels")
    label = label.And(label.connectedPixelCount(64, True).gte(rule["min_patch_px"]))

    # Inside completely labelled squares, drop the rule: only hand labels count there.
    label = label.where(checked_image(cfg).eq(1), 0)

    hand = hand_polygons(cfg, period) if hand is None else hand
    if hand is not None:
        hand_img = ee.Image(255).paint(hand, "class")
        label = label.where(hand_img.neq(255), hand_img)

    return label.unmask(0).rename("label").toUint8()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="test_tarkwa")
    parser.add_argument("--periods", nargs="+", default=["baseline", "recent"])
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()

    cfg = init_ee()
    geom = region_geometry(cfg, args.region)
    maus = maus_polygons(cfg)
    for period in args.periods:
        rgb = build_composite(cfg, period, geom).visualize(bands=["B4", "B3", "B2"], min=0, max=3000)
        mask = label_image(cfg, period, geom, maus).selfMask().visualize(palette=["ff0000"], opacity=0.55)
        url = rgb.blend(mask).getThumbURL({"region": geom, "dimensions": args.size, "format": "png"})
        out = ROOT / "outputs" / "maps" / f"{args.region}_{period}_labels.png"
        urllib.request.urlretrieve(url, out)
        print(f"Saved {out}")


if __name__ == "__main__":
    main()
