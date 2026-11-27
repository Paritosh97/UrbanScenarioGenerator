# Map part of the user prompt: algorithm and format (for the appendix; point notes, not paper text)

Code: `src/usg/training/window.py`; examples: `scripts/p1_window.py` -> `paper/p1/{crossing,junction,street,pedestrian}.{txt,json,png}`; test: `tests/test_window.py`.
Status: **template frozen 27 Nov 2026** (tests of the last two fixes not yet run); **not yet** used by the generator, the checks or the simulator.

## Input
Metric map model built from an OpenStreetMap extract (roads, junctions, crossings, signals, objects, buildings, barriers, areas, paths).

## A. Window selection (`select`)
1. Anchor points: crossings; junctions; points every 15 m on roads of at least 30 m (street); points every 15 m on pedestrian ways and footpaths (pedestrian).
2. Quotas: crossing 40%, junction 20%, street 25%, pedestrian 15%.
3. Centre = random anchor + uniform offset in [-6, 6] m in x and y (seeded).
4. Conditions: street = no crossing and no junction inside; pedestrian = no crossing and no road inside; at least 5% of a 10 x 10 sample grid is sidewalk, path or crossing.
5. Centres at least 20 m apart (largest coordinate difference): windows can overlap by up to 10 m, so splits are made by area, never by window.

## B. Content (`build`)
1. Coordinates relative to the centre; x east, y north; 0.1 m.
2. Lines clipped to the window (Liang-Barsky), polygons (Sutherland-Hodgman); vertices within 0.4 m of the line through their neighbours removed; pieces under 1 m or 1 m2 removed and logged.
3. Roads: class, width, lanes, direction, speed limit, centre line. Sidewalks: mapped OSM sidewalks, plus assumed 2 m strips on road sides without them (map import: a mapped sidewalk within 5 m of the assumed strip over at least half of the road side replaces it). A sidewalk is named by compass side of the nearest road running within 30 degrees of it; mapped ones lying on a road are removed and logged.
4. Road ends: leaves the window / at a junction / continues as another road / road ends. Junctions: position, radius, roads joined, signalised.
5. Stairs: pieces within 2 m of each other form one area (convex hull of the widened lines).
6. Paths: widest first; a path with at least 80% of its length on a road, a sidewalk or a wider path is removed (merged) and logged.
7. Crossings whose centre is inside the window; signals inside the window (a referenced signal outside keeps an id).
8. Objects keep their positions. Removed and logged: inside a building or water; tree, bench, waste basket, street lamp, bus stop or bicycle parking on the road or a crossing; duplicates within 0.3 m. Bollards may stand on the carriageway.
9. Ids are local to the window, numbered per type from north to south, then west to east. The record stores local id -> source id, the centre and the removal log.

Also: assumed sidewalks are cut where their centre comes within 0.5 m of another carriageway (logged). Roads and paths tagged
`tunnel=building_passage` are marked `passes under a building`; there the building does not count as a surface, and the player draws that
building's ground floor see-through.

## C. Text (`to_text`)
Fixed section order: MAP, ROADS (with ends), SIDEWALKS, JUNCTIONS, CROSSINGS, SIGNALS, PATHS, STAIRS, OBJECTS (grouped by type), BUILDINGS, AREAS, BARRIERS. Empty sections say `none`. Same window -> same text.

## Measured (Zurich, new download of 27 Nov 2026, 200 windows)
Map text: median 734 tokens, 95th percentile 1499, maximum 1791 (Qwen3.5-2B tokenizer). Completeness test passes on the 12 areas downloaded so far.

## Known limits (open)
* Bus-only and access restrictions of roads are not passed.
* Road widths and some other values are defaults where OpenStreetMap has none.
* Area outlines come from closed ways only. Building relations are read (outer rings, courtyards) for maps downloaded with the new query.
* Four of the 16 areas still have to be downloaded again (server errors).
