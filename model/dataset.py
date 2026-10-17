"""Tile dataset: loads exported .npz tiles, normalises bands, crops and augments."""
import json

import numpy as np
import torch
from torch.utils.data import Dataset

from common.config import ROOT


def read_split(cfg: dict, name: str) -> list[str]:
    path = ROOT / cfg["splits"]["out_dir"] / f"{name}.txt"
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def band_indices(cfg: dict, experiment: str) -> list[int]:
    bands = cfg["imagery"]["bands_all"]
    if experiment == "rgb":
        return [bands.index(b) for b in cfg["imagery"]["bands_rgb"]]
    if experiment == "all_bands":
        return list(range(len(bands)))
    raise ValueError(f"unknown experiment: {experiment}")


def band_stats(cfg: dict) -> dict:
    """Per-band mean/std of the training tiles, computed once and cached."""
    path = ROOT / cfg["splits"]["out_dir"] / "band_stats.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    files = read_split(cfg, "train")
    rng = np.random.default_rng(cfg["project"]["seed"])
    sample = rng.choice(files, size=min(200, len(files)), replace=False)
    pixels = np.concatenate([
        np.load(ROOT / cfg["tiles"]["out_dir"] / f)["image"][:, ::8, ::8].reshape(12, -1) for f in sample
    ], axis=1).astype(np.float64)
    stats = {"mean": pixels.mean(axis=1).tolist(), "std": pixels.std(axis=1).tolist()}
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def normalise(image: np.ndarray, stats: dict, idx: list[int]) -> np.ndarray:
    mean = np.asarray(stats["mean"], dtype=np.float32)[idx, None, None]
    std = np.asarray(stats["std"], dtype=np.float32)[idx, None, None]
    return (image[idx].astype(np.float32) - mean) / std


class TileDataset(Dataset):
    def __init__(self, cfg: dict, files: list[str], experiment: str, crop: int | None = None, augment: bool = False):
        self.idx = band_indices(cfg, experiment)
        self.stats = band_stats(cfg)
        self.crop, self.augment = crop, augment
        self.files = files
        # Tiles are small enough to hold in memory (int16), which keeps CPU training fast.
        tile_dir = ROOT / cfg["tiles"]["out_dir"]
        loaded = [np.load(tile_dir / f) for f in files]
        self.images = [d["image"] for d in loaded]
        self.labels = [d["label"] for d in loaded]

    def __len__(self):
        return len(self.files)

    def __getitem__(self, i):
        img = normalise(self.images[i], self.stats, self.idx)
        lab = self.labels[i].astype(np.float32)
        if self.crop:
            size = lab.shape[0]
            y, x = np.random.randint(0, size - self.crop + 1, size=2)
            img, lab = img[:, y:y + self.crop, x:x + self.crop], lab[y:y + self.crop, x:x + self.crop]
        if self.augment:
            k = np.random.randint(4)
            img, lab = np.rot90(img, k, axes=(1, 2)), np.rot90(lab, k)
            if np.random.rand() < 0.5:
                img, lab = img[:, :, ::-1], lab[:, ::-1]
        return torch.from_numpy(img.copy()), torch.from_numpy(lab.copy())[None]
