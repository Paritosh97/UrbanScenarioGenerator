/**
 * Interval robustness of a specification over a trajectory prefix: a line-for-line port of `usg/spec/monitor.py`.
 *
 *   lo >= 0  the formula is already satisfied whatever happens next
 *   hi <  0  the formula is already violated whatever happens next
 *
 * `tests/spec.test.ts` compares this implementation with the Python reference on randomised formulas and traces.
 */
import type { Pt } from './types';
import type { FNode } from './formula';
import { dist, distToPolyline, toLocal, wrapPi } from './geometry';
import { SURFACE_SETS } from './surface';

export const BIG = 1.0e9;

export interface Sample {
  x: number; y: number;
  gaze: number;                                   // radians, 0 = east, counter-clockwise
  speed: number;                                  // m/s
  surface: string;
  ents: Record<string, [number, number, number, number, number]>;   // name -> [centre x, centre y, heading, length, width]
  signals: Record<string, string>;
  events: Set<string>;
}

export function distToObbC(p: Pt, c: [number, number], h: number, l: number, w: number): number {
  const [lx, ly] = toLocal(p, c, h);
  return Math.hypot(Math.max(Math.abs(lx) - l / 2, 0), Math.max(Math.abs(ly) - w / 2, 0));
}

export function atomValue(n: FNode, s: Sample): number {
  const p: Pt = [s.x, s.y];
  switch (n.op) {
    case 'true': return BIG;
    case 'in_zone': {
      const z = n.zone!;
      if (z.kind === 'disc') return z.r - Math.hypot(s.x - z.x, s.y - z.y);
      if (z.kind === 'rect') {
        const [lx, ly] = toLocal(p, [z.cx, z.cy], z.h);
        return Math.min(z.hl - Math.abs(lx), z.hw - Math.abs(ly));
      }
      const e = s.ents[z.name];
      return e ? z.r - Math.hypot(s.x - e[0], s.y - e[1]) : -BIG;
    }
    case 'on_surface': return (SURFACE_SETS[n.surface!] as Set<string> | undefined)?.has(s.surface) ? 1 : -1;
    case 'near_path': return n.tol! - distToPolyline(n.path!, p);
    case 'dist_le': case 'dist_ge': {
      const e = s.ents[n.entity!];
      if (!e) return n.op === 'dist_le' ? -BIG : BIG;
      const d = distToObbC(p, [e[0], e[1]], e[2], e[3], e[4]);
      return n.op === 'dist_le' ? n.d! - d : d - n.d!;
    }
    case 'look_at': {
      let tx: number, ty: number;
      if (n.entity) {
        const e = s.ents[n.entity];
        if (!e) return -BIG;
        tx = e[0]; ty = e[1];
      } else [tx, ty] = n.point!;
      const err = Math.abs(wrapPi(s.gaze - Math.atan2(ty - s.y, tx - s.x))) * 180 / Math.PI;
      return n.angle! - err;
    }
    case 'speed_le': return n.v! - s.speed;
    case 'speed_ge': return s.speed - n.v!;
    case 'signal_is': return s.signals[n.signal!] === n.state ? 1 : -1;
    case 'event': return s.events.has(n.name!) ? 1 : -1;
  }
  throw new Error(`not an atom: ${n.op}`);
}

const ATOMS = new Set(['true', 'in_zone', 'on_surface', 'near_path', 'dist_le', 'dist_ge', 'look_at', 'speed_le', 'speed_ge', 'signal_is', 'event']);
type Pair = [number, number];

export class Monitor {
  private K: number;
  private memo = new WeakMap<FNode, Map<number, Pair>>();

  constructor(private s: Sample[], private dt = 0.1, private complete = false) { this.K = s.length - 1; }

  private window(n: FNode, k: number): { first: number; last: number; unknown: boolean } {
    const a = n.start ?? 0;
    const b = n.end ?? null;
    const ia = Math.ceil(a / this.dt - 1e-9);
    const ib = b === null ? null : Math.floor(b / this.dt + 1e-9);
    return {
      first: k + ia,
      last: ib === null ? this.K : Math.min(k + ib, this.K),
      unknown: !this.complete && (ib === null || k + ib > this.K),
    };
  }

  rho(n: FNode, k = 0): Pair {
    let m = this.memo.get(n);
    if (!m) { m = new Map(); this.memo.set(n, m); }
    let r = m.get(k);
    if (!r) { r = this.calc(n, k); m.set(k, r); }
    return r;
  }

  private calc(n: FNode, k: number): Pair {
    if (k > this.K) return this.complete ? [-BIG, -BIG] : [-BIG, BIG];
    if (ATOMS.has(n.op)) { const v = atomValue(n, this.s[k]); return [v, v]; }
    switch (n.op) {
      case 'not': { const [lo, hi] = this.rho(n.arg!, k); return [-hi, -lo]; }
      case 'and': {
        let lo = BIG, hi = BIG;
        for (const c of n.args!) { const r = this.rho(c, k); lo = Math.min(lo, r[0]); hi = Math.min(hi, r[1]); }
        return [lo, hi];
      }
      case 'or': {
        let lo = -BIG, hi = -BIG;
        for (const c of n.args!) { const r = this.rho(c, k); lo = Math.max(lo, r[0]); hi = Math.max(hi, r[1]); }
        return [lo, hi];
      }
      case 'implies': {
        const [alo, ahi] = this.rho(n.a!, k);
        const [blo, bhi] = this.rho(n.b!, k);
        return [Math.max(-ahi, blo), Math.max(-alo, bhi)];
      }
      case 'prev':
        if (k === 0) return (n.init ?? true) ? [BIG, BIG] : [-BIG, -BIG];
        return this.rho(n.arg!, k - 1);
      case 'eventually': case 'always': {
        const { first, last, unknown } = this.window(n, k);
        const ev = n.op === 'eventually';
        let lo = ev ? -BIG : BIG, hi = lo;
        for (let j = first; j <= last; j++) {
          const [l, h] = this.rho(n.arg!, j);
          if (ev) { lo = Math.max(lo, l); hi = Math.max(hi, h); } else { lo = Math.min(lo, l); hi = Math.min(hi, h); }
        }
        if (unknown) { if (ev) hi = BIG; else lo = -BIG; }
        return [lo, hi];
      }
      case 'until': {
        const { first, last, unknown } = this.window(n, k);
        let loBest = -BIG, hiBest = -BIG, ll = BIG, lh = BIG;
        for (let j = k; j <= last; j++) {
          if (j >= first) {
            const [rlo, rhi] = this.rho(n.right!, j);
            loBest = Math.max(loBest, Math.min(rlo, ll));
            hiBest = Math.max(hiBest, Math.min(rhi, lh));
          }
          const [l, h] = this.rho(n.left!, j);
          ll = Math.min(ll, l); lh = Math.min(lh, h);
        }
        if (unknown) hiBest = Math.max(hiBest, lh);
        return [loBest, hiBest];
      }
    }
    throw new Error(`unknown op ${n.op}`);
  }
}

export interface GoalStatus {
  status: 'running' | 'success' | 'failed';
  /** which formula decided it: 'safety' (index) or 'goal' */
  by: 'safety' | 'goal' | null; index: number;
  goal: Pair; safety: Pair[];
}

export function goalStatus(goal: FNode, safety: FNode[], samples: Sample[], dt = 0.1, complete = false): GoalStatus {
  const m = new Monitor(samples, dt, complete);
  const g = m.rho(goal, 0);
  const sf = safety.map((f) => m.rho(f, 0));
  const bad = sf.findIndex(([, hi]) => hi < 0);
  if (bad >= 0) return { status: 'failed', by: 'safety', index: bad, goal: g, safety: sf };
  if (g[0] >= 0) return { status: 'success', by: 'goal', index: -1, goal: g, safety: sf };
  if (g[1] < 0) return { status: 'failed', by: 'goal', index: -1, goal: g, safety: sf };
  return { status: 'running', by: null, index: -1, goal: g, safety: sf };
}
void dist;
