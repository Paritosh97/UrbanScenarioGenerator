"""Merge the two last postdoc slides of presentation_phd_v2.pptx into one: L0/L1/L2 + results on top, three animated GIFs of generated scenarios below.

GIFs: paper/slides/gifs/*.gif (frames captured from the real player driving scenarios of paper/rating/packages: item031, item022, item036; see make_gifs.py).
Output: paper/slides/presentation_phd_v2_updated.pptx (the source file is not modified).
"""
from pathlib import Path
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

H = Path("C:/urbanscenariogenerator/usg/paper/slides")
SRC = Path(r"C:\Users\Paritosh\Downloads\presentation_phd_v2.pptx")   # edited in place (backup: bak/)
prs = Presentation(SRC)
s = [x for x in prs.slides if x.shapes[0].has_text_frame and "niveaux" in x.shapes[0].text_frame.text][0]
by = {sh.name: sh for sh in s.shapes}
def put(name, x, y, w, h, size=None):
    sh = by[name]; sh.left, sh.top, sh.width, sh.height = Inches(x), Inches(y), Inches(w), Inches(h)
    if size is not None:
        for p in sh.text_frame.paragraphs:
            for r in p.runs: r.font.size = Pt(size)
            if not p.runs and p._p.find("{http://schemas.openxmlformats.org/drawingml/2006/main}endParaRPr") is not None:
                p._p.find("{http://schemas.openxmlformats.org/drawingml/2006/main}endParaRPr").set("sz", str(int(size * 100)))
    return sh

X, GW = [0.45, 3.55, 6.65], 2.95
BASE = [2, 9, 16]
for k, b in enumerate(BASE):
    x = X[k]
    put(f"Rounded Rectangle {b}", x, 0.62, GW, 0.34, 12)
    put(f"TextBox {b+1}", x, 0.98, GW, 0.3, 10)
    put(f"Rounded Rectangle {b+2}", x, 1.3, GW, 0.8)
    put(f"TextBox {b+3}", x + 0.08, 1.33, GW - 0.16, 0.74, 7.5)
    put(f"TextBox {b+4}", x, 2.12, GW, 0.2, 9)
    bg = put(f"Rounded Rectangle {b+5}", x, 2.33, GW, 0.27)
    fill = by[f"Rounded Rectangle {b+6}"]
    fw = fill.width / 914400
    put(f"Rounded Rectangle {b+6}", x, 2.33, fw, 0.27, 11)
put("Rounded Rectangle 23", 0.45, 4.93, 9.0, 0.32, 11)

def text(x, y, w, h, runs, size, color, italic=False, align=PP_ALIGN.LEFT):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.02); tf.margin_top = tf.margin_bottom = 0
    for k, (t, b) in enumerate(runs):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = t; r.font.name = "Arial"; r.font.size = Pt(size); r.font.bold = b; r.font.italic = italic; r.font.color.rgb = color
    return tb

GREY, INK = RGBColor(0x59, 0x59, 0x59), RGBColor(0x21, 0x21, 0x21)
new = [text(0.45, 2.63, 9.0, 0.2, [("Exemples générés par Qwen3.5-4B (L2, sans retouche), joués dans le joueur · GIF animés", False)], 8.5, GREY, italic=True)]
cards = [
    ("gen_green_munich.gif", "« Cross at the signalised crossing on green while a car comes down the street, and stay clear of the car. »",
     "Munich · feu rouge → vert · Car1 · obey_signal"),
    ("gen_car_paris.gif", "« Cross the road with oncoming traffic and keep clear of the speeding car. »",
     "Paris · voiture à 8 m/s · collision_free"),
    ("gen_corridor_paris.gif", "« Cross the road but stay inside the marked corridor along the crosswalk. »",
     "Paris · couloir ± 2,5 m · stay_near_path"),
]
GW2, GH2 = 2.7, 2.7 * 270 / 480
for k, (gif, prompt, meta) in enumerate(cards):
    x = X[k] + (GW - GW2) / 2
    pic = s.shapes.add_picture(str(H / "gifs" / gif), Inches(x), Inches(2.86), width=Inches(GW2))
    new.append(pic)
    pic.line.color.rgb = RGBColor(0x1D, 0x1D, 0x3F); pic.line.width = Pt(1)
    new.append(text(X[k], 2.86 + GH2 + 0.04, GW, 0.3, [(prompt, False)], 8, INK, italic=True))
    new.append(text(X[k], 2.86 + GH2 + 0.36, GW, 0.2, [(meta, False)], 8, GREY))

# animation: the new GIF block fades in on a second click, after the L0/L1/L2 code build
from lxml import etree
from copy import deepcopy
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
seq = s._element.find(f"{{{P}}}timing").find(f".//{{{P}}}cTn[@nodeType='mainSeq']/{{{P}}}childTnLst")
nid = [1000]
def n():
    nid[0] += 1; return nid[0]
def eff(spid, kind):
    return f"""<p:par xmlns:p="{P}"><p:cTn id="{n()}" presetID="10" presetClass="entr" fill="hold" nodeType="{kind}"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>
<p:set><p:cBhvr><p:cTn id="{n()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>
<p:animEffect transition="in" filter="fade"><p:cBhvr additive="repl"><p:cTn id="{n()}" dur="500"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect></p:childTnLst></p:cTn></p:par>"""
effs = "".join(eff(sh.shape_id, "clickEffect" if i == 0 else "withEffect") for i, sh in enumerate(new))
click = etree.fromstring(f"""<p:par xmlns:p="{P}"><p:cTn id="{n()}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="{n()}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{effs}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>""")
seq.append(click)
out = SRC
prs.save(out); print("saved", out, len(prs.slides), "slides")
