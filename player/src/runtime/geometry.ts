import type { Pt } from './types';

export const dist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);

export function wrapPi(a: number): number {
  const t = (a + Math.PI) % (2 * Math.PI);
  return (t < 0 ? t + 2 * Math.PI : t) - Math.PI;
}

/** Closest point on a polyline. t > 0 means the point is LEFT of the travel direction. */
export function projectToPolyline(pts: Pt[], p: Pt): { s: number; t: number; closest: Pt; heading: number } {
  let best = { d: Infinity, s: 0, t: 0, closest: pts[0], heading: 0 };
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const l2 = dx * dx + dy * dy;
    const seg = Math.sqrt(l2);
    const f = l2 < 1e-12 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
    const c: Pt = [a[0] + dx * f, a[1] + dy * f];
    const d = dist(c, p);
    if (d < best.d) {
      const cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0]);
      best = { d, s: acc + seg * f, t: cross >= 0 ? d : -d, closest: c, heading: Math.atan2(dy, dx) };
    }
    acc += seg;
  }
  return { s: best.s, t: best.t, closest: best.closest, heading: best.heading };
}

export const distToPolyline = (pts: Pt[], p: Pt) => Math.abs(projectToPolyline(pts, p).t);

export function polylineLength(pts: Pt[]): number {
  let s = 0;
  for (let i = 0; i < pts.length - 1; i++) s += dist(pts[i], pts[i + 1]);
  return s;
}

export function pointInPolygon(poly: Pt[], p: Pt): boolean {
  const [x, y] = p;
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-18) + xi) inside = !inside;
  }
  return inside;
}

/** Express p in a frame at `origin` rotated by `hdg`: [along heading, left of heading]. */
export function toLocal(p: Pt, origin: Pt, hdg: number): Pt {
  const dx = p[0] - origin[0], dy = p[1] - origin[1];
  const c = Math.cos(hdg), s = Math.sin(hdg);
  return [dx * c + dy * s, -dx * s + dy * c];
}

/** Distance from a point to an oriented rectangle (0 if inside). */
export function distToObb(p: Pt, center: Pt, hdg: number, length: number, width: number): number {
  const [lx, ly] = toLocal(p, center, hdg);
  const dx = Math.max(Math.abs(lx) - length / 2, 0);
  const dy = Math.max(Math.abs(ly) - width / 2, 0);
  return Math.hypot(dx, dy);
}

/** Point and heading at arc length s along a polyline (clamped). */
export function pointAt(pts: Pt[], s: number): { p: Pt; h: number } {
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const seg = dist(pts[i], pts[i + 1]);
    if (s <= acc + seg || i === pts.length - 2) {
      const f = seg < 1e-9 ? 0 : Math.max(0, Math.min(1, (s - acc) / seg));
      const a = pts[i], b = pts[i + 1];
      return { p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f], h: Math.atan2(b[1] - a[1], b[0] - a[0]) };
    }
    acc += seg;
  }
  return { p: pts[pts.length - 1], h: 0 };
}

/** Offset a polyline to the LEFT by d (negative = right) with clamped mitres. Port of geo.offset_polyline. */
export function offsetPolyline(pts: Pt[], d: number, miterLimit = 2): Pt[] {
  const n = pts.length;
  if (n < 2) return pts.slice();
  const normals: Pt[] = [];
  for (let i = 0; i < n - 1; i++) {
    const h = Math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0]);
    normals.push([-Math.sin(h), Math.cos(h)]);
  }
  return pts.map((p, i) => {
    let nx: number, ny: number, k = 1;
    if (i === 0) [nx, ny] = normals[0];
    else if (i === n - 1) [nx, ny] = normals[n - 2];
    else {
      const [ax, ay] = normals[i - 1], [bx, by] = normals[i];
      const mx = ax + bx, my = ay + by, ml = Math.hypot(mx, my);
      if (ml < 1e-9) { nx = ax; ny = ay; } else {
        nx = mx / ml; ny = my / ml;
        k = Math.min(miterLimit, 1 / Math.max(1e-3, nx * ax + ny * ay));
      }
    }
    return [p[0] + nx * d * k, p[1] + ny * d * k] as Pt;
  });
}

/** Sub-polyline between arc lengths s0 and s1. */
export function subPolyline(pts: Pt[], s0: number, s1: number): Pt[] {
  const total = polylineLength(pts);
  s0 = Math.max(0, s0); s1 = Math.min(total, s1);
  if (s1 <= s0) return [pointAt(pts, s0).p];
  const out: Pt[] = [pointAt(pts, s0).p];
  let acc = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    acc += dist(pts[i - 1], pts[i]);
    if (acc > s0 && acc < s1) out.push(pts[i]);
  }
  out.push(pointAt(pts, s1).p);
  return out;
}

/** Closed polygon covering the band between offsets d0 and d1 of a polyline. */
export function bandPolygon(pts: Pt[], d0: number, d1: number): Pt[] {
  const a = offsetPolyline(pts, d0), b = offsetPolyline(pts, d1);
  return [...a, ...b.reverse()];
}
