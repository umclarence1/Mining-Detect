"""Screenshot views of the running web app with headless Chrome (for the write-up and posts).

Start the server first (python -m webapp.server), then:
    python -m webapp.screenshot
Writes PNGs to outputs/screenshots/.
"""
import subprocess
import tempfile
from pathlib import Path

from common.config import ROOT

CHROME = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
          Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]
VIEWS = {
    "explore": "",
    "compare": "compare",
    "site_galamsey": "site-3",
    "density": "grid,footprint",
}


def main(base: str = "http://127.0.0.1:8050/", size: str = "1600,1000"):
    browser = next(p for p in CHROME if p.exists())
    out = ROOT / "outputs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    for name, hash_ in VIEWS.items():
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}",
                            f"--window-size={size}", "--virtual-time-budget=15000", f"--screenshot={out / (name + '.png')}",
                            base + ("#" + hash_ if hash_ else "")], capture_output=True, timeout=120)
        print(f"Saved {out / (name + '.png')}")


if __name__ == "__main__":
    main()
