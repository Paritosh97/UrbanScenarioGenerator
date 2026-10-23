import type { Pt, SceneMap, Surface } from './types';
import { dist, distToPolyline, pointInPolygon, projectToPolyline, toLocal } from './geometry';

export const WALKABLE = new Set<Surface>(['crosswalk', 'sidewalk', 'path', 'ground']);
export const PED_INFRA = new Set<Surface>(['crosswalk', 'sidewalk', 'path']);

/** Surface classes a SurfaceAdherenceFailureCondition name allows. */
export const SURFACE_SETS: Record<string, Set<Surface>> = {
  walkable: WALKABLE,
  pedestrian_infra: PED_INFRA,
  crosswalk: new Set<Surface>(['crosswalk']),
  road: new Set<Surface>(['road', 'crosswalk']),
  sidewalk: new Set<Surface>(['sidewalk']),
  path: new Set<Surface>(['path']),
  ground: new Set<Surface>(['ground']),
};

function bbox(pts: Pt[]): number[] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1];
}

const inBox = (p: Pt, bb: number[]) => bb[0] <= p[0] && p[0] <= bb[2] && bb[1] <= p[1] && p[1] <= bb[3];

/**
 * Port of Python `MapModel.surface_at`, kept equivalent step by step. A parity test compares
 * both implementations on thousands of sampled points.
 */
export class SurfaceClassifier {
  private buildings: { pts: Pt[]; bb: number[] }[];
  private water: { pts: Pt[]; bb: number[] }[];

  constructor(private map: SceneMap) {
    this.buildings = map.buildings.map((b) => ({ pts: b.pts, bb: bbox(b.pts) }));
    this.water = map.areas.filter((a) => a.atype === 'water').map((a) => ({ pts: a.pts, bb: bbox(a.pts) }));
  }

  at(p: Pt): Surface {
    const m = this.map;
    for (const c of m.crossings) {
      const q = toLocal(p, c.pos, c.heading);
      if (Math.abs(q[0]) <= c.length / 2 && Math.abs(q[1]) <= c.width / 2) return 'crosswalk';
    }
    for (const b of this.buildings) if (inBox(p, b.bb) && pointInPolygon(b.pts, p)) return 'building';
    for (const a of this.water) if (inBox(p, a.bb) && pointInPolygon(a.pts, p)) return 'water';
    let onSidewalk = false;
    for (const r of m.roads) {
      const { t } = projectToPolyline(r.pts, p);
      const half = r.width / 2;
      if (Math.abs(t) <= half) return 'road';
      const w = t > 0 ? r.sidewalk_left : r.sidewalk_right;
      if (w > 0 && Math.abs(t) <= half + w) onSidewalk = true;
    }
    for (const j of m.junctions) if (dist(p, j.pos) <= j.radius * 0.8) return 'road';
    if (onSidewalk) return 'sidewalk';
    for (const pa of m.paths) if (distToPolyline(pa.pts, p) <= pa.width / 2) return 'path';
    return 'ground';
  }
}
