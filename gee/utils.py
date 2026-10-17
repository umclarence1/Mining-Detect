"""Shared Earth Engine helpers: initialisation, regions and composites."""
import ee

from common.config import load_config


def init_ee(cfg: dict | None = None) -> dict:
    """Initialise Earth Engine with the project in config.yaml and return the config."""
    cfg = cfg or load_config()
    project = cfg["project"]["gee_project"]
    try:
        ee.Initialize(project=project)
    except Exception as e:
        raise SystemExit(
            f"Could not initialise Earth Engine for project '{project}'.\n"
            f"Run `earthengine authenticate` and try again.\nDetails: {e}"
        ) from e
    return cfg


def region_geometry(cfg: dict, name: str) -> ee.Geometry:
    """Rectangle for a named region in config.yaml (e.g. 'train', 'test_tarkwa')."""
    return ee.Geometry.Rectangle(cfg["regions"][name], proj="EPSG:4326", geodesic=False)


def clear_collection(cfg: dict, period: str, geom: ee.Geometry) -> ee.ImageCollection:
    """Sentinel-2 surface reflectance for a period, with cloudy pixels masked by Cloud Score+."""
    img_cfg = cfg["imagery"]
    p = cfg["periods"][period]
    # filterDate's end is exclusive, so advance a day to include the last date.
    end = ee.Date(p["end"]).advance(1, "day")
    band = img_cfg["cloud_score_band"]
    threshold = img_cfg["clear_threshold"]

    s2 = (
        ee.ImageCollection(img_cfg["collection"])
        .filterBounds(geom)
        .filterDate(p["start"], end)
        .linkCollection(ee.ImageCollection(img_cfg["cloud_score_collection"]), [band])
    )
    return s2.map(lambda img: img.updateMask(img.select(band).gte(threshold)))


def build_composite(cfg: dict, period: str, geom: ee.Geometry, clip: bool = True) -> ee.Image:
    """Median dry-season composite of all 12 bands, clipped to the region."""
    bands = cfg["imagery"]["bands_all"]
    composite = clear_collection(cfg, period, geom).select(bands).median()
    return composite.clip(geom) if clip else composite
