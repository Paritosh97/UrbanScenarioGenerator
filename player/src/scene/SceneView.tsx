import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { PointerLockControls, Sky, Text } from '@react-three/drei';
import { XR, XROrigin, createXRStore, useXR, useXRControllerLocomotion } from '@react-three/xr';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import type { PointerLockControls as PLC } from 'three/examples/jsm/controls/PointerLockControls.js';
import type { ScenarioPackage } from '../runtime/types';
import { parseXosc } from '../runtime/xosc';
import { Simulation, type SimLog } from '../runtime/sim';
import { buildWorld, setSignalLamps } from './world';
import { applyGltfOverrides } from './props';
import { makeEntity, makeTaskMarkers } from './entities';
import { inspect, snapshot, type HudSnapshot, type InspectorData } from './snapshot';

/** Dev/test hook: window.__usg exposes the live sim and camera for browser-driven checks. */
function debugHandle(o: object): void {
  const w = window as unknown as { __usg?: object };
  w.__usg = Object.assign(w.__usg ?? {}, o);
}

const EYE = 1.65;
const WALK = 1.6;

export type Phase = 'ready' | 'running';

interface Props {
  pkg: ScenarioPackage;
  onExit?: () => void;
  onFinished?: (log: SimLog) => void;
}

export function SceneView({ pkg, onExit, onFinished }: Props) {
  const def = useMemo(() => parseXosc(pkg.xosc), [pkg]);
  const [runKey, setRunKey] = useState(0);
  const sim = useMemo(() => new Simulation(pkg.map, def), [pkg, def, runKey]);       // eslint-disable-line react-hooks/exhaustive-deps
  const store = useMemo(() => createXRStore({ foveation: 0, frameRate: 'high', emulate: new URLSearchParams(location.search).has('emulate') ? 'metaQuest3' : false }), []);
  const [phase, setPhase] = useState<Phase>('ready');
  const [snap, setSnap] = useState<HudSnapshot>(() => snapshot(sim));
  const [insp, setInsp] = useState<InspectorData>(() => inspect(sim));
  const [showInspector, setShowInspector] = useState(true);
  const [locked, setLocked] = useState(false);
  const [vrSupported, setVrSupported] = useState<boolean | null>(null);
  const reportedRef = useRef(false);
  const lockRef = useRef<PLC | null>(null);
  const free = useMemo(() => new URLSearchParams(location.search).has('free'), []);   // test mode: no pointer lock

  useEffect(() => { setPhase('ready'); setSnap(snapshot(sim)); setInsp(inspect(sim)); reportedRef.current = false; debugHandle({ sim }); }, [sim]);
  useEffect(() => {
    if (!navigator.xr) { setVrSupported(false); return; }
    navigator.xr.isSessionSupported('immersive-vr').then(setVrSupported).catch(() => setVrSupported(false));
  }, []);
  useEffect(() => {
    if (snap.finished && !reportedRef.current) { reportedRef.current = true; onFinished?.(sim.results()); }
  }, [snap.finished, onFinished, sim]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.code === 'KeyI') setShowInspector((v) => !v); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const start = def.entities.find((e) => e.role === 'user')!.start;
  const yaw = start.h - Math.PI / 2;

  const download = () => {
    const blob = new Blob([JSON.stringify(sim.results(), null, 1)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${(def.name || 'scenario').replace(/\W+/g, '_')}_results.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <Canvas shadows={false} camera={{ fov: 70, near: 0.05, far: 2000, position: [start.x, EYE, -start.y], rotation: [0, yaw, 0] }} gl={{ antialias: true }}>
        <XR store={store}>
          <World pkg={pkg} sim={sim} phase={phase} locked={locked || (free && phase === 'running')} onSnap={setSnap} onInspect={setInsp}
            startYaw={yaw} start={start} />
          {!free && <DesktopLook lockRef={lockRef} onLock={setLocked} />}
        </XR>
      </Canvas>

      <DomHud snap={snap} insp={insp} showInspector={showInspector} onToggleInspector={() => setShowInspector((v) => !v)}
        phase={phase} locked={locked || free} vrSupported={vrSupported} scenarioName={def.name} scenarioType={def.scenarioType}
        onStart={() => { setPhase('running'); lockRef.current?.lock(); }}
        onResume={() => lockRef.current?.lock()}
        onEnterVR={() => { setPhase('running'); void store.enterVR(); }}
        onRestart={() => setRunKey((k) => k + 1)} onDownload={download} onExit={onExit} />
    </div>
  );
}

// ------------------------------------------------------------------ in-canvas
function DesktopLook({ lockRef, onLock }: { lockRef: React.MutableRefObject<PLC | null>; onLock: (b: boolean) => void }) {
  const session = useXR((s) => s.session);
  if (session) return null;
  return <PointerLockControls ref={lockRef as never} onLock={() => onLock(true)} onUnlock={() => onLock(false)} />;
}

interface WorldProps {
  pkg: ScenarioPackage; sim: Simulation; phase: Phase; locked: boolean; onSnap: (s: HudSnapshot) => void;
  onInspect: (d: InspectorData) => void; startYaw: number; start: { x: number; y: number; h: number };
}

function World({ pkg, sim, phase, locked, onSnap, onInspect, startYaw, start }: WorldProps) {
  const { camera, gl } = useThree();
  const session = useXR((s) => s.session);
  const originRef = useRef<THREE.Group>(null);
  const keys = useRef<Record<string, boolean>>({});
  const [countdown, setCountdown] = useState<number | null>(null);

  const signalNames = useMemo(() => {
    const names = new Set<string>(sim.def.initSignals.map((s) => s.name));
    for (const ev of sim.def.events) for (const a of ev.actions) if (a.kind === 'signal') names.add(a.name);
    return [...names];
  }, [sim]);
  const world = useMemo(() => buildWorld(pkg.map, signalNames), [pkg, signalNames]);
  const entityObjs = useMemo(() => {
    const m = new Map<string, THREE.Object3D>();
    for (const e of sim.def.entities) m.set(e.name, makeEntity(e));
    return m;
  }, [sim]);
  const markers = useMemo(() => makeTaskMarkers(sim.def.tasks), [sim]);

  useEffect(() => { void applyGltfOverrides(world.group, new URL('./', location.href).href); }, [world]);
  useEffect(() => { debugHandle({ camera, entityObjs }); }, [camera, entityObjs]);

  // reset the desktop camera on (re)start
  useEffect(() => {
    if (!session) { camera.position.set(start.x, EYE, -start.y); camera.rotation.set(0, startYaw, 0, 'YXZ'); }
  }, [sim, session, camera, start, startYaw]);

  // headset: short countdown before the clock starts
  useEffect(() => {
    if (session && phase === 'running') { setCountdown(4); const t = setInterval(() => setCountdown((c) => (c == null || c <= 0 ? null : c - 1)), 1000); return () => clearInterval(t); }
    setCountdown(null);
  }, [session, phase]);

  useEffect(() => {
    const d = (e: KeyboardEvent) => { keys.current[e.code] = true; };
    const u = (e: KeyboardEvent) => { keys.current[e.code] = false; };
    window.addEventListener('keydown', d); window.addEventListener('keyup', u);
    return () => { window.removeEventListener('keydown', d); window.removeEventListener('keyup', u); };
  }, []);

  useXRControllerLocomotion(originRef, { speed: WALK }, { type: 'snap', degrees: 30 }, 'left');

  const tmp = useMemo(() => ({ p: new THREE.Vector3(), d: new THREE.Vector3(), f: new THREE.Vector3(), r: new THREE.Vector3() }), []);
  const acc = useRef(0);
  const lastKey = useRef('');

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1);
    const presenting = gl.xr.isPresenting;

    // ---- desktop movement (WASD): this is the player walking, not a script
    if (!presenting && phase === 'running' && locked) {
      const k = keys.current;
      const sp = (k['ShiftLeft'] ? 2.6 : WALK) * dt;
      camera.getWorldDirection(tmp.f); tmp.f.y = 0; tmp.f.normalize();
      tmp.r.crossVectors(tmp.f, camera.up).normalize();
      if (k['KeyW'] || k['ArrowUp']) camera.position.addScaledVector(tmp.f, sp);
      if (k['KeyS'] || k['ArrowDown']) camera.position.addScaledVector(tmp.f, -sp);
      if (k['KeyD'] || k['ArrowRight']) camera.position.addScaledVector(tmp.r, sp);
      if (k['KeyA'] || k['ArrowLeft']) camera.position.addScaledVector(tmp.r, -sp);
      camera.position.y = EYE;
    }

    // ---- head -> the ego pedestrian's position in map coordinates
    const cam = presenting ? gl.xr.getCamera() : camera;
    cam.getWorldPosition(tmp.p);
    cam.getWorldDirection(tmp.d);
    sim.setUser(tmp.p.x, -tmp.p.z, Math.atan2(-tmp.d.z, tmp.d.x));

    const running = phase === 'running' && (presenting ? countdown == null : locked);
    if (running) sim.step(dt);

    // ---- push sim state into the scene
    for (const [name, e] of sim.entities) {
      const o = entityObjs.get(name);
      if (!o) continue;
      if (e.def.role === 'user') o.position.set(sim.user[0], 0, -sim.user[1]);
      else { o.position.set(e.x, 0, -e.y); o.rotation.y = e.h; }
    }
    const t = state.clock.elapsedTime;
    for (const m of markers) { m.group.visible = sim.tasks.find((x) => x.def.id === m.task.id)?.status === 'active'; m.update(t); }
    setSignalLamps(world.signalLamps, sim.signals);

    acc.current += dt;
    if (acc.current > 0.25) {
      acc.current = 0;
      const s = snapshot(sim);
      const key = `${s.finished}|${s.outcome}|${s.tasks.map((x) => x.status + x.slow + Math.round(x.remaining)).join(',')}|${s.toast?.text}`;
      if (key !== lastKey.current) { lastKey.current = key; onSnap(s); }
      onInspect(inspect(sim));
    }
  });

  return (
    <>
      <color attach="background" args={['#9fc4e8']} />
      <fog attach="fog" args={['#9fc4e8', 120, 520]} />
      <Sky sunPosition={[80, 60, 40]} turbidity={6} rayleigh={1.2} />
      <hemisphereLight args={['#dfeaff', '#6d7660', 0.9]} />
      <directionalLight position={[60, 90, 40]} intensity={1.6} />
      <primitive object={world.group} />
      {[...entityObjs.values()].map((o) => <primitive key={o.uuid} object={o} />)}
      {markers.map((m) => <primitive key={m.group.uuid} object={m.group} />)}
      <XROrigin ref={originRef} position={[start.x, 0, -start.y]} rotation={[0, startYaw, 0]} />
      {session && <VrHud sim={sim} countdown={countdown} />}
    </>
  );
}

/** Head-locked in-world HUD for headsets (DOM overlays are not visible in immersive sessions). */
function VrHud({ sim, countdown }: { sim: Simulation; countdown: number | null }) {
  const group = useRef<THREE.Group>(null);
  const { gl } = useThree();
  const [text, setText] = useState('');

  useFrame((_, dt) => {
    const g = group.current;
    if (!g) return;
    const cam = gl.xr.getCamera();
    const p = new THREE.Vector3(), d = new THREE.Vector3();
    cam.getWorldPosition(p); cam.getWorldDirection(d); d.y = 0; d.normalize();
    const target = p.clone().addScaledVector(d, 1.5); target.y = p.y - 0.28;
    g.position.lerp(target, Math.min(1, dt * 4));
    g.lookAt(p.x, g.position.y, p.z);
    g.rotateY(Math.PI);
    const s = snapshot(sim);
    const lines: string[] = [];
    if (countdown != null) lines.push(countdown > 0 ? `Get ready... ${countdown}` : 'Go!');
    else if (s.finished) lines.push(s.outcome === 'success' ? 'All tasks complete!' : 'Session over');
    else for (const t of s.tasks.filter((x) => x.status === 'active')) lines.push(`${t.text}  (${Math.ceil(t.remaining)}s)`);
    if (s.toast) lines.push(s.toast.text);
    const joined = lines.join('\n');
    setText((prev) => (prev === joined ? prev : joined));
  });

  return (
    <group ref={group}>
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[1.5, 0.42]} />
        <meshBasicMaterial color="#10151c" transparent opacity={0.72} />
      </mesh>
      <Text fontSize={0.07} maxWidth={1.4} color="#ffffff" anchorX="center" anchorY="middle" textAlign="center">{text}</Text>
    </group>
  );
}

// ------------------------------------------------------------------ DOM overlay (desktop)
interface DomProps {
  snap: HudSnapshot; insp: InspectorData; showInspector: boolean; onToggleInspector: () => void;
  phase: Phase; locked: boolean; vrSupported: boolean | null; scenarioName: string; scenarioType: string;
  onStart: () => void; onResume: () => void; onEnterVR: () => void; onRestart: () => void; onDownload: () => void; onExit?: () => void;
}

function DomHud(p: DomProps) {
  const { snap, insp } = p;
  const toastColor: Record<string, string> = { success: '#3ddc84', failure: '#ff6b6b', hint: '#ffd166', info: '#e6edf3' };
  return (
    <div className="hud">
      <div className="hud-top">
        {p.onExit && <button className="btn ghost" onClick={p.onExit}>Back</button>}
        <div className="hud-tasks">
          {snap.tasks.map((t) => (
            <div key={t.id} className={`hud-task ${t.status}`}>
              <span className="dot" />
              <span className="txt">{t.text}</span>
              {t.status === 'active' && <span className={`timer ${t.slow ? 'slow' : ''}`}>{Math.ceil(t.remaining)}s · {t.distance.toFixed(0)} m</span>}
              {t.status !== 'active' && t.status !== 'pending' && <span className="timer">{t.status}{t.reason && t.reason !== 'ok' ? `: ${t.reason}` : ''}</span>}
            </div>
          ))}
        </div>
        <button className="btn ghost small" onClick={p.onToggleInspector} title="Toggle the inspector (I)">Inspector</button>
      </div>

      {p.showInspector && <Inspector insp={insp} />}

      {snap.toast && <div className="toast" style={{ borderColor: toastColor[snap.toast.kind] }}>{snap.toast.text}</div>}

      {p.phase === 'ready' && (
        <div className="overlay">
          <h2>{p.scenarioName}</h2>
          <p className="muted">{p.scenarioType}</p>
          <p>You are the pedestrian. Walk with <b>W A S D</b>, look with the mouse, <b>Shift</b> to hurry, <b>I</b> toggles the inspector.
            In a headset: walk physically, left stick to move, right stick to turn.</p>
          <div className="row">
            <button className="btn primary" onClick={p.vrSupported ? p.onEnterVR : p.onStart}>{p.vrSupported ? 'Enter VR' : 'Start (first person)'}</button>
            {p.vrSupported && <button className="btn" onClick={p.onStart}>Start on desktop</button>}
          </div>
          {p.vrSupported === false && <p className="muted">No VR headset detected, so this runs in first-person desktop mode.</p>}
        </div>
      )}
      {p.phase === 'running' && !p.locked && !snap.finished && (
        <div className="overlay light" onClick={p.onResume}><p>Click the scene to {snap.time > 0 ? 'resume' : 'begin'} (Esc pauses).</p></div>
      )}
      {snap.finished && (
        <div className="overlay">
          <h2>{snap.outcome === 'success' ? 'Scenario complete' : snap.outcome === 'timeout' ? 'Time is up' : 'Scenario failed'}</h2>
          <ul className="results">
            {snap.tasks.map((t) => <li key={t.id} className={t.status}>{t.status}{t.reason && t.reason !== 'ok' ? ` (${t.reason})` : ''}: {t.text}</li>)}
          </ul>
          <div className="row">
            <button className="btn primary" onClick={p.onRestart}>Try again</button>
            <button className="btn" onClick={p.onDownload}>Download results (JSON)</button>
            {p.onExit && <button className="btn" onClick={p.onExit}>Back</button>}
          </div>
        </div>
      )}
    </div>
  );
}

/** Live view of the player, the tasks and the running OpenSCENARIO elements. Observation only. */
function Inspector({ insp }: { insp: InspectorData }) {
  const running = insp.events.filter((e) => e.phase === 'running');
  const waiting = insp.events.filter((e) => e.phase === 'standby');
  const done = insp.events.filter((e) => e.phase === 'complete');
  return (
    <div className="inspector">
      <h3>You (ego pedestrian)</h3>
      <div className="kv"><span>position</span><b>{insp.user.x.toFixed(1)}, {insp.user.y.toFixed(1)} m</b></div>
      <div className="kv"><span>standing on</span><b>{insp.user.surface}</b></div>
      <div className="kv"><span>scenario time</span><b>{insp.time.toFixed(1)} s</b></div>

      {insp.specs.length > 0 && <h3>Task specifications (live margins)</h3>}
      {insp.specs.map((t) => (
        <div key={t.id} className={`ev ${t.status}`}>
          <b>{t.name}</b> <span className="muted">· {t.status}</span><br />
          <span className="muted">goal</span> {t.goal.length > 120 ? t.goal.slice(0, 117) + '...' : t.goal}
          {t.goalMargin !== null && <span className="muted"> · margin {Math.abs(t.goalMargin) > 1e8 ? (t.goalMargin > 0 ? 'inf' : '-inf') : t.goalMargin.toFixed(2)}</span>}
          {t.safety.map((r, i) => <div key={i} className="muted">rule: {r}</div>)}
          {t.safetyMargin !== null && <span className="muted">tightest rule margin {Math.abs(t.safetyMargin) > 1e8 ? 'inf' : t.safetyMargin.toFixed(2)}</span>}
        </div>
      ))}

      <h3>Running OpenSCENARIO elements</h3>
      {running.length === 0 && <div className="muted">none</div>}
      {running.map((e) => (
        <div key={e.name} className="ev running"><b>{e.name}</b><span className="muted"> · {e.actors.join(', ')}</span><br />{e.actions.join(' · ')}</div>
      ))}
      {waiting.length > 0 && <h3>Waiting for a trigger</h3>}
      {waiting.map((e) => <div key={e.name} className="ev"><b>{e.name}</b><span className="muted"> · waits for {e.waitingFor}</span></div>)}
      {done.length > 0 && <h3>Completed ({done.length})</h3>}
      {done.map((e) => <div key={e.name} className="ev done">{e.name}</div>)}

      {insp.entities.length > 0 && <h3>Vehicles and walkers</h3>}
      {insp.entities.map((e) => (
        <div key={e.name} className="kv"><span>{e.name} <span className="muted">({e.model})</span></span>
          <b>{e.x.toFixed(0)}, {e.y.toFixed(0)} · {(e.speed * 3.6).toFixed(0)} km/h</b></div>
      ))}
      {insp.signals.length > 0 && <h3>Signals</h3>}
      {insp.signals.map((s) => <div key={s.name} className="kv"><span>{s.name}</span><b className={`sig ${s.state}`}>{s.state}</b></div>)}
    </div>
  );
}
