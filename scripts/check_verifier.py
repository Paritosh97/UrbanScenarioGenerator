"""Check of the reply verifier: stored references must pass, deliberately wrong replies must fail.

    python scripts/check_verifier.py [data dir] [rows]
"""
import sys, json, copy, random, collections, time
sys.path.insert(0,"src"); from pathlib import Path
from usg.training import records as R, sampler, window as W
DATA=Path(sys.argv[1] if len(sys.argv)>1 else "train/data_city"); COUNT=int(sys.argv[2]) if len(sys.argv)>2 else 200
t0=time.time()
rows=[json.loads(l) for s in ("sft","rl","test") for l in (DATA/f"{s}.jsonl").read_text().splitlines()]
rows=random.Random(1).sample(rows,min(COUNT,len(rows)))
maps={}; n=collections.Counter(); bad=collections.Counter(); rng=random.Random(0)
for row in rows:
    a=row["area"]
    if a not in maps: maps[a]=sampler.load_tool_server(Path(f"train/maps_city/{a}.osm")).model
    win=W.build(maps[a],row["centre"]); w=R.Window(row["window"],win,W.localise(maps[a],win,row["centre"]))
    rec=row["record"]
    assert W.to_text(win) in row["user"]
    n["reference"]+=1; bad["reference"]+=not R.verify(rec,w,row["reply"])["ok"]
    doc=R.parse(row["reply"])
    def m(name,f):
        d=copy.deepcopy(doc)
        if f(d) is False: return
        n[name]+=1
        if R.verify(rec,w,"```json\n"+json.dumps(d)+"\n```")["ok"]: bad[name]+=1
    m("start moved 3 m",lambda d:d.update(start=[d["start"][0]+3,d["start"][1]]))
    m("last task dropped",lambda d:False if len(d["tasks"])<2 else d.update(tasks=d["tasks"][:-1]))
    m("one rule dropped",lambda d:False if not any(t.get("safety") for t in d["tasks"]) else next(t for t in d["tasks"] if t.get("safety"))["safety"].pop() and None)
    def swap(d):
        if rec["order"]=="any" or len(d["tasks"])<2: return False
        a,b=d["tasks"][0],d["tasks"][1]
        if a["goal"]==b["goal"]: return False
        a["goal"],b["goal"]=b["goal"],a["goal"]
    m("two goals swapped",swap)
    def order(d):
        if len(d["tasks"])<2: return False
        for i,t in enumerate(d["tasks"]):
            if rec["order"]=="any": t.pop("mode",None); 
            else: t.pop("after",None); t["mode"]="parallel"
        if rec["order"]=="any":
            for i,t in enumerate(d["tasks"][1:],1): t["after"]=[d["tasks"][i-1]["name"]]
    m("order changed",order)
    def num(d):
        found=[]
        def walk(o):
            if isinstance(o,dict):
                for k,v in o.items():
                    if k in ("seconds","r","tol","d","angle","speed","green","red") and isinstance(v,(int,float)): found.append((o,k))
                    else: walk(v)
            elif isinstance(o,list):
                for v in o: walk(v)
        walk(d)
        if not found: return False
        o,k=rng.choice(found); o[k]=o[k]+ (5 if k in("seconds","angle","green","red") else 1)
    m("one number changed",num)
    def ref(d):
        found=[]
        def walk(o):
            if isinstance(o,dict):
                if o.get("kind")=="crossing_side": found.append(o)
                for v in o.values(): walk(v)
            elif isinstance(o,list):
                for v in o: walk(v)
        walk(d)
        if not found: return False
        found[0]["side"]="end" if found[0]["side"]=="start" else "start"
    m("crossing side flipped",ref)
    m("vehicle dropped",lambda d:False if not d.get("vehicles") else d["vehicles"].pop() and None)
for k in n: print(f"{k}: tried {n[k]}, {'wrongly rejected' if k=='reference' else 'wrongly accepted'} {bad[k]}")
print(f"{time.time()-t0:.0f} s for {len(rows)} records")
