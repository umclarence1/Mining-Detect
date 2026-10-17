"""Score the baseline and both U-Nets on the held-out Tarkwa test tiles.

Run from the project folder:
    python -m model.evaluate

Writes report/results.json and report/results.md.
"""
import json

import numpy as np
import torch

from common.config import ROOT, load_config
from gee.labels import hand_labels_exist
from model.dataset import band_indices, band_stats, normalise, read_split
from model.metrics import Counts
from model.train import build_model


def load_test(cfg: dict, files: list[str]) -> list[dict]:
    """Test tiles, each with the pixel mask to score: hand-checked squares if any exist, else everything."""
    tiles = []
    for f in files:
        d = np.load(ROOT / cfg["tiles"]["out_dir"] / f)
        checked = d["checked"] if "checked" in d.files else np.zeros_like(d["label"])
        tiles.append({"image": d["image"], "label": d["label"], "checked": checked.astype(bool)})
    if any(t["checked"].any() for t in tiles):
        return [t for t in tiles if t["checked"].any()]
    for t in tiles:
        t["checked"] = np.ones_like(t["checked"])
    return tiles


def ndvi_baseline(cfg: dict, tiles: list[dict], ndvi_max: float = 0.3) -> dict:
    """Naive baseline: every pixel with NDVI below a threshold is 'mining'."""
    bands = cfg["imagery"]["bands_all"]
    b4, b8 = bands.index("B4"), bands.index("B8")
    counts = Counts()
    for t in tiles:
        red, nir = t["image"][b4].astype(np.float32), t["image"][b8].astype(np.float32)
        ndvi = (nir - red) / np.maximum(nir + red, 1)
        m = t["checked"]
        counts.update((ndvi < ndvi_max)[m], (t["label"] > 0)[m])
    return counts.summary()


@torch.no_grad()
def unet_scores(cfg: dict, exp: str, tiles: list[dict], threshold: float) -> dict:
    model = build_model(cfg, exp, pretrained=False)
    model.load_state_dict(torch.load(ROOT / cfg["model"]["checkpoint_dir"] / f"{exp}.pt", map_location="cpu"))
    model.eval()
    idx, stats = band_indices(cfg, exp), band_stats(cfg)
    counts = Counts()
    for t in tiles:
        x = torch.from_numpy(normalise(t["image"], stats, idx))[None]
        prob = torch.sigmoid(model(x))[0, 0].numpy()
        m = t["checked"]
        counts.update((prob > threshold)[m], (t["label"] > 0)[m])
    return counts.summary()


def main():
    cfg = load_config()
    torch.set_num_threads(cfg["model"]["num_threads"])
    files = read_split(cfg, "test")
    tiles = load_test(cfg, files)
    checked_px = int(sum(t["checked"].sum() for t in tiles))
    hand_scored = checked_px < len(tiles) * tiles[0]["checked"].size if tiles else False
    threshold = cfg["analysis"]["prob_threshold"]
    results = {"test_tiles": len(tiles), "scored_pixels": checked_px, "hand_checked": hand_scored,
               "baseline_ndvi": ndvi_baseline(cfg, tiles)}

    for exp in cfg["model"]["experiments"]:
        if not (ROOT / cfg["model"]["checkpoint_dir"] / f"{exp}.pt").exists():
            print(f"skip {exp}: no checkpoint")
            continue
        results[f"unet_{exp}"] = unet_scores(cfg, exp, tiles, threshold)

    if hand_scored:
        label_note = f"hand labels, inside completely labelled squares only ({checked_px * 0.01:,.0f} ha)"
    elif hand_labels_exist(cfg):
        label_note = "provisional labels with some hand corrections (no completely labelled squares yet)"
    else:
        label_note = "PROVISIONAL rule-based labels (agreement with the rule, not true accuracy)"
    lines = [
        "# Results on the held-out Tarkwa test block",
        "",
        f"Test tiles: {len(tiles)} (2020 and 2026). Scored against {label_note}.",
        "",
        "| Model | IoU | F1 | Precision | Recall |",
        "|---|---|---|---|---|",
    ]
    for name, m in results.items():
        if isinstance(m, dict):
            lines.append(f"| {name} | {m['iou']:.3f} | {m['f1']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} |")
    out = ROOT / "report"
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
