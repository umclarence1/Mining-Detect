"""Pixel metrics for binary segmentation and the Dice + BCE loss."""
import numpy as np
import torch
import torch.nn.functional as F


class Counts:
    """Accumulates true/false positives/negatives over many tiles."""

    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    def update(self, pred: np.ndarray, truth: np.ndarray):
        pred, truth = pred.astype(bool), truth.astype(bool)
        self.tp += int((pred & truth).sum())
        self.fp += int((pred & ~truth).sum())
        self.fn += int((~pred & truth).sum())
        self.tn += int((~pred & ~truth).sum())

    def summary(self) -> dict:
        tp, fp, fn = self.tp, self.fp, self.fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return {
            "iou": tp / (tp + fp + fn) if tp + fp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0,
            "precision": precision,
            "recall": recall,
        }


def dice_bce_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    bce = F.binary_cross_entropy_with_logits(logits, target)
    prob = torch.sigmoid(logits)
    inter = (prob * target).sum(dim=(1, 2, 3))
    dice = 1 - (2 * inter + 1) / (prob.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3)) + 1)
    return bce + dice.mean()
