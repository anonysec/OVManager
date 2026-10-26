import { defineConfig } from '@playwright/test';

const baseURL = process.env.OVM_E2E_URL || 'https://127.0.0.1:2095/dashboard/';

export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: baseURL.endsWith('/') ? baseURL : `${baseURL}/`,
    headless: true,
    ignoreHTTPSErrors: true,
  },
  reporter: 'list',
});
