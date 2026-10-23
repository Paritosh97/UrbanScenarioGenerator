"""Write the evaluation prompts for one map: the Sophia Antipolis set (``eval/prompts_sophia.json``) filtered by what the map contains.

    python scripts/make_prompts.py paris_center            # reads eval/maps/paris_center.osm, writes eval/prompts_paris_center.json

A prompt is kept only if every object type it asks for exists on the map (a bus stop, a bench, a waste basket, a tree, a zebra or a
signalised crossing), so a failure is never "the map has no bench". The prompts themselves are identical across maps, which keeps the
benchmark comparable; the report lists what was dropped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import osm                                                 # noqa: E402

# what each template prompt (suffix of its Sophia id) needs on the map
NEEDS = {
    "ptp_env_1": {"bus_stop"}, "ptp_env_2": {"bench"}, "ptp_env_3": {"waste_basket"},
    "ptp_road_1": {"crossing"}, "ptp_road_2": {"crossing"}, "ptp_road_3": {"crossing"},
    "cpath_1": {"crossing"}, "cpath_2": {"crossing"}, "cpath_3": {"crossing"},
    "env_con_1": {"zebra"}, "env_con_2": {"crossing"}, "env_con_3": {"bus_stop"},
    "dyn_nav_1": {"zebra"}, "dyn_nav_2": {"crossing"}, "dyn_nav_3": {"crossing"},
    "dep_comp_1": {"crossing"}, "dep_comp_2": {"bus_stop", "bench", "waste_basket"}, "dep_comp_3": {"crossing", "waste_basket"},
    "indep_comp_1": {"waste_basket", "bench"}, "indep_comp_2": {"bench", "bus_stop"}, "indep_comp_3": {"bench", "tree"},
    "mixed_1": {"signals"}, "mixed_2": {"signals"}, "mixed_3": {"crossing"}, "mixed_4": {"signals"},
}


def inventory(model) -> dict[str, int]:
    props = {}
    for p in model.props:
        props[p.ptype] = props.get(p.ptype, 0) + 1
    ctl = {}
    for c in model.crossings:
        ctl[c.control] = ctl.get(c.control, 0) + 1
    return {"bus_stop": props.get("bus_stop", 0), "bench": props.get("bench", 0), "waste_basket": props.get("waste_basket", 0),
            "tree": props.get("tree", 0), "crossing": len(model.crossings), "zebra": ctl.get("zebra", 0), "signals": ctl.get("signals", 0)}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    src = ROOT / "eval" / "maps" / f"{name}.osm"
    if not src.exists():
        print(f"{src} is missing: run scripts/fetch_maps.py {name} first (needs network access)")
        return 1
    inv = inventory(osm.build_map(src))
    tmpl = json.loads((ROOT / "eval" / "prompts_sophia.json").read_text(encoding="utf-8"))
    kept, dropped = [], []
    for p in tmpl["prompts"]:
        suffix = p["id"].split("_", 1)[1]
        missing = sorted(k for k in NEEDS[suffix] if inv[k] == 0)
        if missing:
            dropped.append((p["id"].replace("sa_", f"{name}_", 1), missing))
            continue
        q = dict(p)
        q["id"], q["map"] = f"{name}_{suffix}", name
        kept.append(q)
    desc = (f"Evaluation prompts on the real map '{name}' (OSM extract eval/maps/{name}.osm). The template is eval/prompts_sophia.json; "
            f"prompts whose objects are missing on this map were dropped (see 'dropped'). Inventory: {inv}.")
    out = ROOT / "eval" / f"prompts_{name}.json"
    out.write_text(json.dumps({"description": desc, "inventory": inv, "dropped": dropped, "prompts": kept}, indent=1), encoding="utf-8")
    print(f"{name}: inventory {inv}\nkept {len(kept)} of {len(tmpl['prompts'])} prompts -> {out}")
    for pid, miss in dropped:
        print(f"  dropped {pid}: no {', '.join(miss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
