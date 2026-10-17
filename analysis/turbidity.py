"""River turbidity, 2020 vs 2026, along the main rivers of the training region.

Run from the project folder:
    python -m analysis.turbidity

Uses the Normalised Difference Turbidity Index, NDTI = (red - green) / (red + green),
on water pixels of large rivers (MERIT Hydro upstream area >= 1000 km2).
Higher NDTI means muddier water. Writes report/turbidity.json.
"""
import json

import ee

from common.config import ROOT
from gee.utils import build_composite, init_ee, region_geometry

RIVER_UPA_KM2 = 1000


def main():
    cfg = init_ee()
    geom = region_geometry(cfg, "train")
    rivers = ee.Image("MERIT/Hydro/v1_0_1").select("upa").gte(RIVER_UPA_KM2)
    near_river = rivers.selfMask().focalMax(radius=150, units="meters").unmask(0)
    res = {}
    for period in cfg["periods"]:
        c = build_composite(cfg, period, geom)
        water = c.normalizedDifference(["B3", "B11"]).gt(0.1).And(near_river)
        ndti = c.normalizedDifference(["B4", "B3"]).rename("ndti").updateMask(water)
        stats = ndti.addBands(c.select("B4").rename("red").updateMask(water)).reduceRegion(
            ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), geom, scale=20, maxPixels=1e10, tileScale=4
        ).getInfo()
        res[period] = {"ndti_mean": stats["ndti_mean"], "red_reflectance_mean": stats["red_mean"] / 1e4,
                       "water_pixels_20m": stats["ndti_count"]}
        print(f"{period:9s} NDTI {stats['ndti_mean']:+.3f}  red {stats['red_mean'] / 1e4:.3f}  "
              f"({stats['ndti_count']:,} river pixels)")
    (ROOT / "report" / "turbidity.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
