"""SFT (LoRA), hard-example scoring, online RL and one-shot evaluation of Qwen3.5-2B on the city dataset (train/data_city).

    python scripts/train_model.py memcheck                                         # a few minutes: do the longest cases fit the GPU?
    python scripts/train_model.py sft  --out train/runs/city_sft --epochs 1
    python scripts/train_model.py eval --split val --tag sft --adapter train/runs/city_sft
    python scripts/train_model.py hard --adapter train/runs/city_sft
    python scripts/train_model.py rl   --adapter train/runs/city_sft --out train/runs/city_rl --steps 100

Splits: sft trains on ``sft``; hard and rl use ``rl`` (never used by sft); eval uses val, test, test_heldout or test_long.
Rewards come from ``usg.training.reward`` (the dataset verifier). All conditions share prompt, precision and sampling settings.
sft, hard, rl and eval resume; sft and rl checkpoints hold the adapter and the optimizer state (<out>/last).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from usg.training import prompt, reward                                 # noqa: E402

DATA = ROOT / "train" / "data_city"
MODEL = "Qwen/Qwen3.5-2B"
TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj|in_proj_qkv|in_proj_z|out_proj)"
MAX_TOTAL = 4096                        # tokens; the longest dataset example has 3862
MAX_NEW = {"val": 1024, "test": 1024, "test_heldout": 1024, "rl": 1024, "test_long": 1700}   # longest references: 857, long split 1412


def read_jsonl(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def data_rows(split: str) -> list[dict]:
    """Dataset rows with the CURRENT system prompt (the targets do not depend on its wording)."""
    rows = read_jsonl(DATA / f"{split}.jsonl")
    system = prompt.system_prompt()
    for r in rows:
        r["system"] = system
    return rows


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------ scoring in worker processes (CPU)
def _score_group(job: tuple) -> list[dict]:
    row, texts = job                    # all replies to one request go to one process, which builds its window once
    return [reward.score((row, t)) for t in texts]


def score(ex, rows: list[dict], replies: list[list[str]]) -> list[list[dict]]:
    keys = ("area", "centre", "window", "record")
    return list(ex.map(_score_group, [({k: r[k] for k in keys}, t) for r, t in zip(rows, replies)]))


def summary(results: list[dict]) -> dict:
    n = max(1, len(results))
    out = {"n": len(results), "reward": sum(r["reward"] for r in results) / n, "ok": sum(r["ok"] for r in results) / n,
           "parsed": sum(r["parsed"] for r in results) / n}
    for name in ("map", "start", "vehicles", "signal", "task_count", "time_limits", "goals", "rules", "order"):
        out[name] = sum(bool(r["fields"].get(name)) for r in results) / n
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in out.items()}


# ------------------------------------------------------------------ model
def load(adapter: str | None = None, train: bool = False):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoTokenizer
    # on Windows an over-full GPU silently pages to system memory (several times slower); a cap makes the allocator free its cache instead
    torch.cuda.set_per_process_memory_fraction(0.88)
    tok = AutoTokenizer.from_pretrained(MODEL, padding_side="left")
    model = AutoModelForImageTextToText.from_pretrained(MODEL, dtype=torch.bfloat16, device_map={"": 0})
    if adapter:
        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
    elif train:
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, target_modules=TARGETS, task_type="CAUSAL_LM"))
    if train:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    return model, tok


def prompt_ids(tok, row: dict) -> list[int]:
    text = tok.apply_chat_template([{"role": "system", "content": row["system"]}, {"role": "user", "content": row["user"]}],
                                   add_generation_prompt=True, enable_thinking=False, tokenize=False)
    return tok(text, add_special_tokens=False)["input_ids"]


def generate(model, tok, prompts: list[list[int]], temperature: float, top_p: float, max_new: int) -> list[list[int]]:
    import torch
    n = max(map(len, prompts))
    ids = torch.tensor([[tok.pad_token_id] * (n - len(p)) + p for p in prompts], device=0)
    mask = torch.tensor([[0] * (n - len(p)) + [1] * len(p) for p in prompts], device=0)
    sampling = {"do_sample": True, "temperature": temperature, "top_p": top_p, "top_k": 0} if temperature > 0 else {"do_sample": False}
    with torch.no_grad():
        out = model.generate(input_ids=ids, attention_mask=mask, max_new_tokens=max_new, use_cache=True, pad_token_id=tok.pad_token_id,
                             eos_token_id=tok.eos_token_id, **sampling)
    res = []
    for row in out[:, n:].tolist():
        res.append(row[:row.index(tok.eos_token_id) + 1] if tok.eos_token_id in row else row)
    return res


def decode(tok, comp: list[int]) -> str:
    return tok.decode(comp, skip_special_tokens=True)


def run_cases(model, tok, ex, rows: list[dict], batch: int, temperature: float, max_new: int) -> list[dict]:
    """One reply per row, scored."""
    out = []
    model.eval()
    for k in range(0, len(rows), batch):
        part = rows[k:k + batch]
        comps = generate(model, tok, [prompt_ids(tok, r) for r in part], temperature, 0.9, max_new)
        texts = [[decode(tok, c)] for c in comps]
        for r, c, t, s in zip(part, comps, texts, score(ex, part, texts)):
            out.append({"id": r["id"], "kind": r["kind"], "tokens": len(c), "reply": t[0], **s[0]})
    return out


# ------------------------------------------------------------------ checkpoints
def save_checkpoint(out: Path, model, opt, state: dict) -> None:
    """Written beside the old one and swapped in, so an interrupted save leaves a usable checkpoint."""
    import torch
    new, last, old = out / "new", out / "last", out / "old"
    shutil.rmtree(new, ignore_errors=True)
    model.save_pretrained(new)
    torch.save(opt.state_dict(), new / "optimizer.pt")
    (new / "state.json").write_text(json.dumps(state))
    if last.exists():                           # without ``last``, ``old`` is the only checkpoint: keep it
        shutil.rmtree(old, ignore_errors=True)
        last.rename(old)
    new.rename(last)
    shutil.rmtree(old, ignore_errors=True)


def checkpoint(out: Path) -> tuple[Path | None, dict]:
    for d in (out / "last", out / "old"):
        if (d / "state.json").exists():
            return d, json.loads((d / "state.json").read_text())
    return None, {}


def optimizer(model, lr: float, decay: float, resume: Path | None):
    import torch
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=decay)
    if resume:
        opt.load_state_dict(torch.load(resume / "optimizer.pt", map_location="cpu", weights_only=True))
    return opt


# ------------------------------------------------------------------ supervised fine-tuning
def sft_data(tok, rows: list[dict]) -> list[tuple]:
    data = []
    for r in rows:
        p = prompt_ids(tok, r)
        c = tok(r["reply"], add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
        if len(p) + len(c) <= MAX_TOTAL:
            data.append((p, c))
    return data


def sft_loss(model, p: list[int], c: list[int]):
    """Mean cross-entropy over the reply. Scores are computed for the reply positions only: for the whole sequence they need
    several GB at 4000 tokens."""
    import torch
    ids = torch.tensor([p + c], device=0)
    logits = model(input_ids=ids, use_cache=False, logits_to_keep=len(c) + 1).logits[0, :-1]
    return torch.nn.functional.cross_entropy(logits.float(), ids[0, len(p):])


def sft(a) -> None:
    import torch
    out = Path(a.out)
    ck, state = checkpoint(out)
    done = state.get("examples", 0)
    torch.manual_seed(a.seed)
    model, tok = load(str(ck) if ck else None, train=True)
    rows = data_rows("sft")
    random.Random(a.seed).shuffle(rows)
    rows = rows[: a.examples or len(rows)]
    data = sft_data(tok, rows)
    val_rows = data_rows("val")
    val = sft_data(tok, val_rows)
    shown = random.Random(7).sample(val_rows, min(a.val_gen, len(val_rows)))
    total = len(data) * a.epochs
    print(f"{len(rows)} rows, {len(data)} fit in {MAX_TOTAL} tokens, {a.epochs} epochs; resume at {done}", flush=True)
    order = [i for e in range(a.epochs) for i in random.Random(a.seed * 1000 + e).sample(range(len(data)), len(data))]
    opt = optimizer(model, a.lr, 0.01, ck)
    model.train()
    t0, losses, pending, saved = time.time(), [], 0, done
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for k in range(done, total):
            for g in opt.param_groups:
                g["lr"] = a.lr * min(1.0, (k + 1) / 100) * max(0.1, 1 - k / total)
            loss = sft_loss(model, *data[order[k]])
            (loss / a.accum).backward()
            losses.append(loss.item())
            pending += 1
            epoch_end = (k + 1) % len(data) == 0
            if pending == a.accum or epoch_end:
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                opt.zero_grad()
                pending = 0
            if (k + 1) % 80 == 0 or k + 1 == total:
                rec = {"examples": k + 1, "loss": sum(losses) / len(losses), "s_per_example": (time.time() - t0) / (k + 1 - done),
                       "peak_gb": torch.cuda.max_memory_allocated() / 1e9}
                losses = []
                append(out / "log.jsonl", rec)
                print(rec, flush=True)
            if epoch_end:
                epoch = (k + 1) // len(data)
                model.eval()
                with torch.no_grad():
                    val_loss = sum(sft_loss(model, *x).item() for x in val) / len(val)
                torch.manual_seed(a.seed)
                res = run_cases(model, tok, ex, shown, a.batch, 0.2, MAX_NEW["val"])
                rec = {"epoch": epoch, "val_loss": val_loss, **summary(res)}
                append(out / "val.jsonl", rec)
                print(rec, flush=True)
                model.save_pretrained(out / f"epoch{epoch}")
                model.train()
            # checkpoints only right after an optimizer step, so no gradient is lost on resume; after the epoch's validation
            if pending == 0 and (epoch_end or k + 1 - saved >= a.save_every):
                save_checkpoint(out, model, opt, {"examples": k + 1})
                saved = k + 1
    model.save_pretrained(out)


# ------------------------------------------------------------------ hard examples for RL
def hard(a) -> None:
    """Sample the SFT model several times on each request of the ``rl`` split (resumable); rl trains on those with a low mean reward."""
    import torch
    rows = data_rows("rl")
    random.Random(0).shuffle(rows)
    rows = rows[: a.candidates or len(rows)]
    out = Path(a.out)
    done = {r["id"] for r in read_jsonl(out)} if out.exists() else set()
    rows = [r for r in rows if r["id"] not in done]
    model, tok = load(a.adapter)
    model.eval()
    print(f"scoring {len(rows)} requests, {len(done)} done", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for k in range(0, len(rows), a.batch):
            part = rows[k:k + a.batch]
            t0 = time.time()
            torch.manual_seed(len(done) + k + 1)
            comps = generate(model, tok, [prompt_ids(tok, r) for r in part for _ in range(a.samples)], a.temperature, 1.0, MAX_NEW["rl"])
            texts = [[decode(tok, c) for c in comps[i * a.samples:(i + 1) * a.samples]] for i in range(len(part))]
            for r, g in zip(part, score(ex, part, texts)):
                append(out, {"id": r["id"], "kind": r["kind"], "rewards": [x["reward"] for x in g],
                             "mean": sum(x["reward"] for x in g) / len(g), "n_ok": sum(x["ok"] for x in g)})
            print(f"{k + len(part)}/{len(rows)} ({time.time() - t0:.0f} s)", flush=True)
    scored = read_jsonl(out)
    for t in (0.5, 0.7, 0.85, 0.999):
        h = [r for r in scored if r["mean"] < t]
        print(f"mean < {t}: {len(h)} of {len(scored)}; with differing rewards {sum(max(r['rewards']) - min(r['rewards']) > 1e-6 for r in h)}; "
              f"never right {sum(r['n_ok'] == 0 for r in h)}")


# ------------------------------------------------------------------ online RL (group-relative advantage, clipped ratio)
def rl(a) -> None:
    """Per request: ``group`` replies, advantage = reward - group mean (not divided by the spread); the ``select`` replies furthest
    from the mean are used for ``updates`` clipped-ratio steps."""
    import torch
    rows = data_rows("rl")
    if a.pool:
        keep = {r["id"] for r in read_jsonl(a.pool) if r["mean"] < a.threshold}
        rows = [r for r in rows if r["id"] in keep]
    print(f"{len(rows)} requests in the pool", flush=True)
    random.Random(a.seed).shuffle(rows)
    val_rows = data_rows("val")
    val_rows = random.Random(7).sample(val_rows, min(a.val_n, len(val_rows)))
    out = Path(a.out)
    ck, state = checkpoint(out)
    done = state.get("steps", 0)
    model, tok = load(str(ck) if ck else a.adapter, train=True)
    opt = optimizer(model, a.lr, 0.0, ck)

    def logprobs(p: list[int], c: list[int]):
        ids = torch.tensor([p + c], device=0)
        logits = model(input_ids=ids, use_cache=False, logits_to_keep=len(c) + 1).logits[0, :-1].float()
        return torch.log_softmax(logits, -1).gather(1, ids[0, len(p):, None])[:, 0]

    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        def validate(step: int) -> None:
            torch.manual_seed(a.seed)
            rec = {"step": step, **summary(run_cases(model, tok, ex, val_rows, a.gen_batch, 0.2, MAX_NEW["val"]))}
            append(out / "val.jsonl", rec)
            print("VAL", rec, flush=True)

        if done == 0:
            validate(0)
        for step in range(done, a.steps):
            t0 = time.time()
            torch.manual_seed(a.seed * 100000 + step)
            batch = [rows[(step * a.prompts + i) % len(rows)] for i in range(a.prompts)]
            prompts = [prompt_ids(tok, r) for r in batch]
            model.eval()
            groups = []
            for p in prompts:
                g: list = []
                while len(g) < a.group:
                    g += generate(model, tok, [p] * min(a.gen_batch, a.group - len(g)), a.temperature, 1.0, MAX_NEW["rl"])
                groups.append(g)
            t_gen = time.time() - t0
            results = score(ex, batch, [[decode(tok, c) for c in g] for g in groups])
            t_score = time.time() - t0 - t_gen
            used = []                                    # (prompt, completion, advantage)
            for p, g, res in zip(prompts, groups, results):
                mean = sum(x["reward"] for x in res) / len(res)
                far = sorted(range(len(g)), key=lambda j: -abs(res[j]["reward"] - mean))[: a.select]
                used += [(p, g[j], res[j]["reward"] - mean) for j in far if abs(res[j]["reward"] - mean) > 1e-6 and g[j]]
            with torch.no_grad():                        # reference log-probabilities of the policy that sampled (dropout off)
                old = [logprobs(p, c) for p, c, _ in used]
            model.train()
            for _ in range(a.updates if used else 0):
                opt.zero_grad()
                for (p, c, adv), before in zip(used, old):
                    ratio = torch.exp(logprobs(p, c) - before)
                    surr = torch.minimum(ratio * adv, torch.clamp(ratio, 1 - a.clip, 1 + a.clip) * adv)
                    (-surr.mean() / len(used)).backward()
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
            flat = [x for res in results for x in res]
            rec = {"step": step + 1, **summary(flat), "len": sum(len(c) for g in groups for c in g) / len(flat), "updated_on": len(used),
                   "s_gen": round(t_gen), "s_score": round(t_score), "s_step": round(time.time() - t0),
                   "peak_gb": torch.cuda.max_memory_allocated() / 1e9}
            append(out / "log.jsonl", rec)
            print(rec, flush=True)
            if (step + 1) % a.val_every == 0 or step + 1 == a.steps:
                validate(step + 1)
            if (step + 1) % a.save_every == 0 or step + 1 == a.steps:
                save_checkpoint(out, model, opt, {"steps": step + 1})
    model.save_pretrained(out)


# ------------------------------------------------------------------ one-shot evaluation
def evaluate(a) -> None:
    import torch
    out = ROOT / "train" / "eval" / "city" / f"{a.split}_{a.tag}.jsonl"
    done = {(r["id"], r["rep"]) for r in read_jsonl(out)} if out.exists() else set()
    rows = data_rows(a.split)
    if a.n:
        rows = random.Random(7).sample(rows, min(a.n, len(rows)))
    model, tok = load(a.adapter)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for rep in range(a.reps):
            todo = [r for r in rows if (r["id"], rep) not in done]
            for k in range(0, len(todo), a.batch):
                t0 = time.time()
                torch.manual_seed(rep * 100000 + k)
                for res in run_cases(model, tok, ex, todo[k:k + a.batch], a.batch, a.temperature, MAX_NEW[a.split]):
                    append(out, {**res, "rep": rep, "model": a.tag})
                print(f"rep {rep}: {min(k + a.batch, len(todo))}/{len(todo)} ({time.time() - t0:.0f} s)", flush=True)
    print(summary(read_jsonl(out)))


# ------------------------------------------------------------------ memory check
def memcheck(a) -> None:
    """One SFT step on the longest example, an RL-sized generation on the longest RL prompt and an update of that length."""
    import torch
    model, tok = load(a.adapter, train=True)
    longest = max(sft_data(tok, data_rows("sft")), key=lambda x: len(x[0]) + len(x[1]))
    opt = optimizer(model, 1e-5, 0.0, None)

    def report(what: str, t0: float) -> None:
        print(f"{what}: {time.time() - t0:.1f} s, peak {torch.cuda.max_memory_allocated() / 1e9:.1f} GB", flush=True)
        torch.cuda.reset_peak_memory_stats()

    t0 = time.time()
    model.train()
    sft_loss(model, *longest).backward()
    opt.step()
    opt.zero_grad()
    report(f"SFT step, {len(longest[0]) + len(longest[1])} tokens", t0)
    p = max((prompt_ids(tok, r) for r in data_rows("rl")), key=len)
    model.eval()
    t0 = time.time()
    ids = torch.tensor([p] * a.gen_batch, device=0)
    with torch.no_grad():                                # forced to the full length: the worst case
        model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=MAX_NEW["rl"], min_new_tokens=MAX_NEW["rl"],
                       do_sample=True, use_cache=True, pad_token_id=tok.pad_token_id)
    report(f"generate {a.gen_batch} x ({len(p)} + {MAX_NEW['rl']}) tokens", t0)
    t0 = time.time()
    model.train()
    sft_loss(model, p, [tok.eos_token_id] * MAX_NEW["rl"]).backward()
    report(f"update on {len(p) + MAX_NEW['rl']} tokens", t0)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def command(name: str, **defaults):
        c = sub.add_parser(name)
        c.add_argument("--workers", type=int, default=8, help="scoring processes (CPU)")
        for key, value in defaults.items():
            c.add_argument("--" + key.replace("_", "-"), type=str if value is None else type(value), default=value)
        return c

    sft_dir = str(ROOT / "train" / "runs" / "city_sft")
    scores = str(ROOT / "train" / "hard" / "city_scores.jsonl")
    command("sft", out=sft_dir, examples=0, epochs=1, accum=4, lr=2e-4, seed=0, save_every=400, val_gen=96, batch=8)
    command("hard", adapter=sft_dir, out=scores, candidates=0, samples=4, batch=2, temperature=1.0)
    command("rl", adapter=sft_dir, out=str(ROOT / "train" / "runs" / "city_rl"), pool=scores, threshold=0.85, steps=100, prompts=3,
            group=16, select=4, updates=3, clip=0.1, lr=3e-5, temperature=1.0, gen_batch=8, seed=0, save_every=5, val_every=25, val_n=96)
    e = command("eval", adapter=None, n=0, reps=1, batch=8, temperature=0.2)
    e.add_argument("--tag", required=True)
    e.add_argument("--split", choices=["val", "test", "test_heldout", "test_long"], default="val")
    command("memcheck", adapter=None, gen_batch=8)
    a = ap.parse_args()
    {"sft": sft, "hard": hard, "rl": rl, "eval": evaluate, "memcheck": memcheck}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
