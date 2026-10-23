import type { EventView, Simulation } from '../runtime/sim';
import { describe } from '../runtime/formula';

export interface HudTask { id: number; text: string; status: string; reason: string; remaining: number; slow: boolean; distance: number; category: string }
export interface HudSnapshot {
  time: number;
  tasks: HudTask[];
  toast: { text: string; kind: string } | null;
  finished: boolean;
  outcome: string;
}

export interface InspectorData {
  time: number;
  user: { x: number; y: number; heading: number; surface: string };
  entities: { name: string; role: string; x: number; y: number; speed: number; model: string }[];
  signals: { name: string; state: string }[];
  events: EventView[];
  log: { t: number; what: string }[];
  /** each active/finished task's formal specification with its live robustness margins (metres, degrees, m/s) */
  specs: { id: number; name: string; status: string; goal: string; safety: string[]; goalMargin: number | null; safetyMargin: number | null }[];
}

/** Plain-data view of the simulation for the React HUD (the sim itself is mutable and per-frame). */
export function snapshot(sim: Simulation): HudSnapshot {
  const tasks: HudTask[] = sim.tasks.map((t) => ({
    id: t.def.id, text: sim.taskText(t), status: t.status, reason: t.reason, category: t.def.category,
    remaining: t.tStart == null ? t.def.timeout.baseline : Math.max(0, t.def.timeout.baseline - (sim.time - t.tStart)),
    slow: t.slow, distance: Number.isFinite(t.distance) ? t.distance : 0,
  }));
  const last = sim.messages[sim.messages.length - 1];
  const toast = last && sim.time - last.t < 4 ? { text: last.text, kind: last.kind } : null;
  return { time: sim.time, tasks, toast, finished: sim.finished, outcome: sim.outcome };
}

/** What the inspector shows: the REAL player position, task state and the running OpenSCENARIO elements. */
export function inspect(sim: Simulation): InspectorData {
  return {
    time: sim.time,
    user: { x: sim.user[0], y: sim.user[1], heading: sim.userHeading, surface: sim.surface.at(sim.user) },
    entities: [...sim.entities.values()].filter((e) => e.def.role !== 'user')
      .map((e) => ({ name: e.def.name, role: e.def.role, model: e.def.model, x: e.x, y: e.y, speed: e.speed })),
    signals: [...sim.signals].map(([name, state]) => ({ name, state })),
    events: sim.eventViews(),
    log: sim.eventLog.slice(-8),
    specs: sim.tasks.filter((t) => t.def.spec && t.status !== 'pending').map((t) => ({
      id: t.def.id, name: t.def.name, status: t.status, goal: describe(t.def.spec!.goal),
      safety: t.def.spec!.safety.map((f) => f.label ?? describe(f)), goalMargin: t.goalMargin, safetyMargin: t.safetyMargin,
    })),
  };
}
