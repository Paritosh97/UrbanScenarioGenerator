/**
 * Task specification formulas (see the Python package `usg.spec`). A formula is data: atoms + temporal combinators.
 * The scenario file carries them inside `<VRTask><Spec>` as `<F op="...">` elements (`formula.to_xml` in Python).
 */
import type { Pt } from './types';

export type Zone =
  | { kind: 'disc'; x: number; y: number; r: number }
  | { kind: 'rect'; cx: number; cy: number; h: number; hl: number; hw: number }
  | { kind: 'entity'; name: string; r: number };

export interface FNode {
  op: string;
  arg?: FNode; a?: FNode; b?: FNode; left?: FNode; right?: FNode; args?: FNode[];
  start?: number; end?: number | null; init?: boolean;
  zone?: Zone; surface?: string; path?: Pt[]; tol?: number; entity?: string; d?: number; point?: Pt;
  angle?: number; v?: number; signal?: string; state?: string; name?: string; label?: string;
}

export interface TaskSpec { origin: string; goal: FNode; safety: FNode[] }

const num = (v: string | null, d = 0) => (v == null || v === '' ? d : parseFloat(v));

export function parseFormula(e: Element): FNode {
  const op = e.getAttribute('op') ?? '';
  const n: FNode = { op };
  for (const k of ['surface', 'entity', 'signal', 'state', 'name', 'label'] as const) {
    const v = e.getAttribute(k);
    if (v != null) n[k] = v;
  }
  for (const k of ['tol', 'd', 'angle', 'v', 'start'] as const) {
    const v = e.getAttribute(k);
    if (v != null) n[k] = parseFloat(v);
  }
  if (e.getAttribute('end') != null) n.end = parseFloat(e.getAttribute('end')!);
  if (op === 'eventually' || op === 'always' || op === 'until') {
    n.start = n.start ?? 0;
    n.end = n.end ?? null;
  }
  if (op === 'prev') n.init = e.getAttribute('init') !== 'false';
  if (op === 'look_at' && e.getAttribute('px') != null) n.point = [num(e.getAttribute('px')), num(e.getAttribute('py'))];
  const kids = Array.from(e.children).filter((c) => c.tagName === 'F');
  if (op === 'near_path') n.path = Array.from(e.children).filter((c) => c.tagName === 'P').map((p) => [num(p.getAttribute('x')), num(p.getAttribute('y'))] as Pt);
  if (op === 'in_zone') {
    const z = Array.from(e.children).find((c) => c.tagName === 'Zone')!;
    const kind = z.getAttribute('kind');
    if (kind === 'disc') n.zone = { kind: 'disc', x: num(z.getAttribute('x')), y: num(z.getAttribute('y')), r: num(z.getAttribute('r')) };
    else if (kind === 'rect') n.zone = { kind: 'rect', cx: num(z.getAttribute('cx')), cy: num(z.getAttribute('cy')), h: num(z.getAttribute('h')), hl: num(z.getAttribute('hl')), hw: num(z.getAttribute('hw')) };
    else n.zone = { kind: 'entity', name: z.getAttribute('name') ?? '', r: num(z.getAttribute('r')) };
  }
  if (op === 'not' || op === 'eventually' || op === 'always' || op === 'prev') n.arg = parseFormula(kids[0]);
  else if (op === 'implies') { n.a = parseFormula(kids[0]); n.b = parseFormula(kids[1]); }
  else if (op === 'until') { n.left = parseFormula(kids[0]); n.right = parseFormula(kids[1]); }
  else if (op === 'and' || op === 'or') n.args = kids.map(parseFormula);
  return n;
}

export function* walk(n: FNode): Generator<FNode> {
  yield n;
  for (const k of ['arg', 'a', 'b', 'left', 'right'] as const) if (n[k]) yield* walk(n[k]!);
  if (n.args) for (const c of n.args) yield* walk(c);
}

/** Names the monitor must record for a task: entities, signals, events referenced by its formulas. */
export function references(roots: FNode[]): { entities: Set<string>; signals: Set<string>; events: Set<string> } {
  const r = { entities: new Set<string>(), signals: new Set<string>(), events: new Set<string>() };
  for (const root of roots) {
    for (const n of walk(root)) {
      if ((n.op === 'dist_le' || n.op === 'dist_ge') && n.entity) r.entities.add(n.entity);
      if (n.op === 'look_at' && n.entity) r.entities.add(n.entity);
      if (n.op === 'in_zone' && n.zone?.kind === 'entity') r.entities.add(n.zone.name);
      if (n.op === 'signal_is' && n.signal) r.signals.add(n.signal);
      if (n.op === 'event' && n.name) r.events.add(n.name);
    }
  }
  return r;
}

/** First zone centre of a goal, used by the HUD to show "distance to the next place". */
export function firstZoneCentre(goal: FNode): Pt | null {
  for (const n of walk(goal)) {
    if (n.op === 'in_zone' && n.zone) {
      if (n.zone.kind === 'disc') return [n.zone.x, n.zone.y];
      if (n.zone.kind === 'rect') return [n.zone.cx, n.zone.cy];
    }
  }
  return null;
}

export function describe(n: FNode): string {
  switch (n.op) {
    case 'true': return 'true';
    case 'in_zone': return n.zone!.kind === 'disc' ? `in_zone(disc(${n.zone!.x.toFixed(1)},${n.zone!.y.toFixed(1)};r=${n.zone!.r}))` : 'in_zone(zone)';
    case 'on_surface': return `on_surface(${n.surface})`;
    case 'near_path': return `near_path(tol=${n.tol})`;
    case 'dist_le': return `dist(${n.entity})<=${n.d}`;
    case 'dist_ge': return `dist(${n.entity})>=${n.d}`;
    case 'look_at': return `look_at(${n.entity ?? 'point'},${n.angle}deg)`;
    case 'speed_le': return `speed<=${n.v}`;
    case 'speed_ge': return `speed>=${n.v}`;
    case 'signal_is': return `${n.signal}=${n.state}`;
    case 'event': return `event(${n.name})`;
    case 'not': return `not ${describe(n.arg!)}`;
    case 'and': case 'or': return `(${n.args!.map(describe).join(` ${n.op} `)})`;
    case 'implies': return `(${describe(n.a!)} -> ${describe(n.b!)})`;
    case 'prev': return `prev(${describe(n.arg!)})`;
    case 'eventually': case 'always': return `${n.op}(${describe(n.arg!)})`;
    case 'until': return `(${describe(n.left!)} until ${describe(n.right!)})`;
    default: return n.op;
  }
}
