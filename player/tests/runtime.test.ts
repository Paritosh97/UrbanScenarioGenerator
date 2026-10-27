// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseXosc } from '../src/runtime/xosc';
import { Simulation } from '../src/runtime/sim';
import { PedRouter } from '../src/runtime/pedroute';
import { SurfaceClassifier } from '../src/runtime/surface';
import type { Pt, SceneMap } from '../src/runtime/types';

const rd = (n: string) => readFileSync(resolve('tests/fixtures', n), 'utf-8');
const map = JSON.parse(rd('map.json')) as SceneMap;
const router = PedRouter.fromMap(map)!;
const load = (id: string) => new Simulation(map, parseXosc(rd(`${id}.xosc`)));
const DT = 0.05;

/**
 * TEST-ONLY driver standing in for a human so the runtime rules can be exercised headlessly.
 * The product never does this: in the app the ego pedestrian is the person in VR / first person.
 */
function walkTo(sim: Simulation, opts: { waitUntil?: number; speed?: number } = {}, maxT = 400) {
  const speed = opts.speed ?? 1.3;
  let path: Pt[] = [];
  let cur = -1;
  while (!sim.finished && sim.time < maxT) {
    const act = sim.activeTasks()[0];
    if (act && sim.time >= (opts.waitUntil ?? 0)) {
      if (cur !== act.def.id) {
        cur = act.def.id;
        const r = router.route(sim.user, [act.def.target.x, act.def.target.y]);
        path = r ? r.waypoints.slice(1) : [[act.def.target.x, act.def.target.y]];
      }
      if (path.length) {
        const [tx, ty] = path[0];
        const dx = tx - sim.user[0], dy = ty - sim.user[1], d = Math.hypot(dx, dy), len = speed * DT;
        const next: Pt = d <= len ? [tx, ty] : [sim.user[0] + (dx / d) * len, sim.user[1] + (dy / d) * len];
        const sig = act.def.failures.find((f) => f.type === 'signal');
        const stepsOnto = sim.surface.at(next) === 'crosswalk' && sim.surface.at(sim.user) !== 'crosswalk';
        if (sig && sig.type === 'signal' && stepsOnto && sim.signals.get(sig.signal ?? '') !== 'green') { sim.step(DT); continue; }
        if (d <= len) path.shift();
        sim.setUser(next[0], next[1], Math.atan2(dy, dx));
      }
    }
    sim.step(DT);
  }
  return sim;
}

describe('TypeScript surface classifier equals Python', () => {
  it('agrees on every sampled point', () => {
    const samples = JSON.parse(rd('surface_samples.json')) as [number, number, string][];
    const sc = new SurfaceClassifier(map);
    const wrong = samples.filter(([x, y, s]) => sc.at([x, y]) !== s);
    expect(samples.length).toBeGreaterThan(10000);
    expect(wrong.slice(0, 5)).toEqual([]);
  });
});

describe('OpenSCENARIO parsing', () => {
  it('reads entities, tasks and triggers from every archetype', () => {
    for (const id of ['ptp_env', 'ptp_road', 'cpath', 'env_con', 'dyn_nav', 'dep_comp', 'indep_comp']) {
      const d = parseXosc(rd(`${id}.xosc`));
      expect(d.scenarioType).toBe(id);
      expect(d.entities.some((e) => e.role === 'user')).toBe(true);
      expect(d.tasks.length).toBeGreaterThan(0);
      expect(d.events.length).toBeGreaterThanOrEqual(d.tasks.length);
      expect(d.stop.length).toBe(1);
    }
  });
  it('reads task dependencies as storyboard triggers', () => {
    const ev3 = parseXosc(rd('dep_comp.xosc')).events.find((e) => e.name.startsWith('task_3'))!;
    expect(ev3.start[0].some((c) => c.type === 'elementState' && c.ref.startsWith('task_2'))).toBe(true);
  });
});

describe('the player is never moved by the runtime', () => {
  it('stands still when nobody walks, and the tasks time out', () => {
    const sim = load('ptp_env');
    const p0 = [...sim.user];
    while (!sim.finished && sim.time < 300) sim.step(0.1);
    expect(sim.user).toEqual(p0);
    expect(sim.tasks[0].status).toBe('failed');
    expect(sim.tasks[0].reason).toBe('timeout');
    expect(sim.tasks[0].slow).toBe(true);
  });
});

describe('task rules (exercised with the test-only driver)', () => {
  for (const id of ['ptp_env', 'ptp_road', 'cpath', 'env_con', 'dep_comp', 'indep_comp']) {
    it(`${id} is completable`, () => {
      const sim = walkTo(load(id));
      expect(sim.tasks.filter((t) => t.status !== 'success').map((t) => `${t.def.name}:${t.status}:${t.reason}`)).toEqual([]);
      expect(sim.outcome).toBe('success');
    });
  }
  it('dependent tasks run strictly in order', () => {
    const [a, b, c] = walkTo(load('dep_comp')).tasks;
    expect(a.tEnd!).toBeLessThanOrEqual(b.tStart! + 1e-6);
    expect(b.tEnd!).toBeLessThanOrEqual(c.tStart! + 1e-6);
  });
  it('independent tasks are all active together', () => {
    const sim = load('indep_comp');
    sim.step(DT); sim.step(DT);
    expect(sim.activeTasks().length).toBe(2);
  });
  it('dyn_nav: walking straight out is a collision, waiting for the car is not', () => {
    expect(walkTo(load('dyn_nav')).tasks[0].reason).toMatch(/collision with Car1/);
    const ok = walkTo(load('dyn_nav'), { waitUntil: 12 });
    expect(ok.tasks[0].status).toBe('success');
    expect(ok.tasks[0].minVehicleDist).toBeGreaterThan(0.3);
  });
  it('cpath: leaving the corridor fails', () => {
    const sim = load('cpath');
    const t = sim.tasks[0].def.target;
    sim.step(DT);
    sim.setUser(t.x + 8, t.y - 8);
    for (let i = 0; i < 80; i++) sim.step(DT);
    expect(sim.tasks[0].reason).toMatch(/marked path/);
  });
  it('env_con: touching a parked car fails', () => {
    const sim = load('env_con');
    sim.step(DT);
    const car = sim.entities.get('Car1')!;
    sim.setUser(car.x + 1.4, car.y);
    sim.step(DT);
    expect(sim.tasks[0].reason).toMatch(/collision with/);
  });
  it('signals: red fails, waiting for green succeeds', () => {
    const red = load('signal_cross');
    red.step(DT);
    const c = map.crossings.find((x) => x.id === 'crossing_1')!;
    expect(red.signals.get('signal_1')).toBe('red');
    red.setUser(c.pos[0], c.pos[1]);
    red.step(DT);
    expect(red.tasks[0].reason).toBe('crossed on red');
    const ok = walkTo(load('signal_cross'));
    expect(ok.tasks[0].status).toBe('success');
    expect(ok.tasks[0].tEnd!).toBeGreaterThan(14);
  });
});

describe('signal identifiers and states in the file', () => {
  it('numeric ids with lamp strings (esmini) and the old symbolic form both parse to symbolic names and red/green', () => {
    const text = rd('signal_cross.xosc');
    expect(text).toContain('state="on;off"');                                  // what a standard player expects for a two-lamp light
    expect(parseXosc(text).initSignals).toEqual([{ name: 'signal_1', state: 'red' }]);
    const old = text.replace(/<ParameterDeclaration[^>]*\/>/, '').replace(/name="1" state="on;off"/g, 'name="signal_1" state="red"')
      .replace(/name="1" state="off;on"/g, 'name="signal_1" state="green"');
    expect(parseXosc(old).initSignals).toEqual([{ name: 'signal_1', state: 'red' }]);
  });
});

describe('inspector data and research log', () => {
  it('lists the OpenSCENARIO events with phase, actions and what they wait for', () => {
    const sim = load('dyn_nav');
    let views = sim.eventViews();
    const move = views.find((v) => v.name === 'move_Car1')!;
    expect(move.phase).toBe('standby');
    expect(views.find((v) => v.name.startsWith('task_1'))!.phase).toBe('standby');   // act not yet started at t=0
    sim.step(DT); sim.step(DT);
    views = sim.eventViews();
    expect(views.find((v) => v.name.startsWith('task_1'))!.phase).toBe('running');
    expect(views.find((v) => v.name === 'move_Car1')!.phase).toBe('running');         // started by the task starting
    expect(views.find((v) => v.name === 'move_Car1')!.actions.join(' ')).toMatch(/speed 8\.0 m\/s.*follow route/);
  });
  it('records the walk and per-task metrics', () => {
    const log = walkTo(load('ptp_env')).results();
    expect(log.trace.length).toBeGreaterThan(50);
    expect(log.tasks[0]).toMatchObject({ status: 'success', category: 'ptp_env' });
  });
});
