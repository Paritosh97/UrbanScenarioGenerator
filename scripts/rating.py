"""Human rating of prompt-scenario match (the Text2Scenario protocol: raters score 0-1 in steps of 0.1 how well a scenario fits its text).

    # 1. sample accepted scenarios (needs a benchmark run made with --save-specs) and blind them
    python scripts/rating.py sheet --runs ../paper/results/benchmark.jsonl --prompts eval/prompts_sophia.json eval/prompts_munich.json \\
        --n 60 --raters 15 --out ../paper/rating
    # 2. raters fill ../paper/rating/ratings.csv (copy of ratings_template.csv): item_id, rater, score
    # 3. analyse
    python scripts/rating.py summary --dir ../paper/rating

Items are shuffled and carry no pipeline / model / level, only the prompt and the task instructions; ``key.csv`` links them back. The scenario
itself is ``scenarios/<item>.xosc`` (open it in the player, ``usg app`` -> /player, or load the file there) - raters should play or watch it,
not just read the text. Sampling is stratified by pipeline level, map and model so every cell gets about the same number of items.

Ethics: check whether your institution needs consent / approval for the rater study before running step 2.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

SCORES = [round(0.1 * i, 1) for i in range(11)]
INSTRUCTIONS = """# Rating instructions

You will see a short text request and a scenario made for it. Play each scenario in the viewer (WASD + mouse, Shift to run; or VR), do what the
on-screen task instructions say, then score how well the SCENARIO matches the TEXT REQUEST: 0.0 = does not match at all, 1.0 = matches completely
(steps of 0.1).

* Judge the match to the text only: not graphics, not how hard the task is, not whether you finished it.
* Check the things the text names: the place (crossing, bench, road ...), the order, the rules (traffic light, cars, staying on a path).
* Do not guess how the scenarios were made; the order is random and the same for everybody.
* Rate each item once; do not change earlier scores because of later items.
"""


_MAPS: dict = {}


def _package(r: dict, item: str) -> str:
    """The scenario package the player loads (map + OpenSCENARIO + specification), named by the item id so it does not give the pipeline away."""
    sys.path.insert(0, str(Path(__file__).parent))
    import benchmark as bm                                          # load_map: the cached OSM extract of the benchmark map
    if r["map"] not in _MAPS:
        _MAPS[r["map"]] = bm.load_map(r["map"], 1).model.to_dict()
    return json.dumps({"format": "usg-scenario-package/1", "name": item, "map": _MAPS[r["map"]], "xosc": r["xosc"], "spec": r["spec"],
                       "script": "", "plan": [], "issues": [], "spec_doc": None})


def cmd_sheet(a) -> int:
    texts = {}
    for p in a.prompts:
        for q in json.loads(Path(p).read_text(encoding="utf-8"))["prompts"]:
            texts[q["id"]] = q["text"]
    runs = [json.loads(line) for line in Path(a.runs).read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = [r for r in runs if r.get("accepted") and r.get("spec") and r["id"] in texts and r["level"] != "baseline"]
    if not pool:
        print("no accepted runs with a stored spec: run scripts/benchmark.py with --save-specs")
        return 1
    rng = random.Random(a.seed)
    cells = defaultdict(list)
    for r in pool:
        cells[(str(r["level"]), r["map"], r.get("model"))].append(r)
    for v in cells.values():
        rng.shuffle(v)
    chosen = []
    while len(chosen) < a.n and any(cells.values()):                 # round robin over the cells
        for k in sorted(cells, key=str):
            if cells[k] and len(chosen) < a.n:
                chosen.append(cells[k].pop())
    rng.shuffle(chosen)
    out = Path(a.out)
    (out / "scenarios").mkdir(parents=True, exist_ok=True)
    with (out / "items.csv").open("w", newline="", encoding="utf-8") as fi, (out / "key.csv").open("w", newline="", encoding="utf-8") as fk:
        wi, wk = csv.writer(fi), csv.writer(fk)
        wi.writerow(["item_id", "prompt", "task_instructions", "scenario_file"])
        wk.writerow(["item_id", "run_id", "level", "map", "model", "rep"])
        for i, r in enumerate(chosen, 1):
            item = f"item{i:03d}"
            (out / "scenarios" / f"{item}.xosc").write_text(r.get("xosc") or "", encoding="utf-8")
            instr = " | ".join(str((i.get("en") or next(iter(i.values()), "")) if isinstance(i, dict) else i) or t["name"]
                               for t in r["spec"]["tasks"] for i in [t.get("instruction") or t["name"]])
            (out / "packages").mkdir(exist_ok=True)
            (out / "packages" / f"{item}.json").write_text(_package(r, item), encoding="utf-8")
            wi.writerow([item, texts[r["id"]], instr, f"scenarios/{item}.xosc"])
            wk.writerow([item, r["id"], r["level"], r["map"], r.get("model"), r.get("rep", 0)])
    with (out / "ratings_template.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "rater", "score"])
        for k in range(1, a.raters + 1):
            for i in range(1, len(chosen) + 1):
                w.writerow([f"item{i:03d}", f"R{k:02d}", ""])
    (out / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    print(f"{len(chosen)} items from {len(cells)} cells -> {out}")
    return 0


def _icc2k(table: list[list[float]]) -> float:
    """ICC(2,k): agreement of the mean of k raters (rows = items, columns = raters, complete data only)."""
    n, k = len(table), len(table[0])
    if n < 2 or k < 2:
        return float("nan")
    gm = sum(map(sum, table)) / (n * k)
    rm = [sum(r) / k for r in table]
    cm = [sum(table[i][j] for i in range(n)) / n for j in range(k)]
    ssr = k * sum((m - gm) ** 2 for m in rm)
    ssc = n * sum((m - gm) ** 2 for m in cm)
    sst = sum((table[i][j] - gm) ** 2 for i in range(n) for j in range(k))
    sse = sst - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    return (msr - mse) / (msr + (msc - mse) / n) if (msr + (msc - mse) / n) else float("nan")


def cmd_summary(a) -> int:
    d = Path(a.dir)
    key = {r["item_id"]: r for r in csv.DictReader((d / "key.csv").open(encoding="utf-8"))}
    scores = defaultdict(dict)
    rows = []
    for f in [d / "ratings.csv"] + sorted(d.glob("ratings_R*.csv")):        # one file for everybody and/or one per rater (written by `serve`)
        if f.exists():
            rows += list(csv.DictReader(f.open(encoding="utf-8")))
    for r in rows:
        if r["score"].strip() == "":
            continue
        s = round(float(r["score"]), 1)
        if s not in SCORES:
            print(f"ignored {r['item_id']}/{r['rater']}: score {s} is not in 0.0..1.0 steps of 0.1")
            continue
        scores[r["item_id"]][r["rater"]] = s
    raters = sorted({k for v in scores.values() for k in v})
    complete = [[v[r] for r in raters] for v in scores.values() if all(r in v for r in raters)]
    item_mean = {i: st.mean(v.values()) for i, v in scores.items()}
    rng = random.Random(0)

    def ci(vals):
        if len(vals) < 2:
            return (float("nan"), float("nan"))
        bs = sorted(st.mean(rng.choices(vals, k=len(vals))) for _ in range(2000))
        return (bs[50], bs[1949])

    lines = ["# Human rating of prompt-scenario match", "",
             f"{len(scores)} items, {len(raters)} raters; score 0-1 (steps of 0.1). ICC(2,k) over the {len(complete)} fully rated items: "
             f"{_icc2k(complete):.2f}. Bootstrap 95% intervals over items.", ""]
    for field in ("level", "map", "model"):
        lines += [f"## By {field}", "", f"| {field} | items | mean score | 95% CI |", "|---|---|---|---|"]
        groups = defaultdict(list)
        for i, m in item_mean.items():
            groups[key[i][field]].append(m)
        for g, vals in sorted(groups.items(), key=lambda kv: str(kv[0])):
            lo, hi = ci(vals)
            lines.append(f"| {g} | {len(vals)} | {st.mean(vals):.2f} | [{lo:.2f}, {hi:.2f}] |")
        lines.append("")
    (d / "rating_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Rating</title>
<style>body{font:16px system-ui;max-width:760px;margin:2rem auto;padding:0 1rem}button{font:inherit;padding:.4rem .7rem;margin:.15rem}
.sc button{min-width:3.2rem}.sel{background:#2563eb;color:#fff}.box{border:1px solid #8884;border-radius:8px;padding:1rem;margin:1rem 0}small{color:#888}</style>
<h2>Prompt-scenario match</h2><div id=app></div>
<script>
const R=new URLSearchParams(location.search).get('rater')||'';
let items=[],scores={},i=0;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function init(){items=await (await fetch('/api/items')).json();scores=await (await fetch('/api/scores?rater='+R)).json();
 i=Math.max(0,items.findIndex(x=>!(x.item_id in scores)));draw();}
function draw(){const x=items[i],done=Object.keys(scores).length;
 let h=`<p><small>rater ${esc(R)} · item ${i+1} of ${items.length} · rated ${done}</small></p><div class=box><p><b>Request:</b> ${esc(x.prompt)}</p>
 <p><b>Task instructions in the scenario:</b> ${esc(x.task_instructions)}</p>
 <p><button onclick="window.open('/player/#/play?pkg=/packages/${x.item_id}.json','_blank')">Open the scenario (new tab)</button></p>
 <p>How well does the scenario match the request?</p><div class=sc>`;
 for(let k=0;k<=10;k++){const v=(k/10).toFixed(1);h+=`<button class="${scores[x.item_id]==v?'sel':''}" onclick="rate('${v}')">${v}</button>`}
 h+=`</div></div><p><button onclick="go(-1)">Previous</button><button onclick="go(1)">Next</button></p>`;
 if(done==items.length)h+='<p><b>All items rated. Thank you.</b></p>';
 document.getElementById('app').innerHTML=h;}
async function rate(v){const x=items[i];scores[x.item_id]=v;
 await fetch('/api/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rater:R,item_id:x.item_id,score:v})});
 if(i<items.length-1)i++;draw();}
function go(d){i=Math.min(items.length-1,Math.max(0,i+d));draw();}
init();
</script>"""


def cmd_serve(a) -> int:
    """Local rating page: http://localhost:PORT/?rater=R01 (items in the sheet's fixed order, the player in a new tab, scores saved to ratings_R01.csv)."""
    import re
    import uvicorn
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    d = Path(a.dir).resolve()
    items = list(csv.DictReader((d / "items.csv").open(encoding="utf-8")))
    api = FastAPI(title="usg rating")

    def path(rater: str) -> Path:
        if not re.fullmatch(r"R\d{2,3}", rater or ""):
            raise HTTPException(status_code=422, detail="rater must look like R01")
        return d / f"ratings_{rater}.csv"

    @api.get("/", response_class=HTMLResponse)
    def page():
        return PAGE

    @api.get("/api/items")
    def get_items():
        return [{k: x[k] for k in ("item_id", "prompt", "task_instructions")} for x in items]

    @api.get("/api/scores")
    def get_scores(rater: str):
        f = path(rater)
        return {r["item_id"]: r["score"] for r in csv.DictReader(f.open(encoding="utf-8")) if r["score"]} if f.exists() else {}

    @api.post("/api/score")
    def post_score(b: dict = Body(...)):
        f, item, v = path(b.get("rater", "")), b.get("item_id"), str(b.get("score"))
        if item not in {x["item_id"] for x in items} or v not in {f"{k / 10:.1f}" for k in range(11)}:
            raise HTTPException(status_code=422, detail="unknown item or score")
        cur = {r["item_id"]: r["score"] for r in csv.DictReader(f.open(encoding="utf-8"))} if f.exists() else {}
        cur[item] = v
        with f.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["item_id", "rater", "score"])
            for x in items:
                if x["item_id"] in cur:
                    w.writerow([x["item_id"], b["rater"], cur[x["item_id"]]])
        return {"ok": True}

    @api.get("/packages/{name}.json")
    def package(name: str):
        f = d / "packages" / f"{name}.json"
        if not re.fullmatch(r"item\d+", name) or not f.exists():
            raise HTTPException(status_code=404)
        return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})

    player = Path(__file__).resolve().parent.parent / "src" / "usg" / "player_dist"
    api.mount("/player", StaticFiles(directory=str(player), html=True), name="player")
    print(f"rating page: http://localhost:{a.port}/?rater=R01   (R02, R03 ... for the others)")
    uvicorn.run(api, host=a.host, port=a.port, log_level="warning")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--runs", required=True)
    s.add_argument("--prompts", nargs="+", required=True)
    s.add_argument("--n", type=int, default=60)
    s.add_argument("--raters", type=int, default=15)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--out", required=True)
    m = sub.add_parser("summary")
    m.add_argument("--dir", required=True)
    v = sub.add_parser("serve")
    v.add_argument("--dir", default="paper/rating")
    v.add_argument("--port", type=int, default=7870)
    v.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    return {"sheet": cmd_sheet, "summary": cmd_summary, "serve": cmd_serve}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
