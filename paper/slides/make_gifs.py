"""Assemble the player frames (frames/<name>/NNNN.jpg + meta.jsonl, captured by driving the real player) into small annotated GIFs."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

H = Path("C:/urbanscenariogenerator/usg/paper/slides")
OUT = H / "gifs"; OUT.mkdir(exist_ok=True)
F = lambda s, b=False: ImageFont.truetype("C:/Windows/Fonts/" + ("arialbd.ttf" if b else "arial.ttf"), s)
W, HH = 480, 270
STAT = {"pending": ((150, 150, 150), "en attente"), "active": ((245, 190, 40), "en cours"), "success": ((60, 190, 110), "réussi"), "failed": ((230, 80, 80), "échec")}

def build(name, out, ms, speed_label=None, last=None, signal=None, hold_end=1400):
    d = H / "frames" / name
    meta = [json.loads(l) for l in open(d / "meta.jsonl", encoding="utf8")]
    meta.sort(key=lambda m: m["i"])
    if last: meta = meta[:last]
    frames = []
    for m in meta:
        im = Image.open(d / f"{m['i']:04d}.jpg").convert("RGB").resize((W, HH), Image.LANCZOS)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); dr = ImageDraw.Draw(ov)
        # bottom bar: current instruction(s) with status
        rows = m["tasks"]
        y0 = HH - 8 - 24 * len(rows)
        dr.rounded_rectangle((8, y0 - 4, W - 8, HH - 6), 8, fill=(20, 20, 45, 190))
        for k, (txt, st) in enumerate(rows):
            col, lab = STAT.get(st, STAT["pending"])
            y = y0 + k * 24 + 2
            dr.ellipse((16, y + 4, 28, y + 16), fill=col + (255,))
            t = txt
            while dr.textlength(t, font=F(13, True)) > W - 130 and len(t) > 4: t = t[:-2]
            if t != txt: t = t.rstrip() + "…"
            dr.text((36, y), t, font=F(13, True), fill=(255, 255, 255, 255))
            dr.text((W - 16, y + 1), lab, font=F(12), fill=col + (255,), anchor="ra")
        # top-left chips: time, speed-up, signal
        chips = [f"t = {m['t']:.1f} s" + (f"   {speed_label}" if speed_label else "")]
        if signal and m["sig"].get(signal):
            chips.append("feu piéton : " + ("VERT" if m["sig"][signal] == "green" else "ROUGE"))
        x = 8
        for c in chips:
            col = (255, 255, 255, 255)
            if c.startswith("feu"):
                col = (110, 235, 140, 255) if "VERT" in c else (255, 120, 110, 255)
            w = dr.textlength(c, font=F(13, True)) + 16
            dr.rounded_rectangle((x, 8, x + w, 30), 8, fill=(20, 20, 45, 190)); dr.text((x + 8, 11), c, font=F(13, True), fill=col)
            x += w + 6
        frames.append(Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"))
    pal = Image.new("RGB", (W, HH * 4))
    for k in range(4): pal.paste(frames[min(len(frames) - 1, k * len(frames) // 4)], (0, k * HH))
    pal = pal.quantize(256, method=Image.MEDIANCUT, dither=Image.NONE)
    q = [f.quantize(palette=pal, dither=Image.NONE) for f in frames]
    dur = [ms] * len(q); dur[-1] = hold_end
    q[0].save(OUT / out, save_all=True, append_images=q[1:], duration=dur, loop=0, optimize=True, disposal=1)
    print(out, len(q), "frames", round((OUT / out).stat().st_size / 1e6, 2), "MB")

build("car_paris", "gen_car_paris.gif", 200, last=62)
build("green_munich", "gen_green_munich.gif", 150, speed_label="×2", signal="signal_52")
build("corridor_paris", "gen_corridor_paris.gif", 250)
