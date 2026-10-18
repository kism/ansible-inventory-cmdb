import { defineConfig } from 'vite'

// Root, public/ and dist/ are all this directory's, from `vite build frontend` / `vite frontend` (pnpm build,
// pnpm frontend). The dev server has no API of its own: /api goes to the web app, which needs to be running.
export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:5100' } },
})
