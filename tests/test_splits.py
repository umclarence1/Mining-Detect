import pandas as pd

from common.config import load_config
from gee import export_tiles


def test_spatial_split_never_shares_a_block(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["splits"]["out_dir"] = str(tmp_path)
    monkeypatch.setattr(export_tiles, "ROOT", tmp_path.parent)
    step = 2560
    rows = [{"file": f"trainval/baseline_{i}_{j}.npz", "x0": 500000 + i * step, "y0": 600000 + j * step, "set": "trainval"}
            for i in range(12) for j in range(12)]
    rows += [{"file": "test/baseline_t.npz", "x0": 0, "y0": 0, "set": "test"}]
    export_tiles.make_splits(cfg, pd.DataFrame(rows))

    def blocks(name):
        files = (tmp_path / f"{name}.txt").read_text().split()
        tiles = pd.DataFrame(rows).set_index("file").loc[files]
        block = cfg["splits"]["block_km"] * 1000
        return {(int(x // block), int(y // block)) for x, y in zip(tiles.x0, tiles.y0)}

    train, val = blocks("train"), blocks("val")
    assert train and val
    assert not train & val
    assert (tmp_path / "test.txt").read_text().split() == ["test/baseline_t.npz"]


def test_tile_grid_marks_tarkwa_test_tiles():
    grid = export_tiles.tile_grid(load_config())
    assert grid.is_test.sum() == 64
    # Every test tile is also inside the no-training buffer.
    assert grid[grid.is_test].near_test.all()
