"""Map areas of the Paris / Munich dataset: ``train/maps_city/<city>_<area>.osm``. Existing files are kept.

    python scripts/fetch_city_maps.py

The two ``center`` areas are copies of ``eval/maps``. Boxes are 0.008 x 0.012 degrees. Data: OpenStreetMap contributors (ODbL).
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm                                                 # noqa: E402

OUT = ROOT / "train" / "maps_city"
COPIES = {"paris_center": "paris_center.osm", "munich_center": "munich.osm"}
AREAS = {  # (south, west)
    "paris_marais": (48.8550, 2.3560), "paris_batignolles": (48.8830, 2.3160), "paris_montparnasse": (48.8390, 2.3220),
    "munich_maxvorstadt": (48.1480, 11.5680), "munich_haidhausen": (48.1280, 11.5920), "munich_schwabing": (48.1580, 11.5780),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, source in COPIES.items():
        if not (OUT / f"{name}.osm").exists():
            shutil.copy(ROOT / "eval" / "maps" / source, OUT / f"{name}.osm")
    failed = []
    for name, (s, w) in AREAS.items():
        dst = OUT / f"{name}.osm"
        if dst.exists():
            continue
        for attempt in range(3):
            try:
                cached = osm.fetch_osm(s, w, s + 0.008, w + 0.012, cache_dir=ROOT / ".usg_cache_v2")
                dst.write_bytes(cached.read_bytes())
                print(f"{name}: {dst.stat().st_size // 1024} kB on {time.strftime('%Y-%m-%d')}", flush=True)
                break
            except Exception as e:                                   # public server: retry, then report
                print(f"{name}: attempt {attempt + 1} failed: {e}", flush=True)
                time.sleep(30)
        else:
            failed.append(name)
        time.sleep(5)
    print("failed:", failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
