import { defineConfig } from '@playwright/test'

// Runs against the dev server, which shows the sample domain, in the Chrome already installed on this machine.
export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: 'http://localhost:5199', channel: 'chrome' },
  webServer: { command: 'npx vite --port 5199 --strictPort', url: 'http://localhost:5199', reuseExistingServer: false },
})
