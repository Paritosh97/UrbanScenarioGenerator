import { createRoot } from 'react-dom/client';
import { useEffect, useState } from 'react';
import './styles.css';
import { SceneView } from './scene/SceneView';
import type { ScenarioPackage } from './runtime/types';

/**
 * Standalone player. The Gradio app opens it as  /player/#/play?pkg=/packages/<token>.json
 * A package can also be dropped onto the page (a .usgscene.json downloaded from the app).
 */
function packageUrl(): string | null {
  const hash = location.hash.split('?')[1] ?? '';
  return new URLSearchParams(hash).get('pkg') ?? new URLSearchParams(location.search).get('pkg');
}

function Player() {
  const [pkg, setPkg] = useState<ScenarioPackage | null>(null);
  const [error, setError] = useState('');

  const accept = (p: ScenarioPackage) => {
    if (p.format !== 'usg-scenario-package/1') throw new Error('this is not a scenario package');
    setPkg(p);
  };

  useEffect(() => {
    const url = packageUrl();
    if (!url) return;
    fetch(url).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }).then(accept)
      .catch((e) => setError(`Could not load the scenario: ${e.message}`));
  }, []);

  if (pkg) return <div className="fullscreen"><SceneView pkg={pkg} /></div>;
  return (
    <div className="page"
      onDragOver={(e) => e.preventDefault()}
      onDrop={async (e) => {
        e.preventDefault();
        const f = e.dataTransfer.files[0];
        if (f) { try { accept(JSON.parse(await f.text())); } catch (err) { setError((err as Error).message); } }
      }}>
      <h1>Urban Scenario Player</h1>
      {packageUrl() && !error ? <p className="muted">Loading the scenario…</p> : (
        <>
          <p>Open a scenario from the generator (the <b>Open in WebVR</b> button), or drop a <code>.usgscene.json</code> file here.</p>
          <input type="file" accept=".json,application/json" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) { try { accept(JSON.parse(await f.text())); } catch (err) { setError((err as Error).message); } }
          }} />
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<Player />);
