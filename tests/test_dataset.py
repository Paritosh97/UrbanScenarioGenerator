"""Dataset build / load round trip and the rating tool, on the synthetic city (no network, no model)."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from usg import osm, synth
from usg.baselines import RoutePolicy, rollout
from usg.dataset import build_dataset, iter_scenarios, stats_markdown, vary
from usg.scenario_types import ARCHETYPES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("ds")
    synthetic = osm.build_map(synth.synthetic_osm())
    rows = build_dataset(root, {"synthetic": synthetic, "synthetic_b": osm.build_map(synth.synthetic_osm())},
                         variants=2, test_maps=("synthetic_b",), log=lambda *_: None)
    return root, rows


def test_every_reference_script_makes_a_valid_scenario(built):
    _, rows = built
    base = [r for r in rows if r["map"] == "synthetic" and r["variant"] == 0]
    assert {r["type"] for r in base} == set(ARCHETYPES)
    assert all(r["nominal_ok"] for r in base)


def test_split_is_by_map_and_files_exist(built):
    root, rows = built
    assert {r["split"] for r in rows if r["map"] == "synthetic_b"} == {"test"}
    assert {r["split"] for r in rows if r["map"] == "synthetic"} == {"train"}
    for r in rows:
        assert (root / "scenarios" / f"{r['id']}.xosc").read_text().startswith("<?xml")
    assert (root / "maps" / "synthetic" / "map.xodr").exists()
    assert "Scenarios per map and type" in (root / "STATS.md").read_text()


def test_loader_yields_environments_that_the_scripted_walker_solves(built):
    root, rows = built
    sc = [s for s in iter_scenarios(root, split="test") if s.row["type"] == "ptp_env"][0]
    env = sc.env()
    assert rollout(env, RoutePolicy(env))["success"]
    assert len(list(iter_scenarios(root, split="train"))) + len(list(iter_scenarios(root, split="test"))) == len(rows)


def test_variants_change_the_script_only_where_a_choice_is_made():
    t = ARCHETYPES["cpath"]["template"]
    assert vary(t, "cpath", 0) == t and vary(t, "cpath", 1) != t
    assert "[1 % len(MAP.crossings())]" in vary(t, "cpath", 1)
    assert all(vary(a["template"], sid, 2) != a["template"] for sid, a in ARCHETYPES.items())


def test_stats_of_an_empty_dataset():
    assert "empty" in stats_markdown([])


def test_rating_sheet_is_blinded_and_summary_runs(tmp_path):
    spec = {"tasks": [{"name": "to_stop", "instruction": "Walk to the bus stop"}]}
    runs = [{"id": f"p{i}", "level": lv, "map": "m", "model": "x", "rep": 0, "accepted": True, "spec": spec, "xosc": "<xosc/>"}
            for i in range(4) for lv in (0, 2)]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (tmp_path / "prompts.json").write_text(json.dumps({"prompts": [{"id": f"p{i}", "text": f"text {i}"} for i in range(4)]}))
    out = tmp_path / "rating"
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "rating.py"), *a], capture_output=True, text=True)   # noqa: E731
    r = run("sheet", "--runs", str(tmp_path / "runs.jsonl"), "--prompts", str(tmp_path / "prompts.json"), "--n", "6", "--raters", "3",
            "--out", str(out))
    assert r.returncode == 0, r.stderr
    header = (out / "items.csv").read_text().splitlines()[0]
    assert "level" not in header and "model" not in header                       # raters never see the pipeline
    rows = list(csv.DictReader((out / "ratings_template.csv").open()))
    assert len(rows) == 6 * 3
    for i, row in enumerate(rows):
        row["score"] = ["0.9", "0.8", "0.7"][i % 3]
    with (out / "ratings.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "rater", "score"])
        w.writeheader()
        w.writerows(rows)
    r = run("summary", "--dir", str(out))
    assert r.returncode == 0, r.stderr
    assert "By level" in (out / "rating_summary.md").read_text()
