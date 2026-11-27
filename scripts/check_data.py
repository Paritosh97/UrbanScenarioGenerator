"""Integrity of the dataset: sizes, unique ids and requests, split separation, held-out combinations, prompt reconstruction."""
import sys, json, collections
from pathlib import Path
sys.path.insert(0, "src")
from usg.training import records as R, window as W
D = Path(sys.argv[1] if len(sys.argv) > 1 else "train/data_city")
S = {s: [json.loads(l) for l in (D / f"{s}.jsonl").read_text(encoding="utf-8").splitlines()] for s in ("sft", "rl", "val", "test", "test_heldout", "test_long")}
rows = [r for v in S.values() for r in v]
print({s: len(v) for s, v in S.items()}, "total", len(rows))
print("unique ids", len({r["id"] for r in rows}), "unique (window, request)", len({(r["window"], r["request"]) for r in rows}), "unique user prompts", len({r["user"] for r in rows}))
win = {s: {r["window"] for r in v} for s, v in S.items()}
for a, b in (("sft", "rl"), ("sft", "val"), ("rl", "val"), ("sft", "test"), ("test", "test_heldout"), ("test", "test_long")):
    print("shared windows", a, b, len(win[a] & win[b]))
train = [r for s in ("sft", "rl") for r in S[s]]
near = [min((max(abs(v["centre"][0] - t["centre"][0]), abs(v["centre"][1] - t["centre"][1])) for t in train if t["area"] == v["area"]), default=1e9) for v in S["val"]]
print("closest train window to a val window (m)", round(min(near), 1))
print("areas shared train/test", len({r["area"] for r in train} & {r["area"] for s in ("test", "test_heldout", "test_long") for r in S[s]}))
held = lambda r: R.is_held_out([s["kind"] for s in r["record"]["steps"]], [x["kind"] for x in r["record"]["rules"]], r["kind"].rsplit("|", 1)[1])
print({s: sum(map(held, v)) for s, v in S.items()}, "held-out records per split")
types = {r["kind"] for r in train}
print("test records whose exact type is not in training:", sum(r["kind"] not in types for r in S["test"]), "of", len(S["test"]))
