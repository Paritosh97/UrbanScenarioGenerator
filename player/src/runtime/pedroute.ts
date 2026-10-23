import type { Pt, SceneMap } from './types';
import { dist } from './geometry';

export interface PedGraphData { nodes: Pt[]; edges: [number, number, string, string | null][] }

const CROSSING_PENALTY = 4.0;     // keep identical to Python pedgraph.CROSSING_PENALTY

export interface Route { waypoints: Pt[]; length: number; crossings: string[] }

/**
 * A* over the exported pedestrian graph (sidewalks, corners, crossings, paths).
 * Used for the optional guidance line and by the runtime tests; never to move the player.
 */
export class PedRouter {
  private adj: { to: number; w: number; kind: string; ref: string | null }[][];
  constructor(private nodes: Pt[], edges: PedGraphData['edges']) {
    this.adj = nodes.map(() => []);
    for (const [a, b, kind, ref] of edges) {
      const w = dist(nodes[a], nodes[b]);
      this.adj[a].push({ to: b, w, kind, ref });
      this.adj[b].push({ to: a, w, kind, ref });
    }
  }

  static fromMap(map: SceneMap): PedRouter | null {
    const g = (map as unknown as { ped_graph?: PedGraphData }).ped_graph;
    return g && g.nodes.length ? new PedRouter(g.nodes, g.edges) : null;
  }

  nearest(p: Pt): number {
    let best = 0, bd = Infinity;
    for (let i = 0; i < this.nodes.length; i++) { const d = dist(this.nodes[i], p); if (d < bd) { bd = d; best = i; } }
    return best;
  }

  route(a: Pt, b: Pt, avoid: Set<string> = new Set()): Route | null {
    const s = this.nearest(a), t = this.nearest(b);
    const gs = new Map<number, number>([[s, 0]]);
    const prev = new Map<number, { n: number; kind: string; ref: string | null }>();
    const open: [number, number][] = [[dist(this.nodes[s], this.nodes[t]), s]];
    const done = new Set<number>();
    while (open.length) {
      open.sort((x, y) => x[0] - y[0]);
      const [, n] = open.shift()!;
      if (done.has(n)) continue;
      done.add(n);
      if (n === t) break;
      for (const e of this.adj[n]) {
        if (e.kind === 'crossing' && e.ref && avoid.has(e.ref)) continue;
        const nd = gs.get(n)! + e.w + (e.kind === 'crossing' ? CROSSING_PENALTY : 0);
        if (nd < (gs.get(e.to) ?? Infinity)) {
          gs.set(e.to, nd);
          prev.set(e.to, { n, kind: e.kind, ref: e.ref });
          open.push([nd + dist(this.nodes[e.to], this.nodes[t]), e.to]);
        }
      }
    }
    if (!gs.has(t)) return null;
    const chain = [t];
    const crossings: string[] = [];
    for (let n = t; n !== s;) {
      const p = prev.get(n)!;
      if (p.kind === 'crossing' && p.ref) crossings.push(p.ref);
      chain.push(p.n);
      n = p.n;
    }
    chain.reverse(); crossings.reverse();
    const waypoints: Pt[] = [a, ...chain.map((i) => this.nodes[i]), b];
    let length = 0;
    for (let i = 0; i < waypoints.length - 1; i++) length += dist(waypoints[i], waypoints[i + 1]);
    return { waypoints, length, crossings };
  }
}
