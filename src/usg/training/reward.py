"""Reward of one reply, judged by ``records.verify`` against the record of its dataset row (CPU; windows cached per process).

    1.0                                              every verifier field right
    else 0.1 JSON parses + 0.1 scenario builds + 0.5 x weighted share of the fields that are right        (at most 0.7)

``goals`` (weight 3) and ``rules`` (weight 2) count the share of right formulas; the other fields count 1 each. A field the record
asks nothing of (no vehicle, no signal, no rule, one task) is left out unless the reply gets it wrong.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from . import records as R
from . import sampler
from . import window as W

MAPS = Path(__file__).resolve().parents[3] / "train" / "maps_city"
CACHE = 256                                     # windows kept per process
WEIGHTS = {"goals": 3.0, "rules": 2.0}
_models: dict = {}
_windows: OrderedDict = OrderedDict()


def window_of(row: dict) -> R.Window:
    key = (row["area"], tuple(row["centre"]))
    if key not in _windows:
        if row["area"] not in _models:
            _models[row["area"]] = sampler.load_tool_server(MAPS / f"{row['area']}.osm").model
        M = _models[row["area"]]
        win = W.build(M, row["centre"])
        _windows[key] = R.Window(row["window"], win, W.localise(M, win, row["centre"]))
        if len(_windows) > CACHE:
            _windows.popitem(last=False)
    _windows.move_to_end(key)
    return _windows[key]


def value(rec: dict, judged: dict) -> float:
    if judged["ok"]:
        return 1.0
    fields = judged["fields"]
    if not fields:
        return 0.1 if judged.get("parsed") else 0.0
    parts = judged.get("parts", {})
    asked = {"vehicles": bool(rec["vehicles"]), "signal": bool(rec["signal"]), "order": len(rec["steps"]) > 1,
             "rules": bool(rec["rules"]) or rec["order"] == "ordered"}
    got = total = 0.0
    for name, right in fields.items():
        share = parts.get(name, float(right))
        if share >= 1.0 and not asked.get(name, True):
            continue
        w = WEIGHTS.get(name, 1.0)
        got += w * share
        total += w
    return 0.2 + 0.5 * got / total if total else 0.2


def score(job: tuple) -> dict:
    """job = (row, reply text) -> {reward, ok, parsed, fields, parts, error}. Never raises for a bad reply."""
    row, text = job
    w = window_of(row)
    parsed = R.parse(text) is not None
    try:
        judged = R.verify(row["record"], w, text)
    except Exception as e:                      # one odd reply must not stop a run
        judged = {"ok": False, "fields": {}, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    judged["parsed"] = parsed
    return {"reward": value(row["record"], judged), "ok": judged["ok"], "parsed": parsed, "fields": judged["fields"],
            "parts": judged.get("parts", {}), "error": judged["error"]}
