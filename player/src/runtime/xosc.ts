/**
 * OpenSCENARIO (1.x) reader for the pedestrian runtime.
 *
 * Understands the subset the generator emits: inline Pedestrian/Vehicle entities, Init teleports and
 * global signal states, Story > Act > ManeuverGroup > Maneuver > Event with SimulationTime /
 * StoryboardElementState / RelativeDistance conditions, speed + FollowTrajectory actions, traffic-signal
 * actions and the custom `VR_TASK` command (real <VRTask> child elements).
 */
import type { Pt } from './types';
import { parseFormula, type TaskSpec } from './formula';

export type Role = 'user' | 'vehicle' | 'walker';

export interface EntityDef {
  name: string;
  role: Role;
  model: string;
  start: { x: number; y: number; h: number };
  bbox: { width: number; length: number; height: number; cx: number; cy: number };
}

export type Rule = 'greaterThan' | 'greaterOrEqual' | 'lessThan' | 'lessOrEqual' | 'equalTo' | 'notEqualTo';

export type ConditionDef =
  | { type: 'time'; value: number; rule: Rule }
  | { type: 'elementState'; element: string; ref: string; state: string }
  | { type: 'relDistance'; value: number; rule: Rule; entity: string; triggering: string[]; freespace: boolean }
  | { type: 'unsupported'; name: string };

export type FailureDef =
  | { type: 'timeout'; initial: number; baseline: number }
  | { type: 'surface'; surface: string }
  | { type: 'trajectory'; tolerance: number; vertices: Pt[] }
  | { type: 'collision'; entities: string[] }
  | { type: 'signal'; crossing: string; signal: string | null }
  | { type: 'trigger'; events: string[] };

export interface TaskDef {
  id: number;
  name: string;
  kind: 'go' | 'cross';
  category: string;
  group: string | null;
  mode: string | null;
  required: boolean;
  eventName: string;
  instruction: Record<string, string>;
  success: Record<string, string>;
  failure: Record<string, string>;
  dependsOn: number[];
  target: { x: number; y: number; feature: string | null; entity: string | null; name: string };
  tolerance: number;
  maxSpeed: number;
  evaluation: string;
  timeout: { initial: number; baseline: number };
  failures: FailureDef[];
  /** formal specification (goal + safety formulas); null for files written before the specification language */
  spec: TaskSpec | null;
}

export type ActionDef =
  | { kind: 'speed'; speed: number }
  | { kind: 'trajectory'; times: number[]; pts: { x: number; y: number; h: number }[] }
  | { kind: 'signal'; name: string; state: string }
  | { kind: 'task'; task: TaskDef };

export interface EventDef {
  name: string;
  story: string;
  act: string;
  actors: string[];
  actions: ActionDef[];
  /** OR of AND-groups (OpenSCENARIO: condition groups are OR'ed, conditions inside one are AND'ed). */
  start: ConditionDef[][];
}

export interface ActDef { name: string; story: string; start: ConditionDef[][] }

export interface ScenarioDef {
  name: string;
  scenarioType: string;
  description: string;
  roadFile: string;
  entities: EntityDef[];
  initSignals: { name: string; state: string }[];
  acts: ActDef[];
  events: EventDef[];
  stop: ConditionDef[][];
  tasks: TaskDef[];
}

// ------------------------------------------------------------------ helpers
const kids = (el: Element | null | undefined, tag: string): Element[] =>
  el ? Array.from(el.children).filter((c) => c.tagName === tag) : [];
const kid = (el: Element | null | undefined, tag: string): Element | null => kids(el, tag)[0] ?? null;
const num = (v: string | null | undefined, d = 0) => (v == null || v === '' ? d : parseFloat(v));
const txt = (el: Element | null | undefined, tag: string, d = '') => kid(el, tag)?.textContent?.trim() ?? d;
const lang = (el: Element | null, tag: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const t of kids(el, tag)) out[t.getAttribute('lang') ?? 'en'] = t.textContent?.trim() ?? '';
  return out;
};

function parseWorldPos(el: Element | null): { x: number; y: number; h: number } | null {
  const wp = el?.querySelector('WorldPosition');
  if (!wp) return null;
  return { x: num(wp.getAttribute('x')), y: num(wp.getAttribute('y')), h: num(wp.getAttribute('h')) };
}

function parseCondition(c: Element): ConditionDef {
  const name = c.getAttribute('name') ?? '';
  const byValue = kid(c, 'ByValueCondition');
  if (byValue) {
    const st = kid(byValue, 'SimulationTimeCondition');
    if (st) return { type: 'time', value: num(st.getAttribute('value')), rule: (st.getAttribute('rule') ?? 'greaterOrEqual') as Rule };
    const se = kid(byValue, 'StoryboardElementStateCondition');
    if (se) return { type: 'elementState', element: se.getAttribute('storyboardElementType') ?? 'event', ref: se.getAttribute('storyboardElementRef') ?? '', state: se.getAttribute('state') ?? '' };
  }
  const byEntity = kid(c, 'ByEntityCondition');
  if (byEntity) {
    const trig = kids(kid(byEntity, 'TriggeringEntities'), 'EntityRef').map((e) => e.getAttribute('entityRef') ?? '');
    const rd = kid(kid(byEntity, 'EntityCondition'), 'RelativeDistanceCondition');
    if (rd) {
      return { type: 'relDistance', value: num(rd.getAttribute('value')), rule: (rd.getAttribute('rule') ?? 'lessThan') as Rule, entity: rd.getAttribute('entityRef') ?? '', triggering: trig, freespace: rd.getAttribute('freespace') === 'true' };
    }
  }
  return { type: 'unsupported', name };
}

function parseTrigger(trigger: Element | null): ConditionDef[][] {
  return kids(trigger, 'ConditionGroup').map((g) => kids(g, 'Condition').map(parseCondition));
}

export function parseTask(el: Element): TaskDef {
  const target = kid(el, 'Target');
  const pos = parseWorldPos(target);
  const feat = target?.querySelector('Feature');
  const cons = kid(el, 'Constraints');
  const failures: FailureDef[] = [];
  const fc = kid(el, 'FailureCondition');
  const timeout = { initial: 60, baseline: 90 };
  for (const f of Array.from(fc?.children ?? [])) {
    switch (f.tagName) {
      case 'InitialTimeoutFailureCondition': timeout.initial = num(f.getAttribute('timeout'), 60); break;
      case 'BaselineTimeoutFailureCondition': timeout.baseline = num(f.getAttribute('timeout'), 90); break;
      case 'SurfaceAdherenceFailureCondition': failures.push({ type: 'surface', surface: f.getAttribute('surface') ?? 'walkable' }); break;
      case 'CollisionFailureCondition': failures.push({ type: 'collision', entities: kids(f, 'EntityRef').map((e) => e.getAttribute('entityRef') ?? '') }); break;
      case 'SignalViolationFailureCondition': failures.push({ type: 'signal', crossing: f.getAttribute('crossing') ?? '', signal: f.getAttribute('signal') }); break;
      case 'TriggerFailureCondition': failures.push({ type: 'trigger', events: kids(f, 'Event').map((e) => e.getAttribute('name') ?? '') }); break;
      case 'FollowTrajectoryFailureCondition':
        failures.push({
          type: 'trajectory', tolerance: num(f.getAttribute('tolerance'), 2),
          vertices: Array.from(f.querySelectorAll('Vertex')).map((v) => { const p = parseWorldPos(v)!; return [p.x, p.y] as Pt; }),
        });
        break;
    }
  }
  const entity = kid(target, 'TaskTargetEntity')?.getAttribute('entity') ?? null;
  const specEl = kid(el, 'Spec');
  const goalEl = kid(kid(specEl, 'Goal'), 'F');
  const spec: TaskSpec | null = specEl && goalEl
    ? { origin: specEl.getAttribute('origin') ?? 'helper', goal: parseFormula(goalEl), safety: kids(kid(specEl, 'Safety'), 'F').map(parseFormula) }
    : null;
  return {
    id: num(el.getAttribute('id')),
    name: el.getAttribute('name') ?? `task_${el.getAttribute('id')}`,
    kind: (txt(kid(el, 'Goal'), 'Type', 'go') as 'go' | 'cross'),
    category: el.getAttribute('category') ?? '',
    group: el.getAttribute('group'),
    mode: el.getAttribute('mode'),
    required: el.getAttribute('required') !== 'false',
    eventName: txt(el, 'EventName'),
    instruction: lang(kid(el, 'Instructions'), 'Text'),
    success: lang(kid(el, 'Feedback'), 'Success'),
    failure: lang(kid(el, 'Feedback'), 'Failure'),
    dependsOn: kids(el, 'DependsOn').map((d) => num(d.getAttribute('task'))),
    target: { x: pos?.x ?? 0, y: pos?.y ?? 0, feature: feat?.getAttribute('id') ?? null, entity, name: txt(kid(el, 'Goal'), 'Target') },
    tolerance: num(kid(cons, 'Tolerance')?.getAttribute('value'), 1.5),
    maxSpeed: num(kid(cons, 'MaxSpeed')?.getAttribute('value'), 3),
    evaluation: txt(cons, 'evaluation', 'proximity'),
    timeout,
    failures,
    spec,
  };
}

function parseActions(ev: Element): ActionDef[] {
  const out: ActionDef[] = [];
  for (const a of kids(ev, 'Action')) {
    const task = a.querySelector('VRTask');
    if (task) { out.push({ kind: 'task', task: parseTask(task) }); continue; }
    const speed = a.querySelector('SpeedAction AbsoluteTargetSpeed');
    if (speed) { out.push({ kind: 'speed', speed: num(speed.getAttribute('value')) }); continue; }
    const traj = a.querySelector('FollowTrajectoryAction');
    if (traj) {
      const times: number[] = [];
      const pts: { x: number; y: number; h: number }[] = [];
      for (const v of Array.from(traj.querySelectorAll('Vertex'))) {
        times.push(num(v.getAttribute('time')));
        pts.push(parseWorldPos(v) ?? { x: 0, y: 0, h: 0 });
      }
      out.push({ kind: 'trajectory', times, pts });
      continue;
    }
    const sig = a.querySelector('TrafficSignalStateAction');
    if (sig) out.push({ kind: 'signal', name: sig.getAttribute('name') ?? '', state: sig.getAttribute('state') ?? '' });
  }
  return out;
}

export function parseXosc(xml: string, doc?: Document): ScenarioDef {
  const d = doc ?? new DOMParser().parseFromString(xml, 'application/xml');
  const err = d.querySelector('parsererror');
  if (err) throw new Error('XOSC parse error: ' + err.textContent?.slice(0, 200));
  const root = d.documentElement;
  const header = kid(root, 'FileHeader');
  const props: Record<string, string> = {};
  for (const p of Array.from(header?.querySelectorAll('Property') ?? [])) props[p.getAttribute('name') ?? ''] = p.getAttribute('value') ?? '';

  const entities: EntityDef[] = [];
  for (const so of kids(kid(root, 'Entities'), 'ScenarioObject')) {
    const name = so.getAttribute('name') ?? '';
    const obj = so.querySelector('Vehicle, Pedestrian');
    if (!obj) continue;
    const roleProp = Array.from(obj.querySelectorAll('Property')).find((p) => p.getAttribute('name') === 'usg_role')?.getAttribute('value');
    const role = (roleProp as Role) ?? (obj.tagName === 'Vehicle' ? 'vehicle' : name === 'User' ? 'user' : 'walker');
    const center = obj.querySelector('BoundingBox Center');
    const dims = obj.querySelector('BoundingBox Dimensions');
    entities.push({
      name, role, model: obj.getAttribute('model3d') ?? '',
      start: { x: 0, y: 0, h: 0 },
      bbox: { width: num(dims?.getAttribute('width'), 0.6), length: num(dims?.getAttribute('length'), 0.6), height: num(dims?.getAttribute('height'), 1.75), cx: num(center?.getAttribute('x')), cy: num(center?.getAttribute('y')) },
    });
  }

  const sb = kid(root, 'Storyboard');
  const init = kid(sb, 'Init');
  const initSignals: { name: string; state: string }[] = [];
  for (const s of Array.from(init?.querySelectorAll('GlobalAction TrafficSignalStateAction') ?? [])) {
    initSignals.push({ name: s.getAttribute('name') ?? '', state: s.getAttribute('state') ?? '' });
  }
  for (const pr of Array.from(init?.querySelectorAll('Private') ?? [])) {
    const ent = entities.find((e) => e.name === pr.getAttribute('entityRef'));
    const pos = parseWorldPos(pr.querySelector('TeleportAction'));
    if (ent && pos) ent.start = pos;
  }

  const acts: ActDef[] = [];
  const events: EventDef[] = [];
  const tasks: TaskDef[] = [];
  for (const story of kids(sb, 'Story')) {
    const sName = story.getAttribute('name') ?? '';
    for (const act of kids(story, 'Act')) {
      const aName = act.getAttribute('name') ?? '';
      acts.push({ name: aName, story: sName, start: parseTrigger(kid(act, 'StartTrigger')) });
      for (const mg of kids(act, 'ManeuverGroup')) {
        const actors = kids(kid(mg, 'Actors'), 'EntityRef').map((e) => e.getAttribute('entityRef') ?? '');
        for (const man of kids(mg, 'Maneuver')) {
          for (const ev of kids(man, 'Event')) {
            const actions = parseActions(ev);
            for (const a of actions) if (a.kind === 'task') tasks.push(a.task);
            events.push({ name: ev.getAttribute('name') ?? '', story: sName, act: aName, actors, actions, start: parseTrigger(kid(ev, 'StartTrigger')) });
          }
        }
      }
    }
  }
  tasks.sort((a, b) => a.id - b.id);
  return {
    name: header?.getAttribute('description') ?? 'scenario',
    scenarioType: props['usg_scenario_type'] ?? '',
    description: props['usg_description'] ?? '',
    roadFile: kid(kid(root, 'RoadNetwork'), 'LogicFile')?.getAttribute('filepath') ?? '',
    entities, initSignals, acts, events, tasks,
    stop: parseTrigger(kid(sb, 'StopTrigger')),
  };
}
