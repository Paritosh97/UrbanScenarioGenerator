"""Rebuild the four postdoc 'Urban Scenario Generator' slides (7-10, French section) of presentation.pptx.

Source: paper/slides/presentation.pptx (copy of ~/Downloads/presentation.pptx, never modified)
Output: paper/slides/presentation_updated.pptx
Facts come from paper/METHOD.md (pipeline), paper/results/summary.md (numbers) and paper/rating/ (a real generated scenario, item008).
"""
import copy
import json
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path("C:/urbanscenariogenerator/usg/paper/slides")
SRC, DST = HERE / "presentation.pptx", HERE / "presentation_updated.pptx"

NAVY, ORANGE, TEAL, PURPLE = RGBColor(0x1F, 0x25, 0x54), RGBColor(0xE8, 0x8A, 0x0C), RGBColor(0x1E, 0x8E, 0x7E), RGBColor(0x6B, 0x4C, 0x9A)
INK, GREY, PALE = RGBColor(0x22, 0x22, 0x22), RGBColor(0x66, 0x66, 0x66), RGBColor(0xF3, 0xF4, 0xF8)
WHITE, CODEBG = RGBColor(255, 255, 255), RGBColor(0x1E, 0x1E, 0x2E)
TINT = {NAVY: RGBColor(0xE4, 0xE7, 0xF5), ORANGE: RGBColor(0xFD, 0xF0, 0xDC), TEAL: RGBColor(0xDD, 0xF1, 0xEE), PURPLE: RGBColor(0xEC, 0xE6, 0xF5)}
FONT, MONO = "Arial", "Consolas"


def clear(slide, keep_title=True):
    """Remove every shape except the title and the slide-number items; drop the pictures' relationships."""
    for sh in list(slide.shapes):
        if sh.is_placeholder or (sh.has_text_frame and sh.text_frame.text.strip().isdigit() and sh.left > Inches(9)):
            continue
        for blip in sh._element.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid:
                slide.part.drop_rel(rid)
        sh._element.getparent().remove(sh._element)


def text(slide, x, y, w, h, paras, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE, anchor=MSO_ANCHOR.TOP, margin=0.06, radius=None):
    """paras: list of paragraphs; a paragraph is a str or a list of runs (str | (str, dict(size, bold, color, mono, italic))) plus an optional dict at index 0 for paragraph options."""
    sp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sp.adjustments[0] = radius
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(1)
    sp.shadow.inherit = False
    tf = sp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    first = True
    for para in paras:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        opts = {}
        runs = para if isinstance(para, list) else [para]
        if runs and isinstance(runs[0], dict):
            opts, runs = runs[0], runs[1:]
        p.alignment = opts.get("align", PP_ALIGN.LEFT)
        if "space" in opts:
            p.space_before = Pt(opts["space"])
        for r in runs:
            s, o = (r, {}) if isinstance(r, str) else r
            run = p.add_run()
            run.text = s
            f = run.font
            f.name = MONO if o.get("mono") else FONT
            f.size = Pt(o.get("size", opts.get("size", 11)))
            f.bold = o.get("bold", opts.get("bold", False))
            f.italic = o.get("italic", False)
            f.color.rgb = o.get("color", opts.get("color", INK))
    return sp


def arrow(slide, x1, y1, x2, y2, color=GREY, dashed=False, width=1.75):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    if dashed:
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    return c


def retitle(slide, s):
    for sh in slide.shapes:
        if sh.is_placeholder and sh.has_text_frame and sh.text_frame.text.strip() and not sh.text_frame.text.strip().startswith("\u2039"):
            r = sh.text_frame.paragraphs[0].runs
            r[0].text = s
            for extra in r[1:]:
                extra.text = ""
            return


def card(slide, x, y, w, h, color, title, body_paras, title_h=0.3):
    text(slide, x, y, w, title_h, [[{"size": 11, "bold": True, "color": WHITE}, title]], fill=color, anchor=MSO_ANCHOR.MIDDLE, margin=0.1)
    return text(slide, x, y + title_h, w, h - title_h, body_paras, fill=TINT[color], margin=0.1)


B = lambda s, **o: (s, {"bold": True, **o})
C = lambda s, **o: (s, {"mono": True, "color": NAVY, **o})


def code(slide, x, y, w, h, lines, size=8):
    return text(slide, x, y, w, h, [[{"size": size}, (ln, {"mono": True, "size": size, "color": RGBColor(0xE8, 0xE8, 0xF0)})] for ln in lines], fill=CODEBG, margin=0.1)


prs = Presentation(SRC)
S = list(prs.slides)

# ------------------------------------------------------------------ slide 7: the problem
s = S[6]
pic = next(sh for sh in s.shapes if sh.shape_type == 13)                  # the abstraction-level picture is kept (functional -> concrete)
keep = (pic.left, pic.top, pic.width, pic.height)
clear(s)
retitle(s, "Postdoc : générateur de scénarios urbains")
text(s, 0.27, 0.58, 9.4, 0.75, [[
    {"size": 14}, "Comment générer, à partir d’une ", B("zone OpenStreetMap"), " et d’une ", B("description en texte"),
    ", des ", B("scénarios guidés pour un piéton humain"), ", ", B("vérifiés"), " sur la carte et ", B("jouables en réalité virtuelle"), " ?"]])
# abstraction ladder from the old slide (functional -> abstract -> logical -> concrete)
img_src = [sh for sh in S[6].part.package.iter_parts() if False]
prs_old = Presentation(SRC)
old = next(sh for sh in prs_old.slides[6].shapes if sh.shape_type == 13)
tmp = HERE / "_ladder.png"
tmp.write_bytes(old.image.blob)
s.shapes.add_picture(str(tmp), Inches(0.35), Inches(1.5), height=Inches(3.45))
text(s, 0.3, 4.98, 4.3, 0.25, [[{"size": 8, "color": GREY}, ("Niveaux d’abstraction d’un scénario : fonctionnel → concret (Menzel et al., 2018)", {"italic": True})]])
cx, cw = 4.85, 4.85
card(s, cx, 1.45, cw, 1.05, NAVY, "Entrée → sortie", [[{"size": 10}, B("Zone OSM + texte libre"), " → fichier ", B("OpenSCENARIO"), " + carte ", B("OpenDRIVE"),
     ", joué dans un ", B("joueur WebXR"), " où l’humain est le piéton"]])
card(s, cx, 2.6, cw, 1.3, ORANGE, "Idée clé", [[{"size": 10}, "Chaque tâche est une ", B("formule vérifiable"), " : but + règles de sécurité + délai, dans un ",
     B("langage de spécification typé"), " (marges numériques en m, °, m/s). Le LLM l’écrit comme ", B("donnée"), " ; un validateur la contrôle sur la vraie carte."]])
card(s, cx, 4.0, cw, 1.0, TEAL, "Évaluation", [[{"size": 10}, "2 cartes réelles (Munich, Paris), 50 requêtes, 7 types de scénarios ; LLM local ", B("Qwen3.5-4B"),
     " (aucun service cloud) ; étude de notation humaine prévue"]])

# ------------------------------------------------------------------ slide 8: architecture
s = S[7]
clear(s)
retitle(s, "Postdoc : architecture du pipeline de génération")
text(s, 0.27, 0.55, 9.4, 0.4, [[{"size": 11, "color": GREY}, "Un LLM local écrit une ", B("spécification de tâches"), " ; le système la vérifie sur la carte avant de construire et de jouer le scénario."]])
y1, h1 = 1.05, 0.95
text(s, 0.3, y1, 1.6, h1, [[{"size": 10, "align": PP_ALIGN.CENTER}, B("Entrées")], [{"size": 9, "align": PP_ALIGN.CENTER}, "zone OSM"], [{"size": 9, "align": PP_ALIGN.CENTER}, "+ requête en texte"]],
     fill=PALE, line=GREY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 2.3, y1, 2.3, h1, [[{"size": 10}, B("Modèle de carte"), " (repère métrique)"], [{"size": 8.5}, "routes, trottoirs, passages piétons, feux, mobilier, bâtiments ; export OpenDRIVE"]],
     fill=TINT[NAVY], line=NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 5.0, y1, 4.7, h1, [[{"size": 10}, B("Agent LLM local"), " (Qwen3.5-4B, llama.cpp)"],
     [{"size": 8.5}, "boucle d’appels d’outils ; premier message ancré : ids réels de la carte, exemple de référence ; 16 à 22 étapes max"]],
     fill=TINT[ORANGE], line=ORANGE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
arrow(s, 1.9, y1 + h1 / 2, 2.3, y1 + h1 / 2)
arrow(s, 4.6, y1 + h1 / 2, 5.0, y1 + h1 / 2)
y2, h2 = 2.8, 1.5
text(s, 6.9, y2, 2.8, h2, [[{"size": 10}, B("A · Spécification"), " (JSON)"],
     [{"size": 8.5}, "jamais exécutée ; syntaxe, types, références à la carte, faisabilité ; contrôles d’ancrage (couloir, surface, intention)"]],
     fill=TINT[PURPLE], line=PURPLE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 3.7, y2, 2.8, h2, [[{"size": 10}, B("B · Script du monde"), " (bac à sable)"],
     [{"size": 8.5}, "utilisateur, véhicules, feux ; ", ("scenario.apply_spec(SPEC)", {"mono": True, "size": 8}), " ; validateur de carte + marcheur nominal (marges)"]],
     fill=TINT[PURPLE], line=PURPLE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.3, y2, 3.0, h2, [[{"size": 10}, B("Sortie")], [{"size": 8.5}, ("scenario.xosc", {"mono": True, "size": 8}), " : chaque tâche = ", ("<VRTask><Spec>", {"mono": True, "size": 8}), " (formules)"],
     [{"size": 8.5}, ("map.xodr", {"mono": True, "size": 8}), " : réseau routier OpenDRIVE"]],
     fill=TINT[TEAL], line=TEAL, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE)
arrow(s, 8.3, y1 + h1, 8.3, y2)                                  # agent -> A
arrow(s, 6.9, y2 + h2 / 2, 6.5, y2 + h2 / 2)                     # A -> B
arrow(s, 3.7, y2 + h2 / 2, 3.3, y2 + h2 / 2)                     # B -> output
arrow(s, 5.2, y2, 5.2, y1 + h1, color=ORANGE, dashed=True)       # validator errors -> agent
text(s, 5.3, 2.12, 1.45, 0.55, [[{"size": 8, "color": ORANGE}, B("erreurs du validateur"), " → agent (≤ 6 essais)"]])
arrow(s, 9.2, y2, 9.2, y1 + h1, color=ORANGE, dashed=True)
text(s, 7.6, 2.3, 1.55, 0.4, [[{"size": 8, "color": ORANGE, "align": PP_ALIGN.RIGHT}, "spécification refusée"]])
text(s, 0.3, 4.5, 9.4, 0.62, [[{"size": 10}, B("Joueur WebXR / première personne (three.js) : "), "lit les ", ("<Spec>", {"mono": True, "size": 9}),
     ", échantillonne la pose réelle du participant à 10 Hz et évalue les formules (même sémantique en Python et en TypeScript) → succès / échec + marges numériques"]],
     fill=TINT[TEAL], line=TEAL, shape=MSO_SHAPE.ROUNDED_RECTANGLE, anchor=MSO_ANCHOR.MIDDLE, margin=0.12)
arrow(s, 1.8, y2 + h2, 1.8, 4.5)
text(s, 0.3, 5.14, 8.0, 0.25, [[{"size": 8, "color": GREY}, ("Si l’agent échoue : réparation déterministe « assistée » (reportée séparément des résultats du modèle seul).", {"italic": True})]])

# ------------------------------------------------------------------ slide 9: L0 / L1 / L2
s = S[8]
clear(s)
retitle(s, "Postdoc : niveaux de génération L0, L1, L2")
text(s, 0.27, 0.55, 9.4, 0.4, [[{"size": 11, "color": GREY}, "Qu’est-ce que le modèle écrit ? Même carte, mêmes outils, même validateur : seule la ", B("forme de la sortie"), " change."]])
cy, ch, cw = 1.0, 3.45, 3.05
cols = [
    (NAVY, "L0 · script Python", ["Le modèle adapte un script de référence", "Appelle des aides (", "pas de spécification explicite : la tâche est du code"],
     ['task = scenario.cross(cid, "start",', '  "Check the traffic, then cross",', '  name="cross_with_traffic",', '  avoid=["Car1"], timeout=60)']),
    (ORANGE, "L1 · spécification + monde", ["Étape A : spécification JSON, assemblée depuis la bibliothèque (reach, cross, wait_for_green, obey_signal, collision_free…)", "Étape B : script du monde, puis scenario.apply_spec(SPEC)"],
     ['{"op":"call","name":"cross",', ' "args":{"far_zone":{', '  "kind":"crossing_side",', '  "id":"crossing_41",', '  "side":"end","r":2}}}']),
    (PURPLE, "L2 · + définitions propres", ["Comme L1, et le modèle peut écrire ses propres définitions (defs) quand la bibliothèque ne suffit pas", "Définitions paramétrées, sans récursion ; vérifiées comme le reste"],
     ['"defs":{"safe_cross":{', ' "params":["c","sig"],', ' "body":{"op":"and","args":[', '  cross(far_zone=c),', '  obey_signal(c, sig)]}}}']),
]
for k, (colr, title, bullets, snippet) in enumerate(cols):
    x = 0.3 + k * (cw + 0.12)
    text(s, x, cy, cw, 0.3, [[{"size": 11, "bold": True, "color": WHITE}, title]], fill=colr, anchor=MSO_ANCHOR.MIDDLE, margin=0.1)
    if k == 0:
        bl = [[{"size": 10.5}, "• Le modèle adapte un ", B("script Python de référence")], [{"size": 10.5, "space": 3}, "• Il appelle des aides : ", C("go_to", size=9), ", ", C("cross", size=9), ", ", C("follow_path", size=9)],
              [{"size": 10.5, "space": 3}, "• Pas de spécification explicite : la tâche est ", B("du code")]]
    elif k == 1:
        bl = [[{"size": 10.5}, B("Étape A"), " : spécification JSON assemblée depuis la ", B("bibliothèque"), " (", C("reach", size=9), ", ", C("cross", size=9), ", ", C("wait_for_green", size=9), ", ", C("obey_signal", size=9), ", ", C("collision_free", size=9), "…)"],
              [{"size": 10.5, "space": 3}, B("Étape B"), " : script du monde, puis ", C("scenario.apply_spec(SPEC)", size=9)]]
    else:
        bl = [[{"size": 10.5}, "• Comme L1, ", B("+ définitions propres"), " (", C("defs", size=9), ") quand la bibliothèque ne suffit pas"],
              [{"size": 10.5, "space": 3}, "• Définitions paramétrées, sans récursion, vérifiées comme le reste"]]
    text(s, x, cy + 0.3, cw, 1.6, bl, fill=TINT[colr], margin=0.1)
    code(s, x, cy + 1.9, cw, 1.5, snippet, size=9.5)
text(s, 0.3, 4.55, 9.4, 0.7, [[{"size": 10}, B("Taux d’acceptation sans aide"), " (100 exécutions par niveau, Munich + Paris) : ", B("L0 62 %", color=NAVY), "  ·  ", B("L1 71 %", color=ORANGE), "  ·  ", B("L2 68 %", color=PURPLE),
     " — écarts non significatifs (tests de signe appariés, p ≥ 0,28). Le niveau « assisté » répare 26 exécutions de plus en L1 et en L2."],
     [{"size": 9, "color": GREY, "space": 2}, ("Valeur de L1/L2 : les erreurs portent sur des données (spécification) vérifiables avant d’exécuter du code, et la tâche est une formule que le joueur sait surveiller.", {"italic": True})]],
     fill=PALE, line=GREY, anchor=MSO_ANCHOR.MIDDLE, margin=0.12)

# ------------------------------------------------------------------ slide 10: a generated example
s = S[9]
clear(s)
retitle(s, "Postdoc : exemple de scénario généré")
text(s, 0.27, 0.55, 9.4, 0.5, [[{"size": 11}, B("Requête : "), ("« Wait for the pedestrian light to turn green, then cross the road. »", {"italic": True}),
     ("   Munich · niveau L2 · Qwen3.5-4B · tâche 2 sur 2", {"size": 9, "color": GREY})]])
text(s, 0.3, 1.05, 4.3, 0.28, [[{"size": 10, "bold": True, "color": WHITE}, "① Spécification écrite par le LLM (JSON)"]], fill=PURPLE, anchor=MSO_ANCHOR.MIDDLE, margin=0.1)
code(s, 0.3, 1.33, 4.3, 2.55, [
    '{"name": "cross",',
    ' "instruction": "Cross the road.",',
    ' "goal": {"op": "call", "name": "cross",',
    '   "args": {"far_zone": {',
    '     "kind": "crossing_side",',
    '     "id": "crossing_41",',
    '     "side": "end", "r": 2}}},',
    ' "safety": [{"op": "call",',
    '   "name": "obey_signal",',
    '   "args": {"zone": {"kind": "crossing",',
    '                     "id": "crossing_41"},',
    '            "signal": "signal_52"}}]}'], size=9)
text(s, 4.62, 2.5, 0.5, 0.3, [[{"size": 10, "align": PP_ALIGN.CENTER, "color": GREY}, B("→")]])
text(s, 5.1, 1.05, 4.6, 0.28, [[{"size": 10, "bold": True, "color": WHITE}, "② OpenSCENARIO généré (extrait de scenario.xosc)"]], fill=TEAL, anchor=MSO_ANCHOR.MIDDLE, margin=0.1)
code(s, 5.1, 1.33, 4.6, 2.55, [
    '<VRTask id="2" name="cross" category="ptp_env">',
    '  <Instructions><Text lang="en">Cross the road.',
    '  <Spec origin="spec">',
    '    <Goal><F op="eventually" start="0">',
    '      <F op="in_zone">',
    '        <Zone kind="disc" x="206.66" y="115.46" r="2"/>',
    '    <Safety>',
    '      <F op="always" label="crossed on red">',
    '        <F op="implies">',
    '          <F op="and">',
    '            <F op="in_zone"><Zone kind="rect" … /></F>',
    '            <F op="prev"><F op="not"> in_zone … </F></F>',
    '          </F>',
    '          <F op="signal_is" signal="signal_52"',
    '                            state="green"/>'], size=8)
text(s, 0.3, 4.1, 9.4, 1.05, [
    [{"size": 10.5}, B("Tâche 1 "), "(même requête) : ", C("wait_for_green(crossing_41, signal_52)", size=8.5), " → ", C("until( in_zone(trottoir), signal_52 = vert )", size=8.5)],
    [{"size": 9.5, "space": 3}, B("Validé : "), "ids de carte réels, feu 15 s vert / 20 s rouge, marcheur nominal (marges de but et de règle)."],
    [{"size": 9.5, "space": 3}, B("Joué : "), "le joueur évalue « traversée au rouge » = ", C("always( entrer dans le passage ⇒ feu vert )", size=8.5), " sur la pose réelle → marge en mètres."]],
    fill=PALE, line=GREY, anchor=MSO_ANCHOR.MIDDLE, margin=0.12)

prs.save(DST)
print("saved", DST)
