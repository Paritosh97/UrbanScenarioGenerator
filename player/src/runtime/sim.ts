/**
 * Lightweight OpenSCENARIO interpreter + guided-task manager. Framework-free and deterministic.
 *
 * The EGO pedestrian is the person wearing the headset (or walking with WASD): the renderer feeds their foot
 * position in via `setUser`, and this class never moves them. Everything else (vehicles, walkers, signals,
 * acts/events, task rules) is driven by the scenario.
 */
import type { Pt, SceneMap } from './types';
import { SURFACE_SETS, SurfaceClassifier } from './surface';
import { dist, distToObb, distToPolyline, toLocal } from './geometry';
import type { ActionDef, ConditionDef, EntityDef, EventDef, FailureDef, Rule, ScenarioDef, TaskDef } from './xosc';
import { firstZoneCentre, references } from './formula';
import { goalStatus, type Sample } from './monitor';

export const USER_RADIUS = 0.3;
const GRACE = 1.0;          // seconds a user may be off-surface / off-corridor before failing
const END_DELAY = 2.5;      // seconds the final feedback stays up before the session ends
const SAMPLE_DT = 0.1;      // task formulas are monitored on a 10 Hz trace, the same rate as the Python reference
const EVAL_INTERVAL = 0.04; // between monitor evaluations on the in-progress (provisional) sample

export type TaskStatus = 'pending' | 'active' | 'success' | 'failed' | 'skipped';
export type ElemPhase = 'standby' | 'running' | 'complete';

export interface EntityState {
  def: EntityDef;
  x: number; y: number; h: number; speed: number;
  follow: null | { t0: number; times: number[]; pts: { x: number; y: number; h: number }[] };
}

export interface TaskState {
  def: TaskDef;
  status: TaskStatus;
  reason: string;
  tStart: number | null;
  tEnd: number | null;
  slow: boolean;
  distance: number;               // current distance to target
  minVehicleDist: number;
  outSurfaceSince: number | null;
  outPathSince: number | null;
  insideSignalCrossing: boolean;
  // ---- specification monitor
  samples: Sample[];
  nextSample: number;
  lastEval: number;
  refs: ReturnType<typeof references> | null;
  goalMargin: number | null;      // robustness of the goal formula (lo): >= 0 means satisfied
  safetyMargin: number | null;    // smallest robustness among the safety formulas
}

export interface Message { t: number; text: string; kind: 'info' | 'success' | 'failure' | 'hint' }

type ElemState = { state: ElemPhase; started: number | null; ended: number | null };

/** What the live inspector shows for one OpenSCENARIO event. */
export interface EventView {
  name: string; act: string; actors: string[]; phase: ElemPhase; started: number | null;
  actions: string[]; waitingFor: string;
}

export interface SimLog {
  scenario: string; scenarioType: string; outcome: string; duration: number;
  tasks: { id: number; name: string; category: string; status: string; reason: string; tStart: number | null; tEnd: number | null; durationS: number | null; minVehicleDistM: number | null; slow: boolean; goalMargin: number | null; safetyMargin: number | null }[];
  groups: Record<string, string>;
  trace: [number, number, number][];
  events: { t: number; what: string }[];
}

const cmp = (a: number, rule: Rule, b: number): boolean => {
  switch (rule) {
    case 'greaterThan': return a > b;
    case 'greaterOrEqual': return a >= b;
    case 'lessThan': return a < b;
    case 'lessOrEqual': return a <= b;
    case 'equalTo': return a === b;
    case 'notEqualTo': return a !== b;
  }
};

export class Simulation {
  time = 0;
  finished = false;
  outcome: 'running' | 'success' | 'failed' | 'timeout' = 'running';
  readonly entities = new Map<string, EntityState>();
  readonly signals = new Map<string, string>();
  readonly tasks: TaskState[];
  readonly messages: Message[] = [];
  readonly trace: [number, number, number][] = [];
  readonly eventLog: { t: number; what: string }[] = [];
  user: Pt = [0, 0];
  userHeading = 0;
  readonly surface: SurfaceClassifier;

  private events = new Map<string, ElemState>();
  private acts = new Map<string, 'standby' | 'running'>();
  private evDefs: EventDef[];
  private lastTrace = -1;
  private finishAt: number | null = null;

  constructor(readonly map: SceneMap, readonly def: ScenarioDef) {
    this.surface = new SurfaceClassifier(map);
    for (const e of def.entities) {
      this.entities.set(e.name, { def: e, x: e.start.x, y: e.start.y, h: e.start.h, speed: 0, follow: null });
    }
    const u = def.entities.find((e) => e.role === 'user');
    if (u) { this.user = [u.start.x, u.start.y]; this.userHeading = u.start.h; }
    for (const s of def.initSignals) this.signals.set(s.name, s.state);
    this.evDefs = def.events;
    for (const ev of def.events) this.events.set(ev.name, { state: 'standby', started: null, ended: null });
    for (const a of def.acts) this.acts.set(a.name, 'standby');
    this.tasks = def.tasks.map((t) => ({
      def: t, status: 'pending', reason: '', tStart: null, tEnd: null, slow: false, distance: Infinity,
      minVehicleDist: Infinity, outSurfaceSince: null, outPathSince: null, insideSignalCrossing: false,
      samples: [], nextSample: 0, lastEval: -1, goalMargin: null, safetyMargin: null,
      refs: t.spec ? references([t.spec.goal, ...t.spec.safety]) : null,
    }));
  }

  // ------------------------------------------------------------------ public API
  setUser(x: number, y: number, h = this.userHeading): void {
    this.user = [x, y];
    this.userHeading = h;
  }

  activeTasks(): TaskState[] { return this.tasks.filter((t) => t.status === 'active'); }

  taskText(t: TaskState, lang = 'en'): string {
    const d = t.def.instruction;
    return d[lang] ?? d.en ?? Object.values(d)[0] ?? t.def.name;
  }

  step(dt: number): void {
    if (this.finished) return;
    this.time += dt;
    this.updateEntities();
    this.updateActsAndEvents();
    this.evaluateTasks(dt);
    this.updateEventCompletion();
    this.checkFinish();
    if (this.time - this.lastTrace >= 0.1) {
      this.trace.push([+this.time.toFixed(2), +this.user[0].toFixed(2), +this.user[1].toFixed(2)]);
      this.lastTrace = this.time;
    }
  }

  /** Live view of every OpenSCENARIO event for the inspector panel. */
  eventViews(): EventView[] {
    return this.evDefs.map((ev) => {
      const s = this.events.get(ev.name)!;
      const actions = ev.actions.map((a) => {
        switch (a.kind) {
          case 'speed': return `speed ${a.speed.toFixed(1)} m/s`;
          case 'trajectory': return `follow route (${a.pts.length} pts, ${a.times[a.times.length - 1].toFixed(0)} s)`;
          case 'signal': return `signal ${a.name} -> ${a.state}`;
          case 'task': return `VR task ${a.task.id}: ${a.task.name}`;
        }
      });
      return { name: ev.name, act: ev.act, actors: ev.actors, phase: s.state, started: s.started, actions, waitingFor: s.state === 'standby' ? this.describeWait(ev) : '' };
    });
  }

  results(): SimLog {
    const groups: Record<string, string> = {};
    const byGroup = new Map<string, TaskState[]>();
    for (const t of this.tasks) if (t.def.group) byGroup.set(t.def.group, [...(byGroup.get(t.def.group) ?? []), t]);
    for (const [g, ts] of byGroup) {
      const req = ts.filter((t) => t.def.required);
      groups[g] = req.every((t) => t.status === 'success') ? 'success'
        : req.some((t) => t.status === 'failed' || t.status === 'skipped') ? 'failed' : 'incomplete';
    }
    return {
      scenario: this.def.name, scenarioType: this.def.scenarioType, outcome: this.outcome, duration: +this.time.toFixed(2),
      tasks: this.tasks.map((t) => ({
        id: t.def.id, name: t.def.name, category: t.def.category, status: t.status, reason: t.reason,
        tStart: t.tStart, tEnd: t.tEnd, durationS: t.tStart != null && t.tEnd != null ? +(t.tEnd - t.tStart).toFixed(2) : null,
        minVehicleDistM: Number.isFinite(t.minVehicleDist) ? +t.minVehicleDist.toFixed(2) : null, slow: t.slow,
        goalMargin: t.goalMargin === null ? null : +t.goalMargin.toFixed(3), safetyMargin: t.safetyMargin === null ? null : +t.safetyMargin.toFixed(3),
      })),
      groups, trace: this.trace, events: this.eventLog,
    };
  }

  /** Oriented bounding box of an entity (vehicles' reference point is the rear axle). */
  obb(e: EntityState): { c: Pt; h: number; l: number; w: number } {
    const b = e.def.bbox;
    const c = Math.cos(e.h), s = Math.sin(e.h);
    return { c: [e.x + c * b.cx - s * b.cy, e.y + s * b.cx + c * b.cy], h: e.h, l: b.length, w: b.width };
  }

  // ------------------------------------------------------------------ entities
  private updateEntities(): void {
    for (const e of this.entities.values()) {
      const f = e.follow;
      if (!f) continue;
      const t = this.time - f.t0;
      const n = f.pts.length;
      if (t >= f.times[n - 1]) {
        const last = f.pts[n - 1];
        e.x = last.x; e.y = last.y; e.speed = 0;
        continue;
      }
      let i = 0;
      while (i < n - 2 && t > f.times[i + 1]) i++;
      const t0 = f.times[i], t1 = f.times[i + 1];
      const k = t1 > t0 ? Math.max(0, Math.min(1, (t - t0) / (t1 - t0))) : 1;
      const a = f.pts[i], b = f.pts[i + 1];
      e.x = a.x + (b.x - a.x) * k;
      e.y = a.y + (b.y - a.y) * k;
      if (Math.hypot(b.x - a.x, b.y - a.y) > 1e-6) e.h = Math.atan2(b.y - a.y, b.x - a.x);
      e.speed = t1 > t0 ? Math.hypot(b.x - a.x, b.y - a.y) / (t1 - t0) : 0;
    }
  }

  // ------------------------------------------------------------------ storyboard
  private holds(groups: ConditionDef[][], actors: string[] = []): boolean {
    if (groups.length === 0) return true;
    return groups.some((g) => g.every((c) => this.cond(c, actors)));
  }

  private describeWait(ev: EventDef): string {
    if (this.acts.get(ev.act) !== 'running') return `act ${ev.act} not started`;
    const parts: string[] = [];
    for (const g of ev.start) for (const c of g) {
      if (this.cond(c, ev.actors)) continue;
      if (c.type === 'time') parts.push(`time >= ${c.value.toFixed(0)} s`);
      else if (c.type === 'elementState') parts.push(`${c.ref} ${c.state.replace('Transition', '')}`);
      else if (c.type === 'relDistance') parts.push(`${c.entity} within ${c.value.toFixed(0)} m`);
    }
    return parts.join(' and ') || 'trigger';
  }

  private cond(c: ConditionDef, actors: string[]): boolean {
    switch (c.type) {
      case 'time': return cmp(this.time, c.rule, c.value);
      case 'elementState': {
        const s = this.events.get(c.ref);
        if (!s) return false;
        switch (c.state) {
          case 'startTransition': case 'runningState': return s.state !== 'standby';
          case 'endTransition': case 'completeState': return s.state === 'complete';
          case 'standbyState': return s.state === 'standby';
          default: return false;
        }
      }
      case 'relDistance': {
        const ref = c.entity === 'User' || this.entities.get(c.entity)?.def.role === 'user' ? { p: this.user, e: null as EntityState | null } : { p: null as Pt | null, e: this.entities.get(c.entity) ?? null };
        const trig = c.triggering.length ? c.triggering : actors;
        return trig.some((name) => {
          const te = this.entities.get(name);
          if (!te) return false;
          let d: number;
          if (ref.p) {
            d = c.freespace ? distToObb(ref.p, this.obb(te).c, te.h, te.def.bbox.length, te.def.bbox.width) : dist([te.x, te.y], ref.p);
          } else if (ref.e) d = dist([te.x, te.y], [ref.e.x, ref.e.y]);
          else return false;
          return cmp(d, c.rule, c.value);
        });
      }
      default: return false;
    }
  }

  private updateActsAndEvents(): void {
    for (const a of this.def.acts) {
      if (this.acts.get(a.name) === 'standby' && this.holds(a.start)) {
        this.acts.set(a.name, 'running');
        this.eventLog.push({ t: this.time, what: `act ${a.name} started` });
      }
    }
    for (const ev of this.evDefs) {
      const s = this.events.get(ev.name)!;
      if (s.state !== 'standby' || this.acts.get(ev.act) !== 'running') continue;
      if (!this.holds(ev.start, ev.actors)) continue;
      s.state = 'running';
      s.started = this.time;
      this.eventLog.push({ t: +this.time.toFixed(2), what: `event ${ev.name} started` });
      for (const a of ev.actions) this.runAction(ev, a);
    }
  }

  private runAction(ev: EventDef, a: ActionDef): void {
    switch (a.kind) {
      case 'speed':
        for (const n of ev.actors) { const e = this.entities.get(n); if (e) e.speed = a.speed; }
        break;
      case 'trajectory':
        for (const n of ev.actors) {
          const e = this.entities.get(n);
          if (e) e.follow = { t0: this.time, times: a.times, pts: a.pts };
        }
        break;
      case 'signal':
        this.signals.set(a.name, a.state);
        this.eventLog.push({ t: +this.time.toFixed(2), what: `signal ${a.name} -> ${a.state}` });
        break;
      case 'task':
        this.activateTask(a.task);
        break;
    }
  }

  private updateEventCompletion(): void {
    for (const ev of this.evDefs) {
      const s = this.events.get(ev.name)!;
      if (s.state !== 'running') continue;
      let pending = 0;
      for (const a of ev.actions) {
        if (a.kind === 'trajectory') {
          for (const n of ev.actors) {
            const f = this.entities.get(n)?.follow;
            if (f && this.time - f.t0 < f.times[f.times.length - 1]) pending++;
          }
        } else if (a.kind === 'task') {
          const t = this.tasks.find((x) => x.def.id === a.task.id)!;
          if (t.status === 'active') pending++;
        }
      }
      if (pending === 0) {
        s.state = 'complete';
        s.ended = this.time;
        this.eventLog.push({ t: +this.time.toFixed(2), what: `event ${ev.name} ended` });
      }
    }
  }

  // ------------------------------------------------------------------ tasks
  private activateTask(def: TaskDef): void {
    const t = this.tasks.find((x) => x.def.id === def.id)!;
    const blocked = def.dependsOn.some((d) => {
      const dep = this.tasks.find((x) => x.def.id === d);
      return def.mode === 'sequential' && dep && (dep.status === 'failed' || dep.status === 'skipped');
    });
    if (blocked) {
      t.status = 'skipped'; t.reason = 'earlier task failed'; t.tStart = t.tEnd = this.time;
      this.say('An earlier task failed, so this one was skipped.', 'info');
      return;
    }
    t.status = 'active';
    t.tStart = this.time;
    this.say(this.taskText(t), 'info');
  }

  private resolve(t: TaskState, status: 'success' | 'failed', reason: string): void {
    t.status = status; t.reason = reason; t.tEnd = this.time;
    if (t.def.spec && t.samples.length) {                    // exact margins: the trace is complete now
      const fin = goalStatus(t.def.spec.goal, t.def.spec.safety, t.samples, SAMPLE_DT, true);
      t.goalMargin = fin.goal[0];
      t.safetyMargin = fin.safety.length ? Math.min(...fin.safety.map((x) => x[0])) : null;
    }
    const fb = status === 'success' ? t.def.success : t.def.failure;
    const text = fb.en ?? Object.values(fb)[0] ?? (status === 'success' ? 'Task complete.' : `Task failed (${reason}).`);
    this.say(text, status === 'success' ? 'success' : 'failure');
    this.eventLog.push({ t: +this.time.toFixed(2), what: `task ${t.def.id} ${status}: ${reason}` });
  }

  private evaluateTasks(dt: number): void {
    const p = this.user;
    for (const e of this.entities.values()) {
      if (e.def.role === 'user') continue;
      const o = this.obb(e);
      const d = distToObb(p, o.c, o.h, o.l, o.w);
      for (const t of this.tasks) if (t.status === 'active') t.minVehicleDist = Math.min(t.minVehicleDist, d);
    }
    const surf = this.surface.at(p);
    for (const t of this.tasks) {
      if (t.status !== 'active') continue;
      const d = t.def;
      const elapsed = this.time - (t.tStart ?? this.time);
      const goalXY = d.spec ? firstZoneCentre(d.spec.goal) : null;
      t.distance = dist(p, goalXY ?? [d.target.x, d.target.y]);

      if (d.spec) {
        const res = this.stepSpec(t, elapsed, surf);
        if (res) { this.resolve(t, res.status, res.reason); continue; }
      } else {
        const fail = this.checkFailures(t, surf);
        if (fail) { this.resolve(t, 'failed', fail); continue; }
        if (t.distance <= d.tolerance) { this.resolve(t, 'success', t.slow ? 'late' : 'ok'); continue; }
      }
      if (elapsed >= d.timeout.baseline) { this.resolve(t, 'failed', 'timeout'); continue; }
      if (!t.slow && elapsed >= d.timeout.initial) { t.slow = true; this.say('Hurry up, time is running out.', 'hint'); }
    }
    void dt;
  }

  /** Snapshot of everything the task's formulas can refer to, at the current instant. */
  private makeSample(t: TaskState, surf: string, prev: Sample | undefined): Sample {
    const p = this.user;
    const refs = t.refs!;
    const ents: Sample['ents'] = {};
    for (const n of refs.entities) {
      const e = this.entities.get(n);
      if (e) { const o = this.obb(e); ents[n] = [o.c[0], o.c[1], o.h, o.l, o.w]; }
    }
    const signals: Record<string, string> = {};
    for (const n of refs.signals) { const v = this.signals.get(n); if (v !== undefined) signals[n] = v; }
    const events = new Set<string>();
    for (const n of refs.events) { const s = this.events.get(n); if (s && s.state !== 'standby') events.add(n); }
    const speed = prev ? Math.hypot(p[0] - prev.x, p[1] - prev.y) / SAMPLE_DT : 0;
    return { x: p[0], y: p[1], gaze: this.userHeading, speed, surface: surf, ents, signals, events };
  }

  /** Feed the task's 10 Hz trace and evaluate its formulas. Returns the outcome once it is decided. */
  private stepSpec(t: TaskState, elapsed: number, surf: string): { status: 'success' | 'failed'; reason: string } | null {
    const spec = t.def.spec!;
    let added = false;
    for (let guard = 0; elapsed >= t.nextSample * SAMPLE_DT - 1e-9 && guard < 50; guard++) {
      t.samples.push(this.makeSample(t, surf, guard === 0 ? t.samples[t.samples.length - 1] : undefined));
      t.nextSample++;
      added = true;
    }
    if (!added && this.time - t.lastEval < EVAL_INTERVAL) return null;
    t.lastEval = this.time;
    const last = t.samples[t.samples.length - 1];
    const trace = added || !last ? t.samples : [...t.samples, this.makeSample(t, surf, last)];
    const res = goalStatus(spec.goal, spec.safety, trace, SAMPLE_DT, false);
    t.goalMargin = res.goal[0];
    t.safetyMargin = res.safety.length ? Math.min(...res.safety.map((x) => x[0])) : null;
    if (res.status === 'failed') {
      const label = res.by === 'safety' ? spec.safety[res.index].label : spec.goal.label;
      return { status: 'failed', reason: label ?? (res.by === 'safety' ? 'a rule was broken' : 'the goal can no longer be reached') };
    }
    if (res.status === 'success') return { status: 'success', reason: t.slow ? 'late' : 'ok' };
    return null;
  }

  private checkFailures(t: TaskState, surf: string): string | null {
    const p = this.user;
    for (const f of t.def.failures as FailureDef[]) {
      switch (f.type) {
        case 'collision':
          for (const n of f.entities) {
            const e = this.entities.get(n);
            if (!e) continue;
            const o = this.obb(e);
            if (distToObb(p, o.c, o.h, o.l, o.w) <= USER_RADIUS) return `collision with ${n}`;
          }
          break;
        case 'surface': {
          const allowed = SURFACE_SETS[f.surface] ?? SURFACE_SETS.walkable;
          if (!allowed.has(surf as never)) {
            t.outSurfaceSince = t.outSurfaceSince ?? this.time;
            if (this.time - t.outSurfaceSince > GRACE) return `left ${f.surface} (on ${surf})`;
          } else t.outSurfaceSince = null;
          break;
        }
        case 'trajectory': {
          if (f.vertices.length < 2) break;
          if (distToPolyline(f.vertices, p) > f.tolerance) {
            t.outPathSince = t.outPathSince ?? this.time;
            if (this.time - t.outPathSince > GRACE) return 'left the marked path';
          } else t.outPathSince = null;
          break;
        }
        case 'signal': {
          const c = this.map.crossings.find((x) => x.id === f.crossing);
          if (!c) break;
          const q = toLocal(p, c.pos, c.heading);
          const inside = Math.abs(q[0]) <= c.length / 2 && Math.abs(q[1]) <= c.width / 2;
          if (inside && !t.insideSignalCrossing) {
            const st = f.signal ? this.signals.get(f.signal) : undefined;
            if (st !== undefined && st !== 'green') { t.insideSignalCrossing = true; return 'crossed on red'; }
          }
          t.insideSignalCrossing = inside;
          break;
        }
        case 'trigger':
          for (const n of f.events) if (this.events.get(n)?.state && this.events.get(n)!.state !== 'standby') return `event ${n} occurred`;
          break;
        case 'timeout': break;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------ end of scenario
  private checkFinish(): void {
    const stopHit = this.holds(this.def.stop);
    const required = this.tasks.filter((t) => t.def.required);
    const allResolved = required.length > 0 && required.every((t) => ['success', 'failed', 'skipped'].includes(t.status));
    if (allResolved && this.finishAt === null) this.finishAt = this.time + END_DELAY;
    if (this.finishAt !== null && this.time >= this.finishAt) this.end(required.every((t) => t.status === 'success') ? 'success' : 'failed');
    else if (this.def.stop.length && stopHit) {
      for (const t of this.tasks) if (t.status === 'active') this.resolve(t, 'failed', 'timeout');
      this.end(required.every((t) => t.status === 'success') ? 'success' : 'timeout');
    }
  }

  private end(outcome: 'success' | 'failed' | 'timeout'): void {
    this.finished = true;
    this.outcome = outcome;
    this.eventLog.push({ t: +this.time.toFixed(2), what: `scenario ended: ${outcome}` });
  }

  private say(text: string, kind: Message['kind']): void {
    this.messages.push({ t: this.time, text, kind });
  }
}
