"""Run a generated scenario in esmini (an independent OpenSCENARIO player) and report whether it loads and runs.

esmini is not a dependency of the package. Download a release (https://github.com/esmini/esmini/releases) and set ``ESMINI_BIN`` to its ``bin`` folder
(or put ``esmini`` on the PATH); use the ``esmini-demo`` package when you also want its signal catalogue and 3D models. ``find`` returns None when it
is not installed, and the callers then skip the check.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def find(hint: Optional[str | Path] = None) -> Optional[Path]:
    """Path of the esmini executable: ``hint`` (a bin folder or the executable), ``ESMINI_BIN``, or the PATH; None if not found."""
    for cand in (hint, os.environ.get("ESMINI_BIN"), shutil.which("esmini")):
        if cand:
            p = Path(cand)
            p = p / "esmini" if p.is_dir() else p
            if p.exists():
                return p
    return None


def run(esmini: Path, xosc: str, odr: str | Path, timeout: float = 180.0) -> dict:
    """Run one scenario headless (fixed time step, no window). Returns {rc, loaded, errors, warnings}.

    A scenario passes when it is loaded as OpenSCENARIO 1.3, runs to its end with exit code 0 and logs no error. ``odr`` is the OpenDRIVE file the
    scenario refers to (it is copied next to the scenario as ``map.xodr``).
    """
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
    return {"rc": rc, "loaded": any("Loading s.xosc (v1.3)" in ln for ln in lines),
            "errors": [ln for ln in lines if "[error]" in ln],
            "warnings": [ln for ln in lines if "[warn]" in ln and "Traffic sign mapping" not in ln and "not located" not in ln]}


def ok(result: dict) -> bool:
    return result["rc"] == 0 and result["loaded"] and not result["errors"]


def message(result: dict) -> str:
    """A short reason for the model / the log when a scenario does not pass."""
    if result["rc"] is None:
        return "esmini timed out"
    if not result["loaded"]:
        return "esmini could not load the OpenSCENARIO file" + ((": " + result["errors"][0].split("] ", 1)[-1][:200]) if result["errors"] else "")
    if result["errors"]:
        return "esmini reported: " + "; ".join(e.split("] ", 1)[-1][:200] for e in result["errors"][:2])
    return f"esmini exited with code {result['rc']}"
