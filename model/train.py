"""Train the U-Net.

Run from the project folder:
    python -m model.train --experiment rgb
    python -m model.train --experiment all_bands
"""
import argparse
import json
import time

import numpy as np
import segmentation_models_pytorch as smp
import torch
from torch.utils.data import DataLoader

from common.config import ROOT, load_config
from model.dataset import TileDataset, band_indices, read_split
from model.metrics import Counts, dice_bce_loss


def build_model(cfg: dict, experiment: str, pretrained: bool = True) -> torch.nn.Module:
    mcfg = cfg["model"]
    return smp.Unet(
        encoder_name=mcfg["encoder"],
        encoder_weights=mcfg["encoder_weights"] if pretrained else None,
        in_channels=len(band_indices(cfg, experiment)),
        classes=1,
    )


@torch.no_grad()
def evaluate(model, loader, threshold: float) -> dict:
    model.eval()
    counts = Counts()
    for img, lab in loader:
        prob = torch.sigmoid(model(img)).numpy()
        counts.update(prob > threshold, lab.numpy() > 0.5)
    return counts.summary()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", required=True, choices=["rgb", "all_bands"])
    parser.add_argument("--epochs", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config()
    mcfg = cfg["model"]
    torch.manual_seed(cfg["project"]["seed"])
    np.random.seed(cfg["project"]["seed"])
    torch.set_num_threads(mcfg["num_threads"])

    train_ds = TileDataset(cfg, read_split(cfg, "train"), args.experiment, crop=mcfg["crop_px"], augment=True)
    val_ds = TileDataset(cfg, read_split(cfg, "val"), args.experiment)
    train_dl = DataLoader(train_ds, batch_size=mcfg["batch_size"], shuffle=True, drop_last=True)
    val_dl = DataLoader(val_ds, batch_size=8)
    print(f"{args.experiment}: {len(train_ds)} train tiles, {len(val_ds)} val tiles")

    model = build_model(cfg, args.experiment)
    epochs = args.epochs or mcfg["epochs"]
    opt = torch.optim.AdamW(model.parameters(), lr=mcfg["lr"])
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=mcfg["lr"], total_steps=epochs * len(train_dl))
    threshold = cfg["analysis"]["prob_threshold"]

    out_dir = ROOT / mcfg["checkpoint_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    best, history = -1.0, []
    for epoch in range(1, epochs + 1):
        model.train()
        t0, losses = time.time(), []
        for img, lab in train_dl:
            loss = dice_bce_loss(model(img), lab)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            losses.append(loss.item())
        val = evaluate(model, val_dl, threshold)
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), **val})
        print(f"epoch {epoch:2d}  loss {np.mean(losses):.3f}  val IoU {val['iou']:.3f}  F1 {val['f1']:.3f}  "
              f"({time.time() - t0:.0f}s)", flush=True)
        if val["iou"] > best:
            best = val["iou"]
            torch.save(model.state_dict(), out_dir / f"{args.experiment}.pt")

    (out_dir / f"{args.experiment}_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"Best val IoU {best:.3f}; saved {out_dir / (args.experiment + '.pt')}")


if __name__ == "__main__":
    main()
