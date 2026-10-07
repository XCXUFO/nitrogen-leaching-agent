import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 60000,
  reporter: [['list']], outputDir: '/tmp/nitrogen-browser-results',
  use: { baseURL: process.env.UI_BASE_URL ?? 'http://localhost:3000', headless: true,
    screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
