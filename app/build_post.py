"""Build the LinkedIn carousel: outputs/post/slide_1.png ... and carousel.pdf (1080 x 1350).

Run from the project folder, with the web app running (for its screenshots):
    python -m webapp.screenshot
    python -m app.build_post
"""
import json
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image

from analysis.rasters import read
from app.build_dashboard import alert_chips, outline, tint
from app.build_map import rgb_image
from common.config import ROOT, load_config
from gee.labels import maus_gdf
from webapp.screenshot import CHROME

OUT = ROOT / "outputs" / "post"
IMG = OUT / "img"
VERDICTS = {1: "New industrial works", 2: "Industrial pit expansion", 3: "Galamsey along a stream", 4: "Galamsey along a stream"}


def make_images(cfg: dict) -> list[dict]:
    IMG.mkdir(parents=True, exist_ok=True)
    rgb0_arr, profile = read("baseline_rgb")
    rgb1_arr, _ = read("recent_rgb")
    m0, _ = read("baseline_mask")
    m1, _ = read("recent_mask")
    rgb0, rgb1 = rgb_image(rgb0_arr), rgb_image(rgb1_arr)

    # Cover: the SAME area in both years, side by side. A split of one image would put
    # different places on each side (industrial mines west, galamsey east) and mislead.
    b, a = tint(rgb0, m0, alpha=0.55), tint(rgb1, m1, alpha=0.55)
    box = (1000, 900, 2040, 1940)  # ~10 km square east and south of town, where galamsey spread
    for name, img in (("cover_2020", b), ("cover_2026", a)):
        img.crop(box).resize((700, 700), Image.LANCZOS).save(IMG / f"{name}.jpg", quality=88)

    outline(tint(rgb1, m1, alpha=0.55), maus_gdf(cfg), profile).resize((1000, 1000), Image.LANCZOS).save(IMG / "maus.jpg", quality=88)

    alerts = gpd.read_file(ROOT / "outputs" / "maps" / "alerts.geojson")
    chips = alert_chips(alerts, rgb0, rgb1, profile, VERDICTS)
    for ch in chips:  # alert_chips returns data URIs; the slides use files
        import base64
        for k in ("before", "after"):
            (IMG / f"chip{ch['rank']}_{k}.jpg").write_bytes(base64.b64decode(ch[k].split(",", 1)[1]))
    shots = ROOT / "outputs" / "screenshots"
    for name in ("explore", "compare", "site_galamsey"):
        if (shots / f"{name}.png").exists():
            Image.open(shots / f"{name}.png").convert("RGB").save(IMG / f"app_{name}.jpg", quality=90)
    if (shots / "site_galamsey.png").exists():  # close-up: map and site detail panel
        Image.open(shots / "site_galamsey.png").convert("RGB").crop((560, 230, 1600, 470)).save(IMG / "app_detail.jpg", quality=90)
    return chips


def slides_html(data: dict, chips: list[dict]) -> str:
    c = data["change"]
    o = c["olofsson"]
    growth = round((c["mining_2026_ha"] / c["mining_2020_ha"] - 1) * 100)
    near = round(100 * data["alerts_near_river"] / data["alerts_total"])
    chip_html = "".join(
        f'<div class="chip"><div class="pair"><img src="img/chip{ch["rank"]}_before.jpg" alt=""><img src="img/chip{ch["rank"]}_after.jpg" alt=""></div>'
        f'<div class="cap"><b>#{ch["rank"]} · {ch["area_ha"]:.0f} ha</b><span class="{"gal" if "alamsey" in ch["verdict"] else "ind"}">{ch["verdict"]}</span></div></div>'
        for ch in chips)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{ --bg:#0d1310; --panel:#141c18; --line:#28342e; --fg:#e5ebe6; --muted:#93a299; --accent:#e8914a; --mine:#ef4444; --old:#ffc400; --cyan:#50dcff;
  --display:"Barlow Condensed","Arial Narrow",sans-serif; --body:"IBM Plex Sans","Segoe UI",sans-serif; --mono:"IBM Plex Mono",Consolas,monospace; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; background:var(--bg); color:var(--fg); font-family:var(--body); }}
.slide {{ width:1080px; height:1350px; padding:72px 72px 64px; display:none; flex-direction:column; gap:36px; position:relative; overflow:hidden; }}
.slide:target {{ display:flex; }}
.top {{ display:flex; justify-content:space-between; font:500 20px var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }}
.top b {{ color:var(--accent); font-weight:500; }}
h1 {{ font:700 112px/0.92 var(--display); text-transform:uppercase; margin:0; letter-spacing:.005em; }}
h1 span {{ color:var(--accent); }}
h2 {{ font:600 76px/1 var(--display); margin:0; text-wrap:balance; }}
h2 em {{ font-style:normal; color:var(--accent); }}
p.lead {{ font-size:32px; line-height:1.4; margin:0; color:var(--fg); max-width:30ch; }}
p.sub {{ font-size:26px; line-height:1.45; margin:0; color:var(--muted); }}
.foot {{ margin-top:auto; display:flex; justify-content:space-between; align-items:center; font:500 20px var(--mono); color:var(--muted); letter-spacing:.06em; }}
.swipe {{ color:var(--accent); }}
.frame {{ position:relative; border-radius:6px; overflow:hidden; }}
.frame img {{ display:block; width:100%; }}
.frame .tag {{ position:absolute; top:16px; font:500 22px var(--mono); letter-spacing:.1em; background:rgba(13,19,16,.82); padding:4px 12px; border-radius:4px; }}
.tag.l {{ left:16px; }} .tag.r {{ right:16px; }}
.duo {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.stat {{ margin:0; font:500 40px/1.2 var(--display); color:var(--muted); }}
.stat b {{ color:var(--fg); font-weight:600; }} .stat em {{ font-style:normal; color:var(--accent); font-weight:600; margin-left:10px; }}
#s1 h1 {{ font-size:124px; }}
#s1 p.lead {{ font-size:36px; }}
.legend {{ display:flex; gap:28px; font-size:22px; color:var(--muted); }}
.legend i {{ display:inline-block; width:18px; height:18px; border-radius:4px; vertical-align:-2px; margin-right:8px; }}
.kpis {{ display:grid; grid-template-columns:1fr 1fr; border-top:3px solid var(--fg); }}
.kpi {{ padding:32px 0 32px; border-bottom:1px solid var(--line); display:grid; gap:8px; }}
.kpi:nth-child(odd) {{ padding-right:32px; }} .kpi:nth-child(even) {{ padding-left:32px; border-left:1px solid var(--line); }}
.kpi .v {{ font:600 104px/1 var(--display); font-variant-numeric:tabular-nums; }}
.kpi .v small {{ font:500 34px var(--body); color:var(--muted); }}
.kpi .v.a {{ color:var(--accent); }}
.kpi .l {{ font-size:26px; color:var(--muted); }}
.chips {{ display:grid; grid-template-columns:1fr 1fr; gap:28px 28px; }}
.chip {{ display:grid; gap:10px; }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:3px; border-radius:4px; overflow:hidden; }}
.pair img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; }}
.cap {{ display:flex; justify-content:space-between; font-size:22px; gap:8px; }}
.cap .gal {{ color:var(--mine); font-weight:500; }} .cap .ind {{ color:var(--muted); }}
.app img {{ width:100%; display:block; border-radius:8px; border:1px solid var(--line); }}
#s3 {{ gap:28px; }}
.stack {{ display:grid; gap:0; border-top:3px solid var(--fg); }}
.stack div {{ display:grid; grid-template-columns:200px 1fr; gap:24px; padding:22px 0; border-bottom:1px solid var(--line); font-size:26px; line-height:1.4; }}
.stack b {{ font:500 20px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--accent); padding-top:6px; }}
.note {{ font-size:22px; color:var(--muted); line-height:1.45; }}
</style></head><body>

<section class="slide" id="s1">
  <div class="top"><span><b>Demo Wednesday</b></span><span>Tarkwa, Ghana</span></div>
  <h1>Galamsey<br><span>Detector</span></h1>
  <p class="lead">Can free satellite images catch illegal gold mining before the rivers turn brown?</p>
  <div class="duo">
    <div class="frame"><img src="img/cover_2020.jpg" alt=""><span class="tag l">2020</span></div>
    <div class="frame"><img src="img/cover_2026.jpg" alt=""><span class="tag l">2026</span></div>
  </div>
  <p class="stat">Mining around Tarkwa: {c['mining_2020_ha']:,.0f} ha → <b>{c['mining_2026_ha']:,.0f} ha</b> <em>+{growth}%</em></p>
  <div class="foot"><span>Same 10 km area · red = mining found by the AI</span><span>Sentinel-2</span></div>
</section>

<section class="slide" id="s2">
  <div class="top"><span><b>What I found</b></span><span>Tarkwa, Ghana</span></div>
  <h2>Around Tarkwa, mining grew by <em>{growth}%</em> in six years</h2>
  <div class="kpis">
    <div class="kpi"><div class="v">{c['mining_2020_ha']:,.0f} <small>ha</small></div><div class="l">mining in the 2020 dry season</div></div>
    <div class="kpi"><div class="v a">{c['mining_2026_ha']:,.0f} <small>ha</small></div><div class="l">mining in the 2026 dry season</div></div>
    <div class="kpi"><div class="v">{o['adjusted_new_ha']:,.0f} <small>± {o['ci95_ha']:,.0f}</small></div><div class="l">hectares newly dug up (error-adjusted)</div></div>
    <div class="kpi"><div class="v">{near}%</div><div class="l">of new sites within 500 m of a stream</div></div>
  </div>
  <p class="sub">{data['alerts_protected']} new sites sit inside forest reserves. Study area: 420 km² around Tarkwa, Western Region.</p>
  <div class="foot"><span>Sentinel-2 · 10 m · Nov–Feb composites</span></div>
</section>

<section class="slide" id="s3">
  <div class="top"><span><b>The app</b></span><span>Tarkwa, Ghana</span></div>
  <h2>A monitoring console, not a one-off map</h2>
  <div class="app"><img src="img/app_explore.jpg" alt=""></div>
  <div class="app"><img src="img/app_detail.jpg" alt=""></div>
  <p class="sub">Swipe between years, filter alerts by size, stream and forest reserve, and click a site to see it before and after.</p>
</section>

<section class="slide" id="s4">
  <div class="top"><span><b>Hardest part</b></span><span>Tarkwa, Ghana</span></div>
  <h2>The world's mine maps <em>miss galamsey</em></h2>
  <div class="frame"><img src="img/maus.jpg" alt=""></div>
  <div class="legend"><span><i style="border:3px solid var(--cyan)"></i>Global mining dataset</span><span><i style="background:var(--mine)"></i>What my model finds</span></div>
  <p class="sub">The best free dataset outlines the big industrial pits and almost none of the scars along streams. So I built my own labels.</p>
</section>

<section class="slide" id="s5">
  <div class="top"><span><b>Favourite bug</b></span><span>Tarkwa, Ghana</span></div>
  <h2>My #1 "illegal mining" alert was a <em>big industrial</em> mine</h2>
  <div class="chips">{chip_html}</div>
  <p class="sub">Two of the top four are real galamsey. Two are new works at industrial mines too recent for the 2019 outlines. A detector sees mining, not legality.</p>
</section>

<section class="slide" id="s6">
  <div class="top"><span><b>Under the hood</b></span><span>Tarkwa, Ghana</span></div>
  <h2>How it's built</h2>
  <div class="stack">
    <div><b>Data</b><span>Sentinel-2, 12 bands, cloud-masked with Cloud Score+ in Google Earth Engine</span></div>
    <div><b>Labels</b><span>Global mine polygons + a stream-side bare-soil rule, 1,028 tiles</span></div>
    <div><b>Model</b><span>PyTorch U-Net (ResNet-18), trained on a laptop CPU. 12 bands beat RGB: IoU 0.76 vs 0.71</span></div>
    <div><b>Check</b><span>180 random points, blind, area error-adjusted (Olofsson 2014). 88% agreement</span></div>
    <div><b>App</b><span>FastAPI + Leaflet, alerts API with filters, CSV export</span></div>
  </div>
  <p class="note">Limits: labels are rule-based, the check points were read from 10 m imagery by an AI assistant without field visits, and the area range is wide. Next: field checks, licence boundaries, monthly runs.</p>
  <div class="foot"><span>Code in the comments</span><span class="swipe">#DemoWednesday</span></div>
</section>
</body></html>"""


def render(n: int) -> list[Path]:
    browser = next(p for p in CHROME if p.exists())
    url = (OUT / "slides.html").resolve().as_uri()
    paths = []
    for i in range(1, n + 1):
        out = OUT / f"slide_{i}.png"
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}",
                            "--allow-file-access-from-files", "--window-size=1080,1350", "--virtual-time-budget=8000",
                            f"--screenshot={out}", f"{url}#s{i}"], capture_output=True, timeout=120)
        paths.append(out)
        print(f"Saved {out}")
    return paths


def main():
    cfg = load_config()
    chips = make_images(cfg)
    change = json.loads((ROOT / "report" / "change.json").read_text(encoding="utf-8"))
    alerts = gpd.read_file(ROOT / "outputs" / "maps" / "alerts.geojson")
    data = {"change": change, "alerts_total": len(alerts), "alerts_near_river": int(alerts.near_river.sum()),
            "alerts_protected": int(alerts.in_protected_area.sum())}
    (OUT / "slides.html").write_text(slides_html(data, chips), encoding="utf-8")
    paths = render(6)
    imgs = [Image.open(p).convert("RGB") for p in paths]
    imgs[0].save(OUT / "carousel.pdf", save_all=True, append_images=imgs[1:], resolution=144)
    print(f"Saved {OUT / 'carousel.pdf'}")


if __name__ == "__main__":
    main()
