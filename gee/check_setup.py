"""Check that Earth Engine works with this project.

Run from the project folder:
    python -m gee.check_setup
"""
import ee

from gee.utils import init_ee, region_geometry


def main():
    cfg = init_ee()
    print(f"Earth Engine initialised for project: {cfg['project']['gee_project']}")

    geom = region_geometry(cfg, "test_tarkwa")
    p = cfg["periods"]["baseline"]
    n = (
        ee.ImageCollection(cfg["imagery"]["collection"])
        .filterBounds(geom)
        .filterDate(p["start"], p["end"])
        .size()
        .getInfo()
    )
    print(f"Sentinel-2 scenes over Tarkwa, {p['start']} to {p['end']}: {n}")
    print("Setup OK" if n > 0 else "Connected, but no scenes found - check region/dates in config.yaml")


if __name__ == "__main__":
    main()
