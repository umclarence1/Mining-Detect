import numpy as np
import pandas as pd
import pytest

from analysis.change import PIXEL_HA, olofsson
from analysis.rasters import remove_small


def test_olofsson_perfect_map_returns_mapped_area():
    # Every sample in the "new" stratum is truly new, none elsewhere.
    sample = pd.DataFrame({"stratum": [1] * 10 + [3] * 10, "reference": [1] * 10 + [0] * 10})
    res = olofsson(sample, {1: 1000, 2: 0, 3: 9000})
    assert res["adjusted_new_ha"] == pytest.approx(1000 * PIXEL_HA)
    assert res["ci95_ha"] == pytest.approx(0.0)
    assert res["users_accuracy_new"] == pytest.approx(1.0)


def test_olofsson_counts_omission_in_other_strata():
    # Half of "new" is wrong, and 10% of the large "no mining" stratum is actually new.
    sample = pd.DataFrame({"stratum": [1] * 10 + [3] * 10, "reference": [1] * 5 + [0] * 5 + [1] + [0] * 9})
    res = olofsson(sample, {1: 1000, 2: 0, 3: 9000})
    expected_px = 1000 * 0.5 + 9000 * 0.1
    assert res["adjusted_new_ha"] == pytest.approx(expected_px * PIXEL_HA)
    assert res["ci95_ha"] > 0


def test_remove_small_drops_specks_keeps_patches():
    mask = np.zeros((10, 10), np.uint8)
    mask[0, 0] = 1  # 1-pixel speck
    mask[5:8, 5:8] = 1  # 9-pixel patch
    out = remove_small(mask, min_px=5)
    assert out[0, 0] == 0
    assert out[5:8, 5:8].all()
