"""Turn new mining (2020 -> 2026) into a ranked list of sites to look at first.

Run from the project folder (after analysis.change):
    python -m analysis.alerts

Only new mining outside the licensed footprint (concessions if available, else
the Maus industrial-mine footprint) becomes an alert. Priority goes up for
sites near streams and inside protected areas (e.g. forest reserves, WDPA). Writes
outputs/maps/alerts.geojson and outputs/maps/alerts.csv.
"""
import ee
import geopandas as gpd
import numpy as np
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape

from analysis.rasters import PRED_DIR, burn, read, remove_small
from common.config import ROOT
from gee.labels import licensed_gdf
from gee.utils import init_ee, region_geometry

PIXEL_HA = 0.01


def stream_distance_m(cfg: dict, profile: dict) -> np.ndarray:
    """Distance from each pixel to the nearest stream (MERIT Hydro), on the mosaic grid."""
    streams = ee.Image("MERIT/Hydro/v1_0_1").select("upa").gte(cfg["labels"]["rule"]["stream_upa_km2"]).toUint8()
    t = profile["transform"]
    arr = ee.data.computePixels({
        "expression": streams,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": profile["width"], "height": profile["height"]},
            "affineTransform": {"scaleX": t.a, "shearX": 0, "translateX": t.c, "shearY": 0, "scaleY": t.e, "translateY": t.f},
            "crsCode": str(profile["crs"]),
        },
    })
    is_stream = arr["upa"].astype(bool)
    return ndimage.distance_transform_edt(~is_stream) * abs(t.a)


def protected_areas(cfg: dict) -> gpd.GeoDataFrame:
    fc = ee.FeatureCollection("WCMC/WDPA/current/polygons").filterBounds(region_geometry(cfg, "test_tarkwa"))
    info = fc.select(["NAME", "DESIG_ENG"]).getInfo()
    if not info["features"]:
        return gpd.GeoDataFrame(columns=["NAME", "geometry"], geometry="geometry", crs=4326)
    return gpd.GeoDataFrame.from_features(info["features"], crs=4326)


def main():
    cfg = init_ee()
    new = np.load(PRED_DIR / "new_mining.npy")
    prob, profile = read("recent_prob")
    new = remove_small(new, int(cfg["analysis"]["min_patch_ha"] / PIXEL_HA))

    dist = stream_distance_m(cfg, profile)
    pa = protected_areas(cfg)
    in_pa = burn(pa, profile).astype(bool)
    licensed, licensed_source = licensed_gdf(cfg)
    industrial = burn(licensed, profile).astype(bool)
    # Alerts cover mining outside the licensed footprint only; otherwise changes inside big
    # industrial mines merge with neighbouring galamsey and dominate the ranking.
    inside_ha = float((new.astype(bool) & industrial).sum() * PIXEL_HA)
    new = remove_small(new.astype(bool) & ~industrial, int(cfg["analysis"]["min_patch_ha"] / PIXEL_HA))

    lab, n = ndimage.label(new, structure=np.ones((3, 3)))
    idx = np.arange(1, n + 1)
    area = ndimage.sum(np.ones_like(lab), lab, idx) * PIXEL_HA
    min_dist = ndimage.minimum(dist, lab, idx)
    pa_share = ndimage.mean(in_pa, lab, idx)
    ind_share = ndimage.mean(industrial, lab, idx)
    conf = ndimage.mean(prob / 255, lab, idx)

    polys = {}
    for geom, value in shapes(lab.astype(np.int32), mask=lab > 0, transform=profile["transform"]):
        polys.setdefault(int(value), []).append(shape(geom))
    river_buffer = cfg["analysis"]["river_buffer_m"]
    rows = []
    for k in idx:
        i = k - 1
        near_river = min_dist[i] <= river_buffer
        score = area[i] * (2.0 if near_river else 1.0) * (1.5 if pa_share[i] > 0.5 else 1.0)
        geom = gpd.GeoSeries(polys[int(k)]).union_all()
        rows.append({
            "area_ha": round(float(area[i]), 2),
            "dist_to_stream_m": round(float(min_dist[i])),
            "near_river": bool(near_river),
            "in_protected_area": bool(pa_share[i] > 0.5),
            "likely_industrial": bool(ind_share[i] > 0.5),
            "confidence": round(float(conf[i]), 2),
            "priority": round(float(score), 2),
            "geometry": geom,
        })
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=profile["crs"]).to_crs(4326)
    gdf = gdf.sort_values("priority", ascending=False).reset_index(drop=True)
    gdf.insert(0, "rank", range(1, len(gdf) + 1))
    c = gdf.geometry.representative_point()
    gdf["lon"], gdf["lat"] = c.x.round(5), c.y.round(5)

    out = ROOT / "outputs" / "maps"
    gdf.to_file(out / "alerts.geojson", driver="GeoJSON")
    gdf.drop(columns="geometry").to_csv(out / "alerts.csv", index=False)
    pa_names = ", ".join(sorted(set(pa["NAME"]))) if not pa.empty else "none found"
    print(f"{len(gdf)} new-mining sites outside the licensed footprint ({licensed_source}), "
          f"{gdf.area_ha.sum():,.0f} ha; {int(gdf.near_river.sum())} within {river_buffer} m of a stream; "
          f"{int(gdf.in_protected_area.sum())} in protected areas ({pa_names}). "
          f"Excluded {inside_ha:,.0f} ha of new mining inside the licensed footprint.")
    print(gdf.head(10).drop(columns="geometry").to_string(index=False))


if __name__ == "__main__":
    main()
