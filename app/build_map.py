"""Build the demo outputs:
  - outputs/maps/galamsey_map.html     interactive map (2020/2026 imagery, predictions, new mining, alerts)
  - outputs/maps/before_after.html     before/after slider of the Tarkwa block, mining in red

Run from the project folder (after analysis.alerts):
    python -m app.build_map
"""
import base64
import io
import json

import folium
import geopandas as gpd
import numpy as np
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

from analysis.rasters import PRED_DIR, read
from common.config import ROOT

MAPS = ROOT / "outputs" / "maps"
MAX_PX = 1400


def to_wgs84(array: np.ndarray, profile: dict, nearest: bool = False) -> tuple[np.ndarray, list]:
    """Reproject a mosaic to EPSG:4326 and return it with folium-style bounds [[S, W], [N, E]]."""
    bands = array if array.ndim == 3 else array[None]
    h, w = profile["height"], profile["width"]
    left, top = profile["transform"].c, profile["transform"].f
    right, bottom = left + w * profile["transform"].a, top + h * profile["transform"].e
    dst_t, dw, dh = calculate_default_transform(profile["crs"], "EPSG:4326", w, h, left, bottom, right, top)
    out = np.zeros((bands.shape[0], dh, dw), bands.dtype)
    reproject(bands, out, src_transform=profile["transform"], src_crs=profile["crs"], dst_transform=dst_t,
              dst_crs="EPSG:4326", resampling=Resampling.nearest if nearest else Resampling.bilinear)
    west, north = dst_t.c, dst_t.f
    east, south = west + dw * dst_t.a, north + dh * dst_t.e
    return (out if array.ndim == 3 else out[0]), [[south, west], [north, east]]


def shrink(img: Image.Image) -> Image.Image:
    scale = MAX_PX / max(img.size)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS) if scale < 1 else img


def rgb_image(rgb: np.ndarray) -> Image.Image:
    # Mild contrast stretch so the dark forest isn't murky.
    stretched = np.clip((rgb.astype(np.float32) / 255) ** 0.8 * 255 * 1.1, 0, 255).astype(np.uint8)
    return Image.fromarray(np.moveaxis(stretched, 0, -1))


def mask_image(mask: np.ndarray, colour: tuple) -> Image.Image:
    rgba = np.zeros((*mask.shape, 4), np.uint8)
    rgba[mask > 0] = (*colour, 170)
    return Image.fromarray(rgba)


def data_uri(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    return f"data:image/{fmt.lower()};base64,{base64.b64encode(buf.getvalue()).decode()}"


def overlay(img: Image.Image, mask: np.ndarray) -> Image.Image:
    base = img.convert("RGBA")
    return Image.alpha_composite(base, mask_image(mask, (255, 0, 0))).convert("RGB")


def build_slider(before: Image.Image, after: Image.Image, change: dict) -> None:
    b, a = data_uri(shrink(before), "JPEG"), data_uri(shrink(after), "JPEG")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tarkwa Before and After</title>
<style>
  :root {{ --bg:#111; --fg:#eee; --muted:#aaa; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font-family:system-ui,sans-serif; }}
  main {{ max-width:1000px; margin:0 auto; padding:16px; }}
  h1 {{ font-size:1.3rem; margin:0 0 4px; }}
  p {{ color:var(--muted); margin:0 0 12px; font-size:.95rem; }}
  .wrap {{ position:relative; width:100%; aspect-ratio:{before.width}/{before.height}; overflow:hidden; user-select:none; }}
  .wrap img {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }}
  #after {{ clip-path:inset(0 0 0 50%); }}
  #bar {{ position:absolute; top:0; bottom:0; left:50%; width:2px; background:#fff; pointer-events:none; }}
  .tag {{ position:absolute; top:8px; padding:2px 8px; background:rgba(0,0,0,.6); border-radius:4px; font-size:.85rem; }}
  input {{ width:100%; margin-top:8px; }}
</style></head><body><main>
<h1>Tarkwa, Ghana: dry season 2020 vs 2026</h1>
<p>Red = mining detected by the model. Mining area grew from {change['mining_2020_ha']:,.0f} ha to
{change['mining_2026_ha']:,.0f} ha; {change['new_mining_ha']:,.0f} ha newly disturbed (pixel count, provisional).</p>
<div class="wrap" id="wrap">
  <img src="{b}" alt="2020"><img id="after" src="{a}" alt="2026"><div id="bar"></div>
  <span class="tag" style="left:8px">2020</span><span class="tag" style="right:8px">2026</span>
</div>
<input type="range" id="s" min="0" max="100" value="50" aria-label="Before/after position">
<p>Imagery: Copernicus Sentinel-2 dry-season median composites.</p>
</main><script>
const s=document.getElementById('s'), a=document.getElementById('after'), bar=document.getElementById('bar'), w=document.getElementById('wrap');
function set(v){{ a.style.clipPath='inset(0 0 0 '+v+'%)'; bar.style.left=v+'%'; s.value=v; }}
s.addEventListener('input', e=>set(e.target.value));
w.addEventListener('pointermove', e=>{{ if(e.buttons){{ const r=w.getBoundingClientRect(); set(Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100))); }} }});
</script></body></html>"""
    (MAPS / "before_after.html").write_text(html, encoding="utf-8")


def main():
    change = json.loads((ROOT / "report" / "change.json").read_text(encoding="utf-8"))
    rgb0, prof = read("baseline_rgb")
    rgb1, _ = read("recent_rgb")
    m0, _ = read("baseline_mask")
    m1, _ = read("recent_mask")
    new = np.load(PRED_DIR / "new_mining.npy")

    build_slider(overlay(rgb_image(rgb0), m0), overlay(rgb_image(rgb1), m1), change)

    rgb0_w, bounds = to_wgs84(rgb0, prof)
    rgb1_w, _ = to_wgs84(rgb1, prof)
    m0_w, _ = to_wgs84(m0, prof, nearest=True)
    m1_w, _ = to_wgs84(m1, prof, nearest=True)
    new_w, _ = to_wgs84(new, prof, nearest=True)
    centre = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2]

    fmap = folium.Map(location=centre, zoom_start=12, tiles=None)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="High-res basemap (Esri)",
    ).add_to(fmap)
    layers = [
        ("Sentinel-2 2020", data_uri(shrink(rgb_image(rgb0_w)), "JPEG"), True),
        ("Sentinel-2 2026", data_uri(shrink(rgb_image(rgb1_w)), "JPEG"), False),
        ("Mining 2020 (model)", data_uri(shrink(mask_image(m0_w, (255, 200, 0)))), False),
        ("Mining 2026 (model)", data_uri(shrink(mask_image(m1_w, (255, 0, 0)))), False),
        ("New mining 2020-2026", data_uri(shrink(mask_image(new_w, (255, 0, 255)))), True),
    ]
    for name, uri, show in layers:
        folium.raster_layers.ImageOverlay(uri, bounds=bounds, name=name, show=show, interactive=False).add_to(fmap)

    alerts_path = MAPS / "alerts.geojson"
    if alerts_path.exists():
        alerts = gpd.read_file(alerts_path)
        top = alerts.head(50)
        group = folium.FeatureGroup(name="Top 50 alerts", show=True)
        for r in top.itertuples():
            popup = (f"<b>Alert #{r.rank}</b><br>{r.area_ha} ha new mining<br>{r.dist_to_stream_m} m from a stream"
                     f"<br>Protected area: {'yes' if r.in_protected_area else 'no'}"
                     f"<br>Likely industrial: {'yes' if r.likely_industrial else 'no'}<br>Confidence {r.confidence}"
                     f"<br>{r.lat}, {r.lon}")
            folium.CircleMarker([r.lat, r.lon], radius=4 + min(r.area_ha, 20) / 2, color="#ff00ff", fill=True,
                                fill_opacity=0.8, popup=folium.Popup(popup, max_width=250),
                                tooltip=f"#{r.rank}: {r.area_ha} ha").add_to(group)
        group.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.save(MAPS / "galamsey_map.html")
    print(f"Saved {MAPS / 'galamsey_map.html'}\nSaved {MAPS / 'before_after.html'}")


if __name__ == "__main__":
    main()
