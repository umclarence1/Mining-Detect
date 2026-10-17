"""Save PNG snapshots of the composites, for quick checks and the report.

Run from the project folder:
    python -m gee.thumbnails                     # Tarkwa test block
    python -m gee.thumbnails --region train --size 1600
"""
import argparse
import urllib.request

from common.config import ROOT
from gee.composite import VIS
from gee.utils import build_composite, init_ee, region_geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="test_tarkwa", help="region name in config.yaml")
    parser.add_argument("--periods", nargs="+", default=["baseline", "recent"], help="period names in config.yaml")
    parser.add_argument("--size", type=int, default=1024, help="longest side in pixels")
    args = parser.parse_args()

    cfg = init_ee()
    geom = region_geometry(cfg, args.region)
    out_dir = ROOT / "outputs" / "maps"

    for period in args.periods:
        composite = build_composite(cfg, period, geom)
        for name, vis in VIS.items():
            url = composite.getThumbURL({**vis, "region": geom, "dimensions": args.size, "format": "png"})
            out = out_dir / f"{args.region}_{period}_{name.lower().replace(' ', '_')}.png"
            urllib.request.urlretrieve(url, out)
            print(f"Saved {out}")


if __name__ == "__main__":
    main()
