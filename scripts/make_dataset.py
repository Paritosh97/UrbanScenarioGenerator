"""Build the scenario dataset (see ``usg.dataset``) from the cached maps.

    python scripts/make_dataset.py --out dataset --variants 4 --test-maps munich grenoble
    python scripts/make_dataset.py --out dataset --runs ../paper/results/benchmark.jsonl      # also add accepted LLM runs

Maps are the five real areas of ``scripts/fetch_maps.py`` (those that exist in ``eval/maps``) plus the synthetic city.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm, synth                                        # noqa: E402
from usg.dataset import build_dataset, load_maps                  # noqa: E402


def available_maps(include_synthetic: bool = True) -> dict:
    paths = {p.stem: p for p in sorted((ROOT / "eval" / "maps").glob("*.osm"))}
    maps = load_maps(paths)
    if include_synthetic:
        maps["synthetic"] = osm.build_map(synth.synthetic_osm())
    return maps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dataset"))
    ap.add_argument("--variants", type=int, default=4, help="variants per reference script and map (crossing / landmark choice)")
    ap.add_argument("--test-maps", nargs="*", default=[], help="maps forming the held-out test split")
    ap.add_argument("--runs", help="benchmark JSONL written with --save-specs: add its accepted LLM scenarios")
    ap.add_argument("--no-synthetic", action="store_true")
    a = ap.parse_args()
    maps = available_maps(not a.no_synthetic)
    print("maps:", ", ".join(maps))
    rows = build_dataset(a.out, maps, variants=a.variants, test_maps=tuple(a.test_maps), runs=a.runs)
    print(f"wrote {len(rows)} scenarios to {a.out} (see STATS.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
