import * as THREE from 'three';
import type { EntityDef, TaskDef } from '../runtime/xosc';
import type { Pt } from '../runtime/types';
import { offsetPolyline } from '../runtime/geometry';
import { walk, type Zone } from '../runtime/formula';

const VEHICLE_COLORS: Record<string, number> = {
  car_white: 0xe8e8ea, car_red: 0xc0332f, car_blue: 0x2f56b0, car_yellow: 0xe0b52c,
  van_red: 0xa83a30, bus_blue: 0x2a62b8, truck_yellow: 0xd9a21e,
};
const WALKER_COLORS: Record<string, number> = { ped_a: 0xd0623a, ped_b: 0x3a8fd0, ped_c: 0x7a4fb5 };

const std = (c: number, o?: Partial<THREE.MeshStandardMaterialParameters>) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7, ...o });

/**
 * Object whose origin is the entity reference point (rear axle for vehicles, feet for pedestrians),
 * +x forward. Orientation: rotation.y = heading (radians, ENU CCW from east).
 */
export function makeEntity(def: EntityDef): THREE.Object3D {
  const g = new THREE.Group();
  g.name = `entity:${def.name}`;
  if (def.role === 'vehicle') {
    const { length: l, width: w, height: h, cx } = def.bbox;
    const color = VEHICLE_COLORS[def.model] ?? 0xaaaaaa;
    const isBus = def.model.startsWith('bus'), isTruck = def.model.startsWith('truck');
    const bodyH = isBus ? h * 0.95 : isTruck ? h * 0.6 : h * 0.5;
    const body = new THREE.Mesh(new THREE.BoxGeometry(l, bodyH, w), std(color));
    body.position.set(cx, 0.35 + bodyH / 2, 0);
    g.add(body);
    if (!isBus) {
      const cab = new THREE.Mesh(new THREE.BoxGeometry(l * (isTruck ? 0.3 : 0.5), h * 0.4, w * 0.92), std(0x222a33, { roughness: 0.3 }));
      cab.position.set(cx + (isTruck ? l * 0.3 : -l * 0.02), 0.35 + bodyH + (h * 0.4) / 2, 0);
      g.add(cab);
    }
    for (const sx of [-0.32, 0.32]) for (const sz of [-1, 1]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.22, 14), std(0x111111));
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(cx + l * sx, 0.34, sz * (w / 2 - 0.05));
      g.add(wheel);
    }
  } else if (def.role === 'walker') {
    const color = WALKER_COLORS[def.model] ?? 0xd0623a;
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.22, 0.9, 6, 12), std(color));
    body.position.y = 0.85;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 14, 10), std(0xe8c9a5));
    head.position.y = 1.62;
    g.add(body, head);
  } else {
    // the ego pedestrian is YOU: just a ring on the ground (visible from above / to spectators)
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.28, 0.34, 28), new THREE.MeshBasicMaterial({ color: 0x41c7ff, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05;
    g.add(ring);
  }
  return g;
}

export interface GoalMarker { group: THREE.Group; task: TaskDef; update(t: number): void }

/** Pulsing target ring + beam, and (for path tasks) a translucent corridor ribbon. */
export function makeTaskMarkers(tasks: TaskDef[]): GoalMarker[] {
  return tasks.map((task) => {
    const group = new THREE.Group();
    group.name = `task:${task.id}`;
    // the ring has the radius of the goal zone the task is actually judged against (its formula), else the legacy tolerance
    let zone: Zone | null = null;
    if (task.spec) for (const n of walk(task.spec.goal)) if (n.op === 'in_zone' && n.zone && n.zone.kind !== 'entity') zone = n.zone;
    const radius = zone?.kind === 'disc' ? zone.r : zone?.kind === 'rect' ? Math.min(zone.hl, zone.hw) : task.tolerance;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(Math.max(0.6, radius), 0.07, 8, 40), new THREE.MeshBasicMaterial({ color: 0x35e0ff }));
    ring.rotation.x = Math.PI / 2; ring.position.y = 0.15;
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 5, 8, 1, true), new THREE.MeshBasicMaterial({ color: 0x35e0ff, transparent: true, opacity: 0.35, side: THREE.DoubleSide }));
    beam.position.y = 2.5;
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 14), new THREE.MeshBasicMaterial({ color: 0xffe14a }));
    arrow.rotation.x = Math.PI; arrow.position.y = 2.2;
    const spot = new THREE.Group();
    spot.add(ring, beam, arrow);
    spot.position.set(task.target.x, 0, -task.target.y);
    group.add(spot);

    // corridors: every near_path atom of the task's formulas (helper-made path tasks compile to one), else the legacy failure condition
    const corridors: { pts: Pt[]; tol: number }[] = [];
    if (task.spec) {
      for (const f of [task.spec.goal, ...task.spec.safety]) for (const n of walk(f)) if (n.op === 'near_path' && n.path && n.path.length >= 2) corridors.push({ pts: n.path, tol: n.tol ?? 2 });
    } else {
      const traj = task.failures.find((f) => f.type === 'trajectory');
      if (traj && traj.type === 'trajectory' && traj.vertices.length >= 2) corridors.push({ pts: traj.vertices, tol: traj.tolerance });
    }
    for (const c of corridors) group.add(ribbon(c.pts, c.tol, 0.09, 0x35e0ff, 0.28), ribbon(c.pts, 0.07, 0.1, 0xffe14a, 0.95));
    return {
      group, task,
      update(t: number) {
        arrow.position.y = 2.2 + Math.sin(t * 3) * 0.12;
        ring.scale.setScalar(1 + Math.sin(t * 4) * 0.04);
      },
    };
  });
}

function ribbon(pts: Pt[], halfWidth: number, y: number, color: number, opacity: number): THREE.Mesh {
  const a = offsetPolyline(pts, halfWidth), b = offsetPolyline(pts, -halfWidth);
  const pos: number[] = [], idx: number[] = [];
  for (let i = 0; i < pts.length; i++) {
    pos.push(a[i][0], y, -a[i][1], b[i][0], y, -b[i][1]);
    if (i < pts.length - 1) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2, k, k + 2, k + 1, k + 1, k + 2, k + 3); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  return new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, side: THREE.DoubleSide, depthWrite: false }));
}
