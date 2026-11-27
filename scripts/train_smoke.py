"""Short check that Qwen3.5-4B loads, generates and takes LoRA training steps on this GPU. Reports memory and speed.

    python scripts/train_smoke.py [--bits 4|16]
"""
from __future__ import annotations

import argparse
import time

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

import os
MODEL = os.environ.get("USG_MODEL", "Qwen/Qwen3.5-2B")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=16, choices=[4, 16])
    ap.add_argument("--tokens", type=int, default=4000, help="sequence length of the training test")
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(MODEL)
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16) if a.bits == 4 else None
    model = AutoModelForImageTextToText.from_pretrained(MODEL, dtype=torch.bfloat16, quantization_config=q, device_map={"": 0})
    print("class", type(model).__name__, "| loaded GB", round(torch.cuda.memory_allocated() / 1e9, 2))

    enc = tok.apply_chat_template([{"role": "user", "content": "Write a JSON object with one key 'ok'."}], add_generation_prompt=True,
                                  enable_thinking=False, return_tensors="pt", return_dict=True).to(0)
    t = time.time()
    out = model.generate(**enc, max_new_tokens=100, do_sample=False)
    n = out.shape[1] - enc["input_ids"].shape[1]
    print(f"generate: {n} tokens, {n / (time.time() - t):.1f} tok/s |", repr(tok.decode(out[0, -n:])[:120]))

    names = {name.split(".")[-1] for name, m in model.named_modules() if "visual" not in name and isinstance(m, torch.nn.Linear)}
    print("linear layer names:", sorted(names))
    targets = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj|in_proj|out_proj)"
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, target_modules=targets, task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-4)
    ids = torch.randint(100, 10000, (1, a.tokens), device=0)
    torch.cuda.reset_peak_memory_stats()
    for step in range(4):
        t = time.time()
        loss = model(input_ids=ids, labels=ids, use_cache=False).loss
        loss.backward()
        opt.step()
        opt.zero_grad()
        torch.cuda.synchronize()
        print(f"train step {step}: loss {loss.item():.3f}, {time.time() - t:.2f} s, peak {torch.cuda.max_memory_allocated() / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
