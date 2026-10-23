"""Command line helpers (offline friendly):

  usg sample  --out DIR                      write the synthetic demo map (OSM + scene map + XODR)
  usg map     --osm FILE | --bbox S W N E --out DIR     build scene_map.json + map.xodr from OSM
  usg check   SCRIPT --map scene_map.json [--package OUT.usgscene.json] [--xosc OUT.xosc]
                                             run a scenario script in the sandbox and validate it
  usg types                                  list the 7 scenario archetypes
  usg adb-reverse [--port 7860]              let a USB-connected Quest open http://localhost:PORT (WebXR needs a secure origin)
  usg app     [--port 7860] [--host 127.0.0.1] [--no-browser] [--model NAME] [--backend auto|vulkan|cuda|cpu] [--ctx 12288] [--no-llm]
                                             start the Gradio interface (and your LM Studio model, unless --no-llm)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import osm, synth, xodr
from .mapmodel import MapModel
from .sandbox import run_script
from .scenario_types import ARCHETYPES, axes_label


def _write_map(model: MapModel, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "scene_map.json")
    xodr.export_xodr(model, out / "map.xodr")
    print(f"wrote {out / 'scene_map.json'} and {out / 'map.xodr'} "
          f"({len(model.roads)} roads, {len(model.junctions)} junctions, {len(model.crossings)} crossings)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="usg", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample")
    s.add_argument("--out", default="out")

    m = sub.add_parser("map")
    m.add_argument("--osm")
    m.add_argument("--bbox", nargs=4, type=float, metavar=("S", "W", "N", "E"))
    m.add_argument("--out", default="out")

    c = sub.add_parser("check")
    c.add_argument("script")
    c.add_argument("--map", required=True)
    c.add_argument("--package")
    c.add_argument("--xosc")

    sub.add_parser("types")

    ar = sub.add_parser("adb-reverse")
    ar.add_argument("--port", type=int, default=7860)

    g = sub.add_parser("app")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=7860)
    g.add_argument("--no-browser", action="store_true")
    g.add_argument("--model", help="LM Studio model: part of its name or a .gguf path (default: Qwen3.5-4B if present)")
    g.add_argument("--backend", default="auto", choices=["auto", "vulkan", "cuda", "cpu"])
    g.add_argument("--ctx", type=int, default=16384, help="context tokens (the specification pipeline needs a long prompt)")
    g.add_argument("--no-llm", action="store_true", help="do not start a local model")
    a = ap.parse_args(argv)

    if a.cmd == "sample":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "synthetic.osm").write_text(synth.synthetic_osm(), encoding="utf-8")
        _write_map(osm.build_map(synth.synthetic_osm()), out)
        return 0

    if a.cmd == "map":
        if a.osm:
            model = osm.build_map(a.osm)
        elif a.bbox:
            model = osm.build_map(osm.fetch_osm(*a.bbox), tuple(a.bbox))
        else:
            ap.error("give --osm FILE or --bbox S W N E")
        _write_map(model, Path(a.out))
        return 0

    if a.cmd == "check":
        code = Path(a.script).read_text(encoding="utf-8")
        res = run_script(code, a.map, "map.xodr")
        print(res.feedback())
        if res.ok and a.xosc:
            Path(a.xosc).write_text(res.xosc, encoding="utf-8")
        if res.ok and a.package:
            pkg = {"format": "usg-scenario-package/1", "name": res.spec["name"],
                   "map": json.loads(Path(a.map).read_text(encoding="utf-8")), "xosc": res.xosc,
                   "spec": res.spec, "script": code, "plan": None, "issues": res.issues}
            Path(a.package).write_text(json.dumps(pkg), encoding="utf-8")
            print(f"wrote {a.package}")
        return 0 if res.ok else 1

    if a.cmd == "app":
        from .app import main as run_app
        run_app(a.host, a.port, inbrowser=not a.no_browser, model=a.model, backend=a.backend, ctx=a.ctx, autostart=not a.no_llm)
        return 0

    if a.cmd == "adb-reverse":
        import shutil
        import subprocess
        adb = shutil.which("adb")
        if not adb:
            print("adb not found. Install Android platform-tools and put adb on PATH (Quest: enable developer mode, connect USB).")
            return 1
        r = subprocess.run([adb, "reverse", f"tcp:{a.port}", f"tcp:{a.port}"], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip() or f"ok: the headset can now open http://localhost:{a.port}/player/")
        return r.returncode

    if a.cmd == "types":
        for i, t in ARCHETYPES.items():
            print(f"{i:12s} {t['title']}\n{'':12s} {t['description']}\n{'':12s} axes: {axes_label(t['axes'])}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
