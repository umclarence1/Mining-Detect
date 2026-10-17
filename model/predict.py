"""Run the trained U-Net over the Tarkwa block for each period and save GeoTIFF mosaics.

Run from the project folder:
    python -m model.predict                    # uses the best experiment in report/results.json
    python -m model.predict --experiment rgb

Writes to outputs/predictions/:
    {period}_prob.tif   mining probability (0-255)
    {period}_mask.tif   predicted mining (1/0)
    {period}_label.tif  provisional training labels, for comparison
    {period}_rgb.tif    true-colour image
"""
import argparse
import json

import numpy as np
import rasterio
import torch
from rasterio.transform import from_origin

from common.config import ROOT, load_config
from model.dataset import band_indices, band_stats, normalise, read_split
from model.train import build_model


def best_experiment(cfg: dict) -> str:
    path = ROOT / "report" / "results.json"
    if path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
        scored = {e: res[f"unet_{e}"]["iou"] for e in cfg["model"]["experiments"] if f"unet_{e}" in res}
        if scored:
            return max(scored, key=scored.get)
    return "all_bands"


def write_tif(path, array, transform, crs):
    bands = array if array.ndim == 3 else array[None]
    with rasterio.open(path, "w", driver="GTiff", height=bands.shape[1], width=bands.shape[2], count=bands.shape[0],
                       dtype=bands.dtype, crs=crs, transform=transform, compress="deflate") as dst:
        dst.write(bands)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", choices=["rgb", "all_bands"])
    args = parser.parse_args()

    cfg = load_config()
    torch.set_num_threads(cfg["model"]["num_threads"])
    exp = args.experiment or best_experiment(cfg)
    model = build_model(cfg, exp, pretrained=False)
    model.load_state_dict(torch.load(ROOT / cfg["model"]["checkpoint_dir"] / f"{exp}.pt", map_location="cpu"))
    model.eval()
    idx, stats = band_indices(cfg, exp), band_stats(cfg)
    rgb_idx = band_indices(cfg, "rgb")

    size, scale = cfg["tiles"]["size_px"], cfg["imagery"]["scale_m"]
    tile_dir = ROOT / cfg["tiles"]["out_dir"]
    out_dir = ROOT / "outputs" / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = read_split(cfg, "test")

    for period in cfg["periods"]:
        tiles = [np.load(tile_dir / f) for f in files if f.split("/")[1].startswith(period + "_")]
        xs = sorted({float(t["x0"]) for t in tiles})
        ys = sorted({float(t["y0"]) for t in tiles}, reverse=True)
        h, w = len(ys) * size, len(xs) * size
        prob = np.zeros((h, w), np.float32)
        label = np.zeros((h, w), np.uint8)
        rgb = np.zeros((3, h, w), np.uint8)
        with torch.no_grad():
            for t in tiles:
                r, c = ys.index(float(t["y0"])) * size, xs.index(float(t["x0"])) * size
                x = torch.from_numpy(normalise(t["image"], stats, idx))[None]
                prob[r:r + size, c:c + size] = torch.sigmoid(model(x))[0, 0].numpy()
                label[r:r + size, c:c + size] = t["label"]
                rgb[:, r:r + size, c:c + size] = np.clip(t["image"][rgb_idx] / 3000 * 255, 0, 255).astype(np.uint8)

        transform = from_origin(xs[0], ys[0], scale, scale)
        crs = cfg["tiles"]["crs"]
        mask = (prob > cfg["analysis"]["prob_threshold"]).astype(np.uint8)
        write_tif(out_dir / f"{period}_prob.tif", (prob * 255).astype(np.uint8), transform, crs)
        write_tif(out_dir / f"{period}_mask.tif", mask, transform, crs)
        write_tif(out_dir / f"{period}_label.tif", label, transform, crs)
        write_tif(out_dir / f"{period}_rgb.tif", rgb, transform, crs)
        print(f"{period}: {len(tiles)} tiles -> {h}x{w} px mosaic, {mask.mean():.1%} predicted mining")

    (out_dir / "model_used.txt").write_text(exp + "\n", encoding="utf-8")
    print(f"Used experiment: {exp}")


if __name__ == "__main__":
    main()
