import numpy as np
import pytest
import torch

from model.metrics import Counts, dice_bce_loss


def test_counts_perfect_prediction():
    truth = np.array([[1, 0], [1, 1]])
    c = Counts()
    c.update(truth, truth)
    s = c.summary()
    assert s["iou"] == pytest.approx(1.0)
    assert s["f1"] == pytest.approx(1.0)


def test_counts_known_values():
    pred = np.array([1, 1, 0, 0])
    truth = np.array([1, 0, 1, 0])
    c = Counts()
    c.update(pred, truth)
    s = c.summary()  # tp=1, fp=1, fn=1
    assert s["iou"] == pytest.approx(1 / 3)
    assert s["f1"] == pytest.approx(0.5)
    assert s["precision"] == pytest.approx(0.5)
    assert s["recall"] == pytest.approx(0.5)


def test_counts_accumulates_across_tiles():
    c = Counts()
    c.update(np.array([1, 0]), np.array([1, 0]))
    c.update(np.array([0, 1]), np.array([1, 1]))
    assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 1, 1)


def test_dice_bce_lower_for_better_logits():
    target = torch.zeros(2, 1, 8, 8)
    target[:, :, :4] = 1
    good = (target * 2 - 1) * 6
    bad = -good
    assert dice_bce_loss(good, target) < dice_bce_loss(bad, target)
