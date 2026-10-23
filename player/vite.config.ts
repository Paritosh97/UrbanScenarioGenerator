import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// The build lands INSIDE the Python package, so `pip install` users get the player without needing Node.
// base './' lets the Gradio server mount it at /player/ (or any other path).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: resolve(import.meta.dirname, '../src/usg/player_dist'),
    emptyOutDir: true,
    target: 'es2022',
    chunkSizeWarningLimit: 4000,
  },
  server: { host: true },
  test: { environment: 'node', testTimeout: 60000 },
});
