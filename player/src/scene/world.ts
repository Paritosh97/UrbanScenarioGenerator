/**
 * Static 3D city from the scene map. Pure three.js (no React).
 * Axes: map (x east, y north) -> three (x, up, -y). Everything is generated from the SAME numbers the
 * Python validator used, so what you see is exactly what the scenario reasons about.
 */
import * as THREE from 'three';
import type { Pt, SceneMap } from '../runtime/types';
import { bandPolygon, pointAt, polylineLength, subPolyline } from '../runtime/geometry';
import { makeProp } from './props';

const COLORS = {
  ground: 0x879a78, park: 0x5f8f4e, water: 0x4a86b8, asphalt: 0x3b4048, sidewalk: 0xb9b6ae,
  path: 0xc9b48a, rail: 0x4a4440, marking: 0xf2f2f2, centre: 0xe8c230, barrier: 0x7b6e5a,
};
const PALETTE = [0xd9c7a5, 0xc9b79c, 0xb9a68a, 0xe0d5c0, 0xcfa890, 0xb7b9bd, 0xc4b19f];
const hash = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); };

function shapeFrom(pts: Pt[]): THREE.Shape {
  // shape coordinates are (x, y) of the MAP; geometry is rotated onto the XZ plane afterwards
  return new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)));
}

/** Flat polygon at height y. */
function flat(pts: Pt[], y: number, color: number): THREE.Mesh {
  const g = new THREE.ShapeGeometry(shapeFrom(pts));
  g.rotateX(-Math.PI / 2);
  g.translate(0, y, 0);
  return new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.95 }));
}

/** Extruded prism from y=0 up to `height`. */
function prism(pts: Pt[], height: number, color: number, base = 0): THREE.Mesh {
  const g = new THREE.ExtrudeGeometry(shapeFrom(pts), { depth: height, bevelEnabled: false });
  g.rotateX(-Math.PI / 2);
  g.translate(0, base, 0);
  return new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.9 }));
}

function ccw(pts: Pt[]): Pt[] {
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
  return a < 0 ? pts.slice().reverse() : pts;
}

export interface WorldHandles {
  group: THREE.Group;
  /** signal lamp materials keyed by signal name, recoloured every frame */
  signalLamps: Map<string, { red: THREE.MeshBasicMaterial; green: THREE.MeshBasicMaterial }>;
}

export function buildWorld(map: SceneMap, signalNames: string[] = []): WorldHandles {
  const g = new THREE.Group();
  const [x0, y0, x1, y1] = map.bounds;
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const radius = Math.hypot(x1 - x0, y1 - y0) / 2 + 40;

  const ground = new THREE.Mesh(new THREE.CircleGeometry(radius * 1.6, 48), new THREE.MeshStandardMaterial({ color: COLORS.ground, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; ground.position.set(cx, -0.02, -cy);
  g.add(ground);

  for (const a of map.areas) if (a.pts.length >= 3) g.add(flat(ccw(a.pts), a.atype === 'water' ? 0.0 : 0.01, a.atype === 'water' ? COLORS.water : COLORS.park));

  const dashes: { p: Pt; h: number }[] = [];
  for (const r of map.roads) {
    const L = polylineLength(r.pts);
    const tr = subPolyline(r.pts, r.trim_start, L - r.trim_end);
    if (tr.length < 2) continue;
    g.add(flat(ccw(bandPolygon(tr, r.width / 2, -r.width / 2)), 0.04, COLORS.asphalt));
    for (const [side, w] of [[1, r.sidewalk_left], [-1, r.sidewalk_right]] as const) {
      if (w <= 0) continue;
      const poly = ccw(side > 0 ? bandPolygon(tr, r.width / 2, r.width / 2 + w) : bandPolygon(tr, -r.width / 2, -r.width / 2 - w));
      g.add(prism(poly, 0.14, COLORS.sidewalk));
    }
    if (!r.oneway) {
      const len = polylineLength(tr);
      for (let s = 1; s < len - 2; s += 8) { const q = pointAt(tr, s + 1.5); dashes.push({ p: q.p, h: q.h }); }
    }
  }
  if (dashes.length) {
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(3, 0.01, 0.14), new THREE.MeshBasicMaterial({ color: COLORS.centre }), dashes.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler();
    dashes.forEach((d, i) => { e.set(0, d.h, 0); q.setFromEuler(e); m4.compose(new THREE.Vector3(d.p[0], 0.055, -d.p[1]), q, new THREE.Vector3(1, 1, 1)); im.setMatrixAt(i, m4); });
    g.add(im);
  }

  for (const j of map.junctions) {
    if (j.polygon.length >= 3) g.add(flat(ccw(j.polygon), 0.04, COLORS.asphalt));
    for (const c of j.corners) if (c.length >= 3) g.add(prism(ccw(c), 0.14, COLORS.sidewalk));
  }

  // crosswalk bars
  const bars: { p: Pt; h: number; w: number }[] = [];
  for (const c of map.crossings) {
    const n = Math.floor(c.length / 1.0);
    for (let i = 0; i < n; i++) {
      const u = -c.length / 2 + (i + 0.5) * (c.length / n);
      bars.push({ p: [c.pos[0] + Math.cos(c.heading) * u, c.pos[1] + Math.sin(c.heading) * u], h: c.heading, w: c.width });
    }
  }
  if (bars.length) {
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(0.5, 0.012, 1), new THREE.MeshBasicMaterial({ color: COLORS.marking }), bars.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler();
    bars.forEach((b, i) => {
      e.set(0, b.h, 0); q.setFromEuler(e);
      m4.compose(new THREE.Vector3(b.p[0], 0.06, -b.p[1]), q, new THREE.Vector3(1, 1, b.w * 0.92));
      im.setMatrixAt(i, m4);
    });
    g.add(im);
  }

  for (const p of map.paths) g.add(flat(ccw(bandPolygon(p.pts, p.width / 2, -p.width / 2)), 0.05, COLORS.path));
  for (const r of map.railways) g.add(flat(ccw(bandPolygon(r.pts, 1.2, -1.2)), 0.05, COLORS.rail));
  for (const b of map.barriers) g.add(prism(ccw(bandPolygon(b.pts, 0.08, -0.08)), b.height, COLORS.barrier));
  for (const b of map.buildings) if (b.pts.length >= 3) g.add(prism(ccw(b.pts), b.height, PALETTE[hash(b.id) % PALETTE.length]));

  for (const p of map.props) {
    const o = makeProp(p.ptype);
    o.position.set(p.pos[0], 0.14, -p.pos[1]);
    o.rotation.y = p.heading;
    g.add(o);
  }

  // signal heads at the end of each controlled crossing
  const lamps = new Map<string, { red: THREE.MeshBasicMaterial; green: THREE.MeshBasicMaterial }>();
  for (const name of signalNames) {
    const sg = map.signals.find((s) => s.id === name);
    const cr = sg?.crossing ? map.crossings.find((c) => c.id === sg.crossing) : map.crossings.find((c) => `${c.id}_ped` === name || c.signal_id === name);
    const pos: Pt | null = cr ? [cr.pos[0] + Math.cos(cr.heading) * (cr.length / 2 + 0.6), cr.pos[1] + Math.sin(cr.heading) * (cr.length / 2 + 0.6)] : sg ? sg.pos : null;
    if (!pos) continue;
    const head = makeSignalHead(lamps, name);
    head.position.set(pos[0], 0.14, -pos[1]);
    g.add(head);
  }
  return { group: g, signalLamps: lamps };
}

function makeSignalHead(lamps: WorldHandles['signalLamps'], name: string): THREE.Group {
  const grp = new THREE.Group();
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.6, 8), new THREE.MeshStandardMaterial({ color: 0x555a60 }));
  pole.position.y = 1.3;
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.62, 0.2), new THREE.MeshStandardMaterial({ color: 0x1a1c1f }));
  box.position.y = 2.45;
  const red = new THREE.MeshBasicMaterial({ color: 0x551111 });
  const green = new THREE.MeshBasicMaterial({ color: 0x114411 });
  const r = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 8), red); r.position.set(0, 2.6, 0.11);
  const gr = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 8), green); gr.position.set(0, 2.3, 0.11);
  grp.add(pole, box, r, gr);
  lamps.set(name, { red, green });
  return grp;
}

export function setSignalLamps(lamps: WorldHandles['signalLamps'], states: Map<string, string>): void {
  for (const [name, m] of lamps) {
    const s = states.get(name);
    m.red.color.setHex(s === 'red' ? 0xff3030 : 0x441010);
    m.green.color.setHex(s === 'green' ? 0x30ff60 : 0x104418);
  }
}
