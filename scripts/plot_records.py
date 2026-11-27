"""Review sheets: window drawing with the reference walk, targets and vehicles of sampled records, for checking by eye.

    python scripts/plot_records.py --data train/data_city --split sft --n 24 [--filter cross]

Output: <data>/review/<id>.png and <data>/review/index.md. Walk: blue line (start: blue dot); targets: magenta circles;
avoided area: red circle; line rule: orange; vehicles: black box at the start, dashed route if moving.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from PIL import Image, ImageDraw                                    # noqa: E402

from usg.spec import scene                                          # noqa: E402
from usg.training import records as R, sampler, window as W         # noqa: E402
from p1_window import draw                                          # noqa: E402

S = 24


def px(p) -> tuple:
    return ((p[0] + W.H) * S, (W.H - p[1]) * S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "train" / "data_city"))
    ap.add_argument("--split", default="sft")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--filter", default="")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    data = Path(a.data)
    rows = [json.loads(l) for l in (data / f"{a.split}.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if a.filter in r["kind"]]
    rows = random.Random(a.seed).sample(rows, min(a.n, len(rows)))
    out = data / "review"
    out.mkdir(exist_ok=True)
    maps: dict = {}
    index = ["# Review sample", ""]
    for row in rows:
        if row["area"] not in maps:
            maps[row["area"]] = sampler.load_tool_server(ROOT / "train" / "maps_city" / f"{row['area']}.osm").model
        M = maps[row["area"]]
        win = W.build(M, row["centre"])
        w = R.Window(row["window"], win, W.localise(M, win, row["centre"]))
        rec = row["record"]
        spec, _ = scene.check(R.document(rec, w), w.M)
        plan = R.Plan(rec, w, spec).run()
        path = out / f"{row['id']}.png"
        draw(win, path, S)
        img = Image.open(path).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

        def circle(p, r, colour, width=3):
            x, y = px(p)
            d.ellipse((x - r * S, y - r * S, x + r * S, y + r * S), outline=colour, width=width)

        for v in rec["vehicles"]:
            m = plan.walker.movers[v["name"]]
            x, y, h, length, wid = m.at(0.0)
            import math
            c, s = math.cos(h), math.sin(h)
            box = [(x + i * length / 2 * c - j * wid / 2 * s, y + i * length / 2 * s + j * wid / 2 * c) for i, j in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
            d.polygon([px(p) for p in box], outline=(0, 0, 0), fill=(20, 20, 20, 120))
            if v["moving"]:
                pts = [px(p) for p in m.pts]
                for i in range(len(pts) - 1):
                    d.line([pts[i], pts[i + 1]], fill=(0, 0, 0), width=1)
        for r in rec["rules"]:
            if r["kind"] == "avoid_area":
                circle(w.point(r["place"]), R.AVOID_R, (220, 0, 0))
            if r["kind"] == "near_line":
                d.line([px(p) for p in r["path"]], fill=(255, 140, 0, 200), width=3)
        d.line([px((s.x, s.y)) for s in plan.walker.samples], fill=(0, 60, 255), width=3)
        circle(rec["start"], 0.35, (0, 60, 255), 6)
        for i, s in enumerate(rec["steps"]):
            places = [w.point(p) for p in ([s["place"]] if "place" in s else s.get("places", []))]
            if s["kind"] in ("wait", "cross"):
                side = s["side"] if s["kind"] == "wait" else ("end" if s["side"] == "start" else "start")
                places = [w.side(s["crossing"], side)]
            for p in places:
                circle(p, R.R_PLACE, (200, 0, 200))
                d.text((px(p)[0] - 4, px(p)[1] - 6), str(i + 1), fill=(120, 0, 120))
        img.save(path)
        index += [f"## {row['id']}", f"`{row['kind']}`, walk {row['walk']['seconds']} s", "", row["request"], "", f"![]({path.name})", ""]
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    print(out)
    for row in rows:
        print(row["id"], row["kind"], "\n  ", row["request"])


if __name__ == "__main__":
    main()
