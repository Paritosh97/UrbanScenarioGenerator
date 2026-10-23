/**
 * Street furniture. Procedural low-poly placeholders; list a glTF in assets/manifest.json
 * ({"bus_stop": "assets/bus_stop.glb"}) next to the player to replace any of them (generated assets plug in the same way).
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const mat = (c: number, r = 0.8) => new THREE.MeshStandardMaterial({ color: c, roughness: r });
const box = (w: number, h: number, d: number, c: number, x = 0, y = 0, z = 0) => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(c));
  m.position.set(x, y + h / 2, z);
  return m;
};
const cyl = (r: number, h: number, c: number, x = 0, y = 0, z = 0, seg = 10) => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat(c));
  m.position.set(x, y + h / 2, z);
  return m;
};

/**
 * Local frame of a prop: +x is the direction it FACES (toward the road for bus stops and benches),
 * +z runs along the pavement. The Python exporter sets prop.heading accordingly.
 */
const BUILDERS: Record<string, () => THREE.Object3D> = {
  bus_stop() {
    const g = new THREE.Group();
    g.add(box(1.4, 0.1, 3.2, 0x6a7078, 0, 2.4, 0));
    for (const z of [-1.5, 1.5]) g.add(cyl(0.05, 2.4, 0x6a7078, -0.6, 0, z));
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.04, 1.5, 3.1), new THREE.MeshStandardMaterial({ color: 0x9ec9d9, transparent: true, opacity: 0.45 }));
    back.position.set(-0.65, 1.3, 0);
    g.add(back, box(0.35, 0.07, 1.8, 0x8a6a45, -0.45, 0.45, 0));
    g.add(cyl(0.03, 2.9, 0x3d7a3d, 0.5, 0, 1.9), box(0.05, 0.45, 0.45, 0x2f7d32, 0.5, 2.55, 1.9));
    return g;
  },
  waste_basket() {
    const g = new THREE.Group();
    g.add(cyl(0.22, 0.75, 0x2f5f3a, 0, 0, 0, 12), cyl(0.24, 0.06, 0x20402a, 0, 0.75, 0, 12));
    return g;
  },
  bench() {
    const g = new THREE.Group();
    g.add(box(0.45, 0.06, 1.6, 0x8a6a45, 0, 0.45, 0), box(0.05, 0.4, 1.6, 0x8a6a45, -0.22, 0.65, 0));
    g.add(box(0.4, 0.45, 0.06, 0x30343a, 0, 0, -0.7), box(0.4, 0.45, 0.06, 0x30343a, 0, 0, 0.7));
    return g;
  },
  tree() {
    const g = new THREE.Group();
    g.add(cyl(0.18, 2.2, 0x6b4a2b, 0, 0, 0, 8));
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(1.7, 1), mat(0x3f7f3a, 1));
    crown.position.y = 3.6;
    g.add(crown);
    return g;
  },
  street_lamp() {
    const g = new THREE.Group();
    g.add(cyl(0.07, 6, 0x4b5057, 0, 0, 0, 8), box(0.9, 0.08, 0.14, 0x4b5057, 0.4, 5.95, 0));
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.14, 10, 8), new THREE.MeshBasicMaterial({ color: 0xfff1c0 }));
    bulb.position.set(0.85, 5.9, 0);
    g.add(bulb);
    return g;
  },
  bollard() { return cyl(0.1, 0.9, 0x6b6f75, 0, 0, 0, 10); },
  bicycle_parking() {
    const g = new THREE.Group();
    for (let i = 0; i < 4; i++) g.add(box(0.05, 0.8, 0.5, 0x555a60, i * 0.5 - 0.75, 0, 0));
    return g;
  },
};

export function makeProp(ptype: string): THREE.Object3D {
  const f = BUILDERS[ptype];
  const o = f ? f() : box(0.4, 0.4, 0.4, 0xaa55aa);
  o.name = `prop:${ptype}`;
  return o;
}

/** Replace procedural props with glTF models listed in assets/manifest.json (best effort, silent if absent). */
export async function applyGltfOverrides(root: THREE.Object3D, base: string): Promise<void> {
  let manifest: Record<string, string> = {};
  try { const r = await fetch(`${base}assets/manifest.json`); if (r.ok) manifest = await r.json(); } catch { return; }
  const loader = new GLTFLoader();
  for (const t of Object.keys(manifest)) {
    let gltf;
    try { gltf = await loader.loadAsync(`${base}${manifest[t]}`); } catch { continue; }
    root.traverse((o) => {
      if (o.name !== `prop:${t}`) return;
      o.clear();
      o.add(gltf.scene.clone(true));
    });
  }
}
