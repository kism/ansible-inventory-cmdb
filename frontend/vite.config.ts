import { defineConfig } from 'vitest/config'

// Root, public/ and dist/ are all this directory's, from `vite build frontend` / `vite frontend` (pnpm build,
// pnpm dev), and `vitest --root frontend` (pnpm test). The dev server has no API of its own: /api goes to the web
// app, which needs to be running.
export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:5100' } },
  test: {
    // lcov for Codecov, next to the Python's coverage.xml; text for the terminal.
    coverage: { provider: 'v8', include: ['src/**/*.ts'], reporter: ['text', 'lcov'] },
  },
})
