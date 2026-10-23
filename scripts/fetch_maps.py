"""Download the five evaluation areas from OpenStreetMap (Overpass) into ``eval/maps/<name>.osm``; existing files are kept.

    python scripts/fetch_maps.py            # all five
    python scripts/fetch_maps.py paris_center grenoble

Boxes are about 0.8 km2 (the size of the Sophia Antipolis area of the main experiment). Pin the download date in the paper: OSM changes.
Needs network access to overpass-api.de.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm                                                 # noqa: E402

# name: (south, west, north, east)
AREAS = {
    "sophia_antipolis": (43.61225, 7.06263, 43.62025, 7.07363),     # Sophia Antipolis / Biot (the main experiment, already cached)
    "paris_center": (48.8530, 2.3380, 48.8610, 2.3500),             # Ile de la Cite / Chatelet: dense crossings and signals
    "paris_saclay": (48.7090, 2.1650, 48.7170, 2.1770),             # Plateau de Saclay campus: wide roads, suburban
    "grenoble": (45.1860, 5.7215, 45.1940, 5.7335),                 # city centre: tram lines, bike lanes, pedestrian streets
    "munich": (48.1330, 11.5695, 48.1410, 11.5815),                 # old town around Marienplatz: narrow one-way streets, no signals
}


def main() -> int:
    wanted = sys.argv[1:] or list(AREAS)
    out = ROOT / "eval" / "maps"
    out.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        if name not in AREAS:
            print(f"unknown area {name}; choose from {', '.join(AREAS)}")
            return 2
        dst = out / f"{name}.osm"
        if dst.exists():
            print(f"{name}: already cached ({dst.stat().st_size // 1024} kB)")
            continue
        b = AREAS[name]
        print(f"{name}: {osm.bbox_area_km2(b):.2f} km2, downloading ...", flush=True)
        cached = osm.fetch_osm(*b, cache_dir=ROOT / ".usg_cache")
        dst.write_bytes(cached.read_bytes())
        print(f"{name}: wrote {dst} ({dst.stat().st_size // 1024} kB) on {time.strftime('%Y-%m-%d')}")
        time.sleep(2)                                              # be polite to the public Overpass instance
    return 0


if __name__ == "__main__":
    sys.exit(main())
