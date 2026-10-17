"""Helpers for reading prediction mosaics and burning vector layers onto their grid."""
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

from common.config import ROOT

PRED_DIR = ROOT / "outputs" / "predictions"


def read(name: str) -> tuple[np.ndarray, dict]:
    with rasterio.open(PRED_DIR / f"{name}.tif") as src:
        return src.read(1) if src.count == 1 else src.read(), src.profile


def burn(gdf: gpd.GeoDataFrame, profile: dict) -> np.ndarray:
    """1 where any polygon covers a pixel of the mosaic grid."""
    shape = (profile["height"], profile["width"])
    if gdf is None or gdf.empty:
        return np.zeros(shape, np.uint8)
    geoms = gdf.to_crs(profile["crs"]).geometry
    return rasterize(((g, 1) for g in geoms), out_shape=shape, transform=profile["transform"], dtype="uint8")


def remove_small(mask: np.ndarray, min_px: int) -> np.ndarray:
    from scipy import ndimage

    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[lab].astype(np.uint8)
