// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseXosc } from '../src/runtime/xosc';
import { Simulation } from '../src/runtime/sim';
import { PedRouter } from '../src/runtime/pedroute';
import { Monitor, goalStatus, type Sample } from '../src/runtime/monitor';
import { walk, type FNode } from '../src/runtime/formula';
import type { Pt, SceneMap } from '../src/runtime/types';
import { inspect } from '../src/scene/snapshot';

const rd = (n: string) => readFileSync(resolve('tests/fixtures', n), 'utf-8');
const map = JSON.parse(rd('map.json')) as SceneMap;
const router = PedRouter.fromMap(map)!;
const load = (id: string) => new Simulation(map, parseXosc(rd(`${id}.xosc`)));
const DT = 0.05;

interface RawSample { x: number; y: number; gaze: number; speed: number; surface: string; ents: Record<string, number[]>; signals: Record<string, string>; events: string[] }
interface Case { formula: FNode; samples: RawSample[]; results: { n: number; complete: boolean; k: number; lo: number; hi: number }[] }

const toSample = (s: RawSample): Sample => ({ ...s, ents: s.ents as Sample['ents'], events: new Set(s.events) });

describe('the TypeScript monitor equals the Python reference', () => {
  const cases = JSON.parse(rd('formula_cases.json')) as Case[];
  it('has a meaningful number of randomised cases covering every operator', () => {
    expect(cases.length).toBeGreaterThanOrEqual(100);
    const ops = new Set<string>();
    for (const c of cases) for (const n of walk(c.formula)) ops.add(n.op);
    for (const op of ['in_zone', 'on_surface', 'near_path', 'dist_le', 'dist_ge', 'look_at', 'speed_le', 'speed_ge', 'signal_is', 'event',
      'not', 'and', 'or', 'implies', 'eventually', 'always', 'until', 'prev']) expect(ops.has(op), op).toBe(true);
  });
  it('gives identical (lo, hi) on every case, prefix length, completeness and anchor', () => {
    let checked = 0;
    const wrong: string[] = [];
    cases.forEach((c, i) => {
      const samples = c.samples.map(toSample);
      for (const r of c.results) {
        const [lo, hi] = new Monitor(samples.slice(0, r.n), 0.1, r.complete).rho(c.formula, r.k);
        checked++;
        if (Math.abs(lo - r.lo) > 1e-6 * Math.max(1, Math.abs(r.lo)) || Math.abs(hi - r.hi) > 1e-6 * Math.max(1, Math.abs(r.hi))) {
          wrong.push(`case ${i} n=${r.n} complete=${r.complete} k=${r.k}: ts=(${lo},${hi}) py=(${r.lo},${r.hi})`);
        }
      }
    });
    expect(checked).toBeGreaterThan(1500);
    expect(wrong.slice(0, 5)).toEqual([]);
  });
});

describe('formulas are read from the scenario file', () => {
  it('every task of every reference scenario carries a goal and safety formulas', () => {
    for (const id of ['ptp_env', 'ptp_road', 'cpath', 'env_con', 'dyn_nav', 'dep_comp', 'indep_comp', 'signal_cross', 'spec_cross', 'spec_look']) {
      for (const t of parseXosc(rd(`${id}.xosc`)).tasks) {
        expect(t.spec, `${id}:${t.name}`).not.toBeNull();
        expect(t.spec!.goal.op).toBeTruthy();
      }
    }
  });
  it('helper-made and model-written tasks are marked differently', () => {
    expect(parseXosc(rd('cpath.xosc')).tasks[0].spec!.origin).toBe('helper');
    expect(parseXosc(rd('spec_cross.xosc')).tasks[0].spec!.origin).toBe('spec');
    expect(parseXosc(rd('cpath.xosc')).tasks[0].spec!.safety[0].label).toBe('left the marked path');
  });
});

/** TEST-ONLY driver that stands in for a human (the product never moves the player). */
function stages(sim: Simulation): Pt[] {
  const out: Pt[] = [];
  for (const n of walk(sim.tasks[0].def.spec!.goal)) {
    if (n.op === 'in_zone' && n.zone?.kind === 'disc') out.push([n.zone.x, n.zone.y]);
  }
  return out;
}

function walkStages(sim: Simulation, opts: { waitAtFirst?: boolean; maxT?: number } = {}) {
  const goals = stages(sim);
  let si = 0, path: Pt[] = [], waited = false;
  const speed = 1.3;
  while (!sim.finished && sim.time < (opts.maxT ?? 200)) {
    if (sim.activeTasks().length && si < goals.length) {
      if (!path.length) {
        const r = router.route(sim.user, goals[si]);
        path = r ? r.waypoints.slice(1) : [goals[si]];
      }
      const [tx, ty] = path[0];
      const dx = tx - sim.user[0], dy = ty - sim.user[1], d = Math.hypot(dx, dy), len = speed * DT;
      const arrivedFirst = si === 0 && d <= len && path.length === 1;
      if (arrivedFirst && opts.waitAtFirst && !waited) {
        if (sim.signals.get('signal_1') !== 'green') { sim.step(DT); continue; }
        waited = true;
      }
      const next: Pt = d <= len ? [tx, ty] : [sim.user[0] + (dx / d) * len, sim.user[1] + (dy / d) * len];
      if (d <= len) { path.shift(); if (!path.length) si++; }
      sim.setUser(next[0], next[1], Math.atan2(dy, dx));
    }
    sim.step(DT);
  }
  return sim;
}

describe('model-written specifications are evaluated in the player', () => {
  it('spec_cross: crossing while the light is red is a violation reported with its label', () => {
    const sim = walkStages(load('spec_cross'));
    expect(sim.tasks[0].status).toBe('failed');
    expect(sim.tasks[0].reason).toBe('crossed on red');
  });
  it('spec_cross: waiting for green and then crossing succeeds, with positive margins', () => {
    const sim = walkStages(load('spec_cross'), { waitAtFirst: true });
    expect(sim.tasks[0].status).toBe('success');
    expect(sim.tasks[0].tEnd!).toBeGreaterThan(14);
    const log = sim.results().tasks[0];
    expect(log.goalMargin!).toBeGreaterThanOrEqual(0);
    expect(log.safetyMargin!).toBeGreaterThan(0);
  });
  it('spec_look: never looking at the car fails when the 25 s window closes', () => {
    const sim = load('spec_look');
    sim.setUser(sim.user[0], sim.user[1], -Math.PI / 2);       // facing south, away from the road
    while (!sim.finished && sim.time < 60) sim.step(DT);
    expect(sim.tasks[0].status).toBe('failed');
    expect(sim.tasks[0].tEnd!).toBeLessThan(30);               // decided by the window, before the 40 s baseline timeout
  });
  it('spec_look: turning the head toward the car succeeds', () => {
    const sim = load('spec_look');
    sim.step(DT);
    const car = sim.entities.get('Car1')!;
    sim.setUser(sim.user[0], sim.user[1], Math.atan2(car.y - sim.user[1], car.x - sim.user[0]));
    for (let i = 0; i < 20; i++) sim.step(DT);
    expect(sim.tasks[0].status).toBe('success');
  });
});

describe('statuses from the monitor', () => {
  it('goalStatus decides success, failure and undecided on a hand-made trace', () => {
    const mk = (x: number): Sample => ({ x, y: 0, gaze: 0, speed: 1, surface: 'sidewalk', ents: {}, signals: {}, events: new Set() });
    const goal: FNode = { op: 'eventually', start: 0, end: null, arg: { op: 'in_zone', zone: { kind: 'disc', x: 10, y: 0, r: 1 } } };
    expect(goalStatus(goal, [], [mk(0), mk(5)]).status).toBe('running');
    expect(goalStatus(goal, [], [mk(0), mk(9.5)]).status).toBe('success');
    const never: FNode = { op: 'always', start: 0, end: 0.2, arg: { op: 'in_zone', zone: { kind: 'disc', x: 10, y: 0, r: 1 } } };
    expect(goalStatus(never, [], [mk(0)]).status).toBe('failed');
  });
});

describe('inspector', () => {
  it('lists the specification of each started task with live margins', () => {
    const sim = load('spec_cross');
    for (let i = 0; i < 10; i++) sim.step(DT);
    const specs = inspect(sim).specs;
    expect(specs.length).toBe(1);
    expect(specs[0].goal).toContain('until');
    expect(specs[0].safety).toEqual(['crossed on red']);
    expect(typeof specs[0].goalMargin).toBe('number');
  });
});
