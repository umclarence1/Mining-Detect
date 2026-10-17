"""2020 -> 2026 change in mining over the Tarkwa block, in hectares.

Run from the project folder (after model.predict):
    python -m analysis.change

Pixel counting is biased, so this also handles error-adjusted area
(Olofsson et al., 2014):
  1. The first run writes outputs/predictions/area_sample.csv - random points
     stratified by the change map, with an empty `reference` column.
  2. Label each point by eye (1 = newly disturbed by mining, 0 = not) using
     high-resolution imagery, and save the file.
  3. Rerun: the report then includes the adjusted area with a 95% interval.
"""
import json

import numpy as np
import pandas as pd
from pyproj import Transformer

from analysis.rasters import PRED_DIR, burn, read, remove_small
from common.config import ROOT, load_config
from gee.labels import licensed_gdf

PIXEL_HA = 0.01  # 10 m x 10 m
STRATA = {1: "new mining", 2: "stable mining", 3: "no mining"}
SAMPLE_SIZE = {1: 60, 2: 30, 3: 90}


def change_map(cfg: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    min_px = int(cfg["analysis"]["min_patch_ha"] / PIXEL_HA)
    before, profile = read("baseline_mask")
    after, _ = read("recent_mask")
    before, after = remove_small(before, min_px), remove_small(after, min_px)
    return before, after, (after == 1) & (before == 0), profile


def olofsson(sample: pd.DataFrame, stratum_px: dict) -> dict:
    """Error-adjusted area of 'new mining' with a 95% confidence interval."""
    total = sum(stratum_px.values())
    p, var = 0.0, 0.0
    for h, n_px in stratum_px.items():
        s = sample[sample.stratum == h]
        if len(s) < 2:
            continue
        w = n_px / total
        share = s.reference.mean()
        p += w * share
        var += w ** 2 * share * (1 - share) / (len(s) - 1)
    area = p * total * PIXEL_HA
    ci = 1.96 * np.sqrt(var) * total * PIXEL_HA
    # Accuracy of the map's "new mining" stratum against the reference labels.
    new = sample[sample.stratum == 1]
    users = float(new.reference.mean()) if len(new) else float("nan")
    return {"adjusted_new_ha": round(float(area), 1), "ci95_ha": round(float(ci), 1),
            "users_accuracy_new": round(users, 3), "points_labelled": int(len(sample))}


def draw_sample(strata: np.ndarray, profile: dict, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    to_ll = Transformer.from_crs(profile["crs"], "EPSG:4326", always_xy=True)
    rows = []
    for h, n in SAMPLE_SIZE.items():
        r, c = np.nonzero(strata == h)
        if len(r) == 0:
            continue
        pick = rng.choice(len(r), size=min(n, len(r)), replace=False)
        x = profile["transform"].c + (c[pick] + 0.5) * profile["transform"].a
        y = profile["transform"].f + (r[pick] + 0.5) * profile["transform"].e
        lon, lat = to_ll.transform(x, y)
        rows += [{"id": f"{h}-{i}", "stratum": h, "stratum_name": STRATA[h], "lon": lo, "lat": la, "reference": ""}
                 for i, (lo, la) in enumerate(zip(lon, lat))]
    df = pd.DataFrame(rows).sample(frac=1, random_state=seed).reset_index(drop=True)  # shuffle: label blind
    return df


def main():
    cfg = load_config()
    before, after, new, profile = change_map(cfg)
    licensed, licensed_source = licensed_gdf(cfg)
    industrial = burn(licensed, profile).astype(bool)

    def ha(m):
        return float(m.sum() * PIXEL_HA)

    res = {
        "area_ha": ha(np.ones_like(before)),
        "mining_2020_ha": ha(before == 1),
        "mining_2026_ha": ha(after == 1),
        "new_mining_ha": ha(new),
        "no_longer_mining_ha": ha((before == 1) & (after == 0)),
        "new_mining_outside_licensed_ha": ha(new & ~industrial),
        "new_mining_inside_licensed_ha": ha(new & industrial),
        "licensed_footprint_source": licensed_source,
    }
    res["mining_2020_pct"] = 100 * res["mining_2020_ha"] / res["area_ha"]
    res["mining_2026_pct"] = 100 * res["mining_2026_ha"] / res["area_ha"]

    strata = np.where(new, 1, np.where((after == 1) & (before == 1), 2, 3))
    sample_path = PRED_DIR / "area_sample.csv"
    if not sample_path.exists():
        draw_sample(strata, profile, cfg["project"]["seed"]).to_csv(sample_path, index=False)
        print(f"Wrote {sample_path}: label the `reference` column (1/0) and rerun for error-adjusted area.")
    else:
        sample = pd.read_csv(sample_path)
        sample = sample[pd.to_numeric(sample.reference, errors="coerce").notna()].copy()
        sample["reference"] = sample.reference.astype(int)
        if len(sample) >= 30:
            res["olofsson"] = olofsson(sample, {h: int((strata == h).sum()) for h in STRATA})
        else:
            print(f"Only {len(sample)} sample points labelled; need 30+ for error-adjusted area.")

    np.save(PRED_DIR / "new_mining.npy", new.astype(np.uint8))
    (ROOT / "report" / "change.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(f"{k:36s} {v:,.1f}" if isinstance(v, float) else f"{k:36s} {v}")


if __name__ == "__main__":
    main()
