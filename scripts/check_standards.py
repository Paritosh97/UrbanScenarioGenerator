"""Check the generated files with an independent consumer of the standards: esmini (OpenSCENARIO player + OpenDRIVE road manager).

For every scenario of a dataset (``scripts/make_dataset.py``) or, without ``--dataset``, for the 7 reference scripts on the synthetic city:

* **OpenSCENARIO**: ``esmini --headless --osc`` must load the file (version 1.3), run it to the end with exit code 0 and log no error. The
  ``<VRTask>``/``<Spec>`` extension travels inside ``CustomCommandAction``, which a standard player has to ignore without failing.
* **OpenDRIVE**: the road manager of esmini (``libesminiRMLib``) must load ``map.xodr``, find as many roads as the export wrote, and agree with our
  map frame: points on our road centre lines are projected onto esmini's road geometry and the lateral offset must be small.

    python scripts/check_standards.py --esmini /path/to/esmini/bin [--dataset dataset] --out ../paper/results/standards_check.md

esmini is not a dependency of the package: download a release from https://github.com/esmini/esmini/releases and point ``--esmini`` (or the
``ESMINI_BIN`` environment variable) to its ``bin`` folder. No XSD validation is done here (the ASAM schemas are licensed separately).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg import geo, osm, synth, xodr                              # noqa: E402
from usg.dataset import scenario_xodr                              # noqa: E402
from usg.mapmodel import MapModel                                  # noqa: E402
from usg.sandbox import run_script                                 # noqa: E402
from usg.scenario_types import ARCHETYPES                          # noqa: E402


class PosData(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double), ("h", ctypes.c_double),
                ("p", ctypes.c_double), ("r", ctypes.c_double), ("hRelative", ctypes.c_double), ("roadId", ctypes.c_uint32),
                ("junctionId", ctypes.c_uint32), ("laneId", ctypes.c_int), ("laneOffset", ctypes.c_double), ("s", ctypes.c_double)]


class _quiet:
    """Silence the C library's own log lines on stdout while it runs."""
    def __enter__(self):
        sys.stdout.flush()
        self.fd, self.null = os.dup(1), os.open(os.devnull, os.O_WRONLY)
        os.dup2(self.null, 1)

    def __exit__(self, *a):
        os.dup2(self.fd, 1)
        os.close(self.fd)
        os.close(self.null)


def find_esmini(arg: str | None) -> Path:
    for cand in (arg, os.environ.get("ESMINI_BIN"), shutil.which("esmini")):
        if cand:
            p = Path(cand)
            p = p / "esmini" if p.is_dir() else p
            if p.exists():
                return p
    raise SystemExit("esmini not found: pass --esmini <bin folder> or set ESMINI_BIN")


def run_osc(esmini: Path, xosc: str, odr: Path, timeout: float = 180.0) -> dict:
    """Run one scenario headless; returns exit code, error / warning lines and whether esmini reported the file version."""
    with tempfile.TemporaryDirectory(prefix="usg_esmini_") as tmp:
        tmp = Path(tmp)
        (tmp / "s.xosc").write_text(xosc, encoding="utf-8")
        shutil.copy(odr, tmp / "map.xodr")
        try:
            p = subprocess.run([str(esmini), "--headless", "--osc", "s.xosc", "--fixed_timestep", "0.1", "--logfile_path", "log.txt"],
                               cwd=tmp, capture_output=True, text=True, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            return {"rc": None, "errors": ["timeout"], "warnings": [], "loaded": False}
        log = (tmp / "log.txt").read_text(encoding="utf-8", errors="replace") if (tmp / "log.txt").exists() else ""
    lines = log.splitlines()
    errors = [ln for ln in lines if "[error]" in ln]
    warns = [ln for ln in lines if "[warn]" in ln and "Traffic sign mapping" not in ln and "Traffic light type" not in ln]
    return {"rc": rc, "errors": errors, "warnings": warns, "loaded": any("Loading s.xosc (v1.3)" in ln for ln in lines)}


def check_opendrive(lib: Path, odr: Path, model: MapModel, samples_per_road: int = 6) -> dict:
    """Load the road network with esmini's road manager and compare it with our centre lines."""
    rm = ctypes.CDLL(str(lib))
    rm.RM_Init.argtypes = [ctypes.c_char_p]
    rm.RM_GetNumberOfRoads.restype = ctypes.c_int
    rm.RM_CreatePosition.restype = ctypes.c_int
    for fn in (rm.RM_SetWorldXYHPosition,):
        fn.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    rm.RM_SetRoadPosition.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_double, ctypes.c_double, ctypes.c_bool]
    rm.RM_GetPositionData.argtypes = [ctypes.c_int, ctypes.POINTER(PosData)]
    rm.RM_GetRoadLength.argtypes = [ctypes.c_uint32]
    rm.RM_GetRoadLength.restype = ctypes.c_double
    with _quiet():
        rc = rm.RM_Init(str(odr).encode())
    if rc != 0:
        return {"loaded": False}
    import xml.etree.ElementTree as ET
    out = {"loaded": True, "roads": rm.RM_GetNumberOfRoads(), "roads_in_file": len(ET.parse(odr).getroot().findall("road"))}
    h, d = rm.RM_CreatePosition(), PosData()
    offs, outliers = [], []
    for r in model.roads:
        if len(r.pts) < 2:
            continue
        length = geo.polyline_length(r.pts)
        lo, hi = r.trim_start + 1.0, length - r.trim_end - 1.0
        if hi <= lo:
            continue
        for k in range(samples_per_road):
            s_ref = lo + (hi - lo) * (k + 0.5) / samples_per_road
            (x, y), _ = geo.point_at(r.pts, s_ref)
            with _quiet():
                rm.RM_SetWorldXYHPosition(h, x, y, 0.0)
                rm.RM_GetPositionData(h, ctypes.byref(d))
                rm.RM_SetRoadPosition(h, d.roadId, d.s, 0.0, False)
                e = PosData()
                rm.RM_GetPositionData(h, ctypes.byref(e))
            offs.append(math.hypot(e.x - x, e.y - y))                 # lateral distance to the reference line esmini picked
            if offs[-1] > 0.5:
                outliers.append(round(hi - lo + 2.0, 1))               # length of our trimmed road: are the outliers on tiny stubs?
    out["samples"] = len(offs)
    out["over_half_metre"] = len(outliers)
    out["outlier_road_lengths_m"] = sorted(outliers)[:8]
    out["max_offset_m"] = round(max(offs), 3) if offs else None
    out["mean_offset_m"] = round(sum(offs) / len(offs), 3) if offs else None
    with _quiet():
        rm.RM_Close()
    return out


def reference_items(tmp: Path):
    model = osm.build_map(synth.synthetic_osm())
    mp = tmp / "scene_map.json"
    model.save(mp)
    odr = tmp / "map.xodr"
    xodr.export_xodr(model, odr)
    for sid, a in sorted(ARCHETYPES.items()):
        r = run_script(a["template"], mp)
        if r.ok:
            own = tmp / f"{sid}.xodr"
            yield f"synthetic__{sid}", r.xosc, own if scenario_xodr(model, r.spec, own) else odr, model


def dataset_items(root: Path):
    maps = {}
    for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        xosc = root / "scenarios" / f"{row['id']}.xosc"
        if not xosc.exists():
            continue
        maps.setdefault(row["map"], MapModel.load(root / "maps" / row["map"] / "scene_map.json"))
        own = root / "scenarios" / f"{row['id']}.xodr"                   # present when the scenario adds signals of its own
        yield row["id"], xosc.read_text(encoding="utf-8"), own if own.exists() else root / "maps" / row["map"] / "map.xodr", maps[row["map"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esmini", help="esmini bin folder (or the esmini executable)")
    ap.add_argument("--rmlib", help="libesminiRMLib.so for the OpenDRIVE road-manager check (default: next to the esmini executable)")
    ap.add_argument("--dataset", help="dataset folder from make_dataset.py; default: the 7 reference scripts on the synthetic city")
    ap.add_argument("--out", default=str(ROOT.parent / "paper" / "results" / "standards_check.md"))
    a = ap.parse_args()
    esmini = find_esmini(a.esmini)
    rmlib = Path(a.rmlib) if a.rmlib else esmini.parent / "libesminiRMLib.so"
    version = next((ln for ln in subprocess.run([str(esmini), "--version"], capture_output=True, text=True).stdout.splitlines() if "TAG" in ln or "esmini" in ln), "esmini")

    tmp = Path(tempfile.mkdtemp(prefix="usg_std_"))
    items = list(dataset_items(Path(a.dataset))) if a.dataset else list(reference_items(tmp))
    rows, odr_rows = [], {}
    for name, xosc, odr, model in items:
        res = run_osc(esmini, xosc, odr)
        rows.append((name, res))
        key = str(odr)
        if rmlib.exists() and key not in odr_rows:
            odr_rows[key] = (name.split("__")[0], check_opendrive(rmlib, odr, model))
        print(f"{name:42s} rc={res['rc']} loaded={res['loaded']} errors={len(res['errors'])} warnings={len(res['warnings'])}", flush=True)

    ok = [r for _, r in rows if r["rc"] == 0 and r["loaded"] and not r["errors"]]
    all_odr_ok = all(o.get("loaded") and o.get("roads") == o.get("roads_in_file") for _, o in odr_rows.values())
    lines = ["# Standards check with esmini", "", f"{version}. Scenarios checked: {len(rows)}.", "",
             f"* **OpenSCENARIO 1.3 + `<VRTask>`/`<Spec>` extension:** {len(ok)}/{len(rows)} load, run to the end (exit code 0) and log no error "
             f"in `esmini --headless`. Warnings other than unsupported traffic-light types: "
             f"{sum(len(r['warnings']) for _, r in rows)} in total.", ""]
    from collections import Counter
    import re
    kinds = Counter(re.sub(r"[0-9.]+", "N", w.split("] ", 1)[-1])[:110] for _, r in rows for w in r["warnings"])
    for text, n in kinds.most_common(3):
        lines.append(f"  * {n} x `{text}`")
    bad = [(n, r) for n, r in rows if r not in ok]
    for n, r in bad[:10]:
        lines.append(f"  * `{n}`: rc={r['rc']}; " + "; ".join((r["errors"] + r["warnings"])[:2]))
    lines += ["", "| OpenDRIVE (esmini road manager) | loads | roads (esmini / file) | samples | > 0.5 m | max offset (m) | mean offset (m) |", "|---|---|---|---|---|---|---|"]
    for key, (name, o) in odr_rows.items():
        lines.append(f"| {name} | {o.get('loaded')} | {o.get('roads')} / {o.get('roads_in_file')} | {o.get('samples')} | {o.get('over_half_metre')} | {o.get('max_offset_m')} | {o.get('mean_offset_m')} |")
    for key, (name, o) in odr_rows.items():
        if o.get("over_half_metre"):
            lines.append(f"\nOutliers in `{name}`: {o['over_half_metre']} of {o['samples']} samples are more than 0.5 m away; the trimmed length of those roads "
                         f"(m, shortest first) is {o['outlier_road_lengths_m']}. Cause not investigated: candidates are roads that run within a few metres "
                         f"of each other or overlap at junctions, where another road's reference line is the nearest one.")
    lines += ["", "The offset is the distance between a point on our road centre line and the reference line esmini assigns it to; it measures whether the",
              "OpenDRIVE export and the metric map describe the same geometry. Not covered: XSD validation, the OpenDRIVE junction / lane-link semantics",
              "beyond what esmini needs to load them, and the odrviewer GUI (it crashes in this headless container, also on a minimal valid file).", ""]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if len(ok) == len(rows) and all_odr_ok else 1


if __name__ == "__main__":
    sys.exit(main())
