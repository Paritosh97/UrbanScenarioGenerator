"""Measure batched generation speed of the 4-bit base model (the bottleneck of online RL).

    python scripts/train_genspeed.py
"""
from __future__ import annotations

import time

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

import os
MODEL = os.environ.get("USG_MODEL", "Qwen/Qwen3.5-2B")
tok = AutoTokenizer.from_pretrained(MODEL, padding_side="left")
q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForImageTextToText.from_pretrained(MODEL, dtype=torch.bfloat16, quantization_config=q, device_map={"": 0}).eval()
text = tok.apply_chat_template([{"role": "user", "content": "Write a Python script that prints the first 200 squares, one per line."}],
                               add_generation_prompt=True, enable_thinking=False, tokenize=False)
for batch in (1, 8, 16):
    enc = tok([text] * batch, return_tensors="pt", padding=True).to(0)
    torch.cuda.reset_peak_memory_stats()
    t = time.time()
    out = model.generate(**enc, max_new_tokens=128, min_new_tokens=128, do_sample=True, temperature=0.7, pad_token_id=tok.pad_token_id)
    dt = time.time() - t
    n = (out.shape[1] - enc["input_ids"].shape[1]) * batch
    print(f"batch {batch}: {n} tokens in {dt:.1f} s = {n / dt:.1f} tok/s, peak {torch.cuda.max_memory_allocated() / 1e9:.2f} GB", flush=True)
