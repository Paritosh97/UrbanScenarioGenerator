"""Examples of 30 x 30 m map windows (text, drawing, stored record) and length statistics.

    python scripts/p1_window.py [--map eval/maps/paris_center.osm] [--n 20] [--out paper/p1]
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from usg.training import sampler, window as W           # noqa: E402


def draw(win: dict, path: Path, scale: int = 24) -> None:
    """Top-down picture of the window content (what the text says)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (int(W.SIZE * scale),) * 2, (238, 236, 228))
    d = ImageDraw.Draw(img)
    e = win["elements"]

    def px(pts):
        return [((x + W.H) * scale, (W.H - y) * scale) for x, y in pts]

    def label(pts, text):
        p = px(pts)
        d.text((sum(a for a, _ in p) / len(p) - 20, sum(b for _, b in p) / len(p) - 6), text, fill=(0, 0, 150))

    for a in e["areas"]:
        d.polygon(px(a["outline"]), fill=(170, 200, 240) if a["type"] == "water" else (190, 220, 180))
    for p in e["paths"]:
        d.line(px(p["line"]), fill=(225, 205, 160), width=int(p["width"] * scale), joint="curve")
    for s in e["stairs"]:
        d.polygon(px(s["outline"]), fill=(205, 175, 130))
    for w in e["sidewalks"]:
        d.line(px(w["line"]), fill=(196, 196, 196), width=int(w["width"] * scale), joint="curve")
    for r in e["roads"]:
        d.line(px(r["line"]), fill=(92, 92, 98), width=int(r["width"] * scale), joint="curve")
    for j in e["junctions"]:
        (x, y), k = px([j["pos"]])[0], 5
        d.rectangle((x - k, y - k, x + k, y + k), fill=(240, 140, 20))
    for c in e["crossings"]:
        d.line(px(c["line"]), fill=(250, 250, 250) if c["control"] == "zebra" else (250, 220, 90), width=int(c["width"] * scale))
    for b in e["buildings"]:
        d.polygon(px(b["outline"]), fill=(168, 130, 110), outline=(80, 55, 45))
        for h in b["holes"]:
            d.polygon(px(h), fill=(238, 236, 228), outline=(80, 55, 45))
    for b in e["barriers"]:
        d.line(px(b["line"]), fill=(50, 50, 50), width=3)
    for key, colour in (("objects", (30, 120, 40)), ("signals", (210, 30, 30))):
        for o in e[key]:
            if "pos" in o:
                x, y = px([o["pos"]])[0]
                d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=colour)
                d.text((x + 7, y - 6), o["id"], fill=(0, 0, 0))
    for key in ("roads", "paths"):
        for r in e[key]:
            label(r["line"], r["id"])
    for key in ("buildings", "stairs"):
        for b in e[key]:
            label(b["outline"], b["id"])
    for c in e["crossings"]:
        label(c["line"], c["id"])
    img.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=str(ROOT / "eval" / "maps" / "paris_center.osm"))
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "paper" / "p1"))
    a = ap.parse_args()
    M = sampler.load_tool_server(Path(a.map)).model
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from transformers import AutoTokenizer
    from train_model import MODEL
    tok = AutoTokenizer.from_pretrained(MODEL)
    tokens, shown, kinds, reasons = [], {}, collections.Counter(), collections.Counter()
    for kind, centre in W.select(M, a.n, a.seed):
        win = W.build(M, centre)
        text = W.to_text(win)
        tokens.append(len(tok(text)["input_ids"]))
        kinds[kind] += 1
        reasons.update(r["reason"] for r in win["removed"])
        rich = len(win["elements"]["buildings"]) + len(win["elements"]["objects"])
        if kind not in shown or rich > shown[kind][0]:
            shown[kind] = (rich, centre, win, text)
    for kind, (_, centre, win, text) in shown.items():
        (out / f"{kind}.txt").write_text(text + "\n", encoding="utf-8")
        record = {"map": Path(a.map).stem, "kind": kind, "centre": centre, "text": text, "ids": win["ids"], "removed": win["removed"]}
        (out / f"{kind}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
        draw(win, out / f"{kind}.png")
    tokens.sort()
    print("windows", len(tokens), dict(kinds))
    print("tokens median", statistics.median(tokens), "p95", tokens[int(0.95 * len(tokens))], "max", tokens[-1])
    print("removed", dict(reasons))


if __name__ == "__main__":
    main()
