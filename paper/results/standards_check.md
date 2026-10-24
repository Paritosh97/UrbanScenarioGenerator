# Standards check with esmini

esmini GIT REV: v3.10.2-0-d1d4423b. Scenarios checked: 69.

* **OpenSCENARIO 1.3 + `<VRTask>`/`<Spec>` extension:** 53/69 load, run to the end (exit code 0) and log no error in `esmini --headless`. Warnings other than unsupported traffic-light types: 175 in total.

  * 69 x `[warn] ND model walkmanNosgb not located, using specified file path`
  * 69 x `[warn] ND model user_rig not located, using specified file path`
  * 25 x `[warn] ND model car_white not located, using specified file path`
  * `sophia_antipolis__signal_cross__v0`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_traffic__v0`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_cross__v1`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_traffic__v1`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_cross__v2`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_traffic__v2`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_cross__v3`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `sophia_antipolis__signal_traffic__v3`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `synthetic__signal_cross__v0`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path
  * `synthetic__signal_traffic__v0`: rc=255; [] [error] Exception: stoi; [] [warn] 3D model walkman.osgb not located, using specified file path

| OpenDRIVE (esmini road manager) | loads | roads (esmini / file) | samples | > 0.5 m | max offset (m) | mean offset (m) |
|---|---|---|---|---|---|---|
| sophia_antipolis | True | 824 / 824 | 1344 | 25 | 6.333 | 0.08 |
| synthetic | True | 24 / 24 | 36 | 0 | 0.0 | 0.0 |

Outliers in `sophia_antipolis`: 25 of 1344 samples are more than 0.5 m away; the trimmed length of those roads (m, shortest first) is [11.2, 11.2, 18.6, 22.4, 22.4, 22.4, 31.5, 31.5]. Cause not investigated: candidates are roads that run within a few metres of each other or overlap at junctions, where another road's reference line is the nearest one.

The offset is the distance between a point on our road centre line and the reference line esmini assigns it to; it measures whether the
OpenDRIVE export and the metric map describe the same geometry. Not covered: XSD validation, the OpenDRIVE junction / lane-link semantics
beyond what esmini needs to load them, and the odrviewer GUI (it crashes in this headless container, also on a minimal valid file).

## Analysis of the failures (written by hand after the run)

All 53 scenarios without traffic-signal actions load and run to the end in esmini v3.10.2. All 16 scenarios with traffic-signal actions
(`signal_cross`, `signal_traffic`, on both maps) are **rejected** (exit code 255, `Exception: stoi`). Two causes were isolated on one scenario:

1. esmini converts the `name` of a `TrafficSignalStateAction` to an integer, so it needs numeric OpenDRIVE signal ids. We write symbolic ids (`signal_1`).
   With numeric ids in both files the `stoi` error disappears.
2. The next error is then `TrafficLight: Invalid mode 'red', valid modes are 'unknown', 'other', 'off', 'on', 'flashing' and 'counting'`: esmini expects the state
   string to be a lamp mode of one of *its* traffic-light types (the signal type `1000002` we export is reported as not supported), not `red` / `green`.

So the signal part of the extension is **not yet loadable by a standard player**; the scenarios without signals are. A fix needs numeric signal ids plus a
state vocabulary the consumer's signal catalogue understands, while the player keeps its symbolic names (for example through a mapping stored in the file).
This is future work; it does not affect the player, the validator or the headless environment. The esmini release used here has no `resources` folder
(3D models and signal catalogue are missing), which explains the model-not-located warnings; they are harmless.
