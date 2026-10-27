# Standards check with esmini

esmini GIT REV: v3.10.2-0-d1d4423b. Scenarios checked: 69.

* **OpenSCENARIO 1.3 + `<VRTask>`/`<Spec>` extension:** 69/69 load, run to the end (exit code 0) and log no error in `esmini --headless`. Warnings other than unsupported traffic-light types: 109 in total.

  * 69 x `[warn] ND model user_rig not located, using specified file path`
  * 25 x `[warn] ND model car_white not located, using specified file path`
  * 4 x `[warn] No connection from rid N lid N -> rid N eltype N - trying move to closest lane`

| OpenDRIVE (esmini road manager) | loads | roads (esmini / file) | samples | > 0.5 m | max offset (m) | mean offset (m) |
|---|---|---|---|---|---|---|
| sophia_antipolis | True | 824 / 824 | 1344 | 25 | 6.333 | 0.08 |
| synthetic | True | 24 / 24 | 36 | 0 | 0.0 | 0.0 |

Outliers in `sophia_antipolis`: 25 of 1344 samples are more than 0.5 m away; the trimmed length of those roads (m, shortest first) is [11.2, 11.2, 18.6, 22.4, 22.4, 22.4, 31.5, 31.5]. Cause not investigated: candidates are roads that run within a few metres of each other or overlap at junctions, where another road's reference line is the nearest one.

The offset is the distance between a point on our road centre line and the reference line esmini assigns it to; it measures whether the
OpenDRIVE export and the metric map describe the same geometry. Not covered: XSD validation, the OpenDRIVE junction / lane-link semantics
beyond what esmini needs to load them, and the odrviewer GUI (it crashes in this headless container, also on a minimal valid file).

## History (written by hand)

The first run of this check (esmini bin package without its resources, before the signal export was made standard-conform) passed **53 of 69** scenarios: all 16 scenarios with traffic-signal
actions were rejected (`Exception: stoi`). Two causes were isolated: esmini converts the `name` of a `TrafficSignalStateAction` to an integer (we wrote symbolic ids), and it expects lamp-state strings of
the signal type (`on;off` / `off;on`), not `red` / `green`; the OpenDRIVE signal also must not carry a `value` attribute. The exporter now writes numeric ids and lamp states, declares the symbolic names
as `ParameterDeclaration`s (the player maps them back), and puts signals that a scenario adds on crossings without a light into a scenario-specific OpenDRIVE file (`usg/signals.py`). The final run above
(esmini-demo package, which includes the signal catalogue and models; road-manager library of the bin package) passes **69/69**. The check also found and fixed a crossing object placed beyond the end of a short
junction-trimmed road. The harmless warnings are model files esmini cannot locate and four lane-connection warnings of vehicle routes.
