import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  use: { baseURL: 'http://127.0.0.1:43719', browserName: 'chromium' },
  webServer: {
    command: 'pnpm dev --host 127.0.0.1 --port 43719 --strictPort',
    url: 'http://127.0.0.1:43719',
    reuseExistingServer: false,
    env: { PULSE_FIXTURES_DIR: resolve(import.meta.dirname, 'tests/fixtures/exports') },
  },
})
