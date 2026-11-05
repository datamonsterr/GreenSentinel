import { defineConfig, devices } from '@playwright/test';

if (!process.env.ISSUE61_DATABASE_URL || !process.env.API_BASE_URL) {
  throw new Error("Local API/database prerequisites are unset or inconsistent for persisted tests.");
}

const backendPort = process.env.GIS_BACKEND_PORT || '18662';
const frontendPort = process.env.GIS_FRONTEND_PORT || '3162';
const expectedApi = `http://127.0.0.1:${backendPort}`;
const expectedFrontend = `http://127.0.0.1:${frontendPort}`;
if (process.env.API_BASE_URL.replace(/\/$/, '') !== expectedApi) {
  throw new Error(`API_BASE_URL must be ${expectedApi} for persisted tests.`);
}
if (process.env.PLAYWRIGHT_TEST_BASE_URL && process.env.PLAYWRIGHT_TEST_BASE_URL.replace(/\/$/, '') !== expectedFrontend) {
  throw new Error(`PLAYWRIGHT_TEST_BASE_URL must be ${expectedFrontend} for persisted tests.`);
}
const baseURL = expectedFrontend;

export default defineConfig({
  testDir: '../../tests/e2e/browser',
  testMatch: 'gis-persisted.spec.ts',
  timeout: 45 * 1000,
  expect: {
    timeout: 10 * 1000,
  },
  fullyParallel: false,
  // Shared self-hosted runners add timing noise to the p95 selection-budget
  // spec (gis-persisted.spec.ts:675); one CI retry absorbs a single transient
  // overrun while a real regression still fails twice. Local runs stay strict.
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  outputDir: '../../artifacts/gis-persisted/test-results',
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../../artifacts/gis-persisted/playwright-report' }]],
  forbidOnly: true,
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // Separate optimized test artifact, bound to loopback with an isolated API.
      command: `APP_ENV=test TEST_AUTH_ENABLED=true API_BASE_URL=${expectedApi} NEXT_PUBLIC_API_URL=${expectedApi} NEXT_PUBLIC_GIS_OPTIMIZED_TEST=true E2E_TEST=true NEXT_PUBLIC_E2E_TEST=true sh -c './node_modules/.bin/next build --webpack && ./node_modules/.bin/next start --hostname 127.0.0.1 -p ${frontendPort}'`,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 300 * 1000,
      cwd: __dirname,
    },
  ],
});
