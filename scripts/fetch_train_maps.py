"""Download the training and validation areas (disjoint from the evaluation areas) into ``train/maps_v2/<split>/<name>.osm`` (``train/maps`` holds the first download, used by the pilot).

    python scripts/fetch_train_maps.py

``val`` areas are never used for training. The evaluation areas (``eval/maps``: Paris centre, Munich; also Sophia Antipolis) are excluded
on purpose. Existing files are kept. Data: OpenStreetMap contributors (ODbL). Pin the download date in the paper.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm                                                 # noqa: E402

# name: (south, west) ; every box is 0.008 x 0.012 degrees, about the size of the evaluation areas
AREAS = {
    "val": {"grenoble": (45.1860, 5.7215), "berlin_mitte": (52.5170, 13.3830), "lyon_presquile": (45.7580, 4.8290)},
    "train": {
        "toulouse": (43.6000, 1.4380), "nantes": (47.2130, -1.5620), "lille": (50.6330, 3.0560), "strasbourg": (48.5790, 7.7430),
        "bordeaux": (44.8380, -0.5800), "hamburg": (53.5490, 9.9880), "cologne": (50.9340, 6.9520), "vienna": (48.2040, 16.3630),
        "turin": (45.0660, 7.6780), "amsterdam": (52.3660, 4.8880), "brussels": (50.8450, 4.3500), "barcelona": (41.3880, 2.1590),
        "london_soho": (51.5100, -0.1380), "zurich": (47.3720, 8.5360), "paris_saclay": (48.7090, 2.1650),
    },
}


def main() -> int:
    """Default: the 2026-11-27 query (with building relations) into ``train/maps_v2`` for the areas that exist in ``train/maps``."""
    failed = []
    for split, areas in AREAS.items():
        out = ROOT / "train" / "maps_v2" / split
        out.mkdir(parents=True, exist_ok=True)
        for name, (s, w) in areas.items():
            dst = out / f"{name}.osm"
            if dst.exists() or not (ROOT / "train" / "maps" / split / f"{name}.osm").exists():
                continue
            try:
                cached = osm.fetch_osm(s, w, s + 0.008, w + 0.012, cache_dir=ROOT / ".usg_cache_v2")
                dst.write_bytes(cached.read_bytes())
                print(f"{split}/{name}: {dst.stat().st_size // 1024} kB on {time.strftime('%Y-%m-%d')}", flush=True)
            except Exception as e:                                   # keep going; report at the end
                failed.append(name)
                print(f"{split}/{name}: FAILED {e}", flush=True)
            time.sleep(5)                                            # be polite to the public Overpass instance
    print("failed:", failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
