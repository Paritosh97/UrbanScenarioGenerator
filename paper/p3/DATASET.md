# Paris / Munich L1 dataset (generated 27 Nov 2026)

Point notes, not paper text. Data: `train/data_city/` (`<split>.jsonl`, `windows.json`, `STATS.md`, `review/`). This replaces `GENERATION.md`.

## Commands
```
python scripts/fetch_city_maps.py                      # 8 areas, OpenStreetMap (ODbL), downloaded 27 Nov 2026
python scripts/window_data.py --workers 12             # about 16 min, CPU
python scripts/check_data.py                           # splits and integrity
python scripts/check_verifier.py train/data_city 150   # verifier on right and wrong replies
python scripts/plot_records.py --split sft --n 24      # pictures for checking by eye
```

## Splits
| split | records | areas | content |
|---|---|---|---|
| sft | 6000 | 6 training areas | 1-3 steps, 0-2 rules |
| rl | 2004 | 6 training areas | same, other windows |
| val | 504 | eastern strip of the training areas | closest training window centre: 34.5 m |
| test | 1000 | paris_center, munich_center | new streets; 75 have a type not in sft+rl |
| test_heldout | 300 | centres | wait+parked, near_line+moving, stay+stay_on_sidewalk |
| test_long | 200 | centres | 4-5 steps |

The centre areas are the old evaluation maps (used during earlier development, never for this training data).

## Row
`id, split, city, area, window, centre, window_kind, kind, record, request, system, user, reply, walk`

## Reply format (changed)
One JSON document: `start, signals, vehicles, tasks`. No Python script (`src/usg/spec/scene.py`).

## Algorithm (`training/records.py`, `training/walk.py`)
1. Windows per area: signalised crossings first (at most a third), then the quota mix of `window.select`.
2. Draw a type (steps, order, rules, vehicle) the window can host, favouring the least used parts.
3. Place it: start, targets and vehicles from cells reachable on a 0.5 m grid.
4. Prove it: map validator; A path (Dijkstra) for every leg avoiding buildings, barriers, vehicles and rule areas; simulated walk at 1.2 m/s; every goal reached and no rule broken (same monitor as the player); at most 55 s per task; not satisfied at task start; skipping a step's work fails it.
5. Render request (random phrasings, all fields stated) and reply; the verifier must accept the reply.

## Checks run on the final data
| check | result |
|---|---|
| unique ids, requests, prompts | 10008 / 10008 |
| windows shared between sft, rl, val, test | 0 |
| held-out combinations outside test_heldout | 0 |
| stored references accepted by the verifier | 150 / 150 |
| wrong replies accepted (8 kinds of error, 36-150 each) | 0 |
| export to OpenSCENARIO | 200 / 200 |
| prompt tokens (sft sample) median / p95 / max | 1779 / 2585 / 3518 |
| reply tokens (sft) median / p95 / max | 272 / 515 / 743 |
| reply tokens (test_long) median / p95 / max | 572 / 1179 / 1411 |

## Limits
* Signal tasks are rare: wait 287, obey_signal 540 of 10008.
* A walker who ignores the rule rarely fails for: near_line (40 of 1512), keep_distance (62 of 2386), stay_on_sidewalk (126 of 1650), look_before_road (228 of 1235). The labels are correct, but these rules seldom constrain the walk.
* 47935 candidates were rejected (mostly: nothing to avoid near the walk, too few places, no room to park).
* The verifier requires the same formulas (and/or order free) or the same predicates and time bounds with equal results on test walks. Valid replies written very differently are rejected.
* The verifier check used errors we thought of; it does not give a false-accept rate for model errors.
* No human check yet. Pictures were inspected for only a few records.
* Vehicles ignore signals; no walking pedestrians; the walk uses our grid, not the VR player; exported files were not loaded in the player.
* Requests are template phrasings.
