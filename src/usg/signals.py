"""Traffic-signal identifiers and states in the exported standards files.

Inside the library a signal is a symbolic name (``signal_3``, ``crossing_2_ped``); formulas and the player use it. A standard consumer such as esmini needs

* a **numeric** OpenDRIVE signal id, which ``TrafficSignalStateAction`` also uses as its ``name``, and
* a **lamp-state string** of the signal type: ``on;off`` / ``off;on`` (red / green) for a two-lamp pedestrian light (type 1000002) and
  ``on;off;off`` / ``off;off;on`` for a three-lamp traffic light (type 1000001), instead of ``red`` / ``green``.

The symbolic names are kept in the OpenSCENARIO file as ``ParameterDeclaration``s (name -> integer id), so the player maps them back.
Numbering: the map's own signals first (their order in the map), then the signals a scenario adds on crossings without a light (sorted by name).
"""
from __future__ import annotations

from typing import Iterable

LAMPS = {"pedestrian": {"red": "on;off", "green": "off;on"},
         "vehicle": {"red": "on;off;off", "green": "off;off;on"}}


def signal_numbers(model, virtual: Iterable[str] = ()) -> dict[str, int]:
    """Symbolic signal name -> numeric id (1-based): the map's signals in map order, then the scenario's virtual ones sorted."""
    out = {s.id: i + 1 for i, s in enumerate(model.signals)}
    for name in sorted(set(virtual) - set(out)):
        out[name] = len(out) + 1
    return out


def signal_kind(model, name: str) -> str:
    """'vehicle' for a vehicle traffic light of the map, 'pedestrian' for everything else (including virtual crossing signals)."""
    for s in model.signals:
        if s.id == name:
            return "vehicle" if s.kind == "vehicle" else "pedestrian"
    return "pedestrian"


def lamp_state(kind: str, state: str) -> str:
    """'red' / 'green' -> the lamp-state string of the signal type."""
    return LAMPS[kind][state]


def symbolic_state(text: str) -> str:
    """Inverse: a lamp-state string (or an old-style 'red' / 'green') -> 'red' | 'green'."""
    if text in ("red", "green"):
        return text
    lamps = text.split(";")
    return "green" if lamps and lamps[-1] == "on" else "red"
