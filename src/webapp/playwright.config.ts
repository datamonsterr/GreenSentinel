import { defineConfig, devices } from '@playwright/test';
import { execSync } from 'child_process';

type PlaywrightPortEnv = Partial<Pick<NodeJS.ProcessEnv, 'PORT' | 'PLAYWRIGHT_TEST_BASE_URL' | 'CI'>>;

export function resolvePort(env: PlaywrightPortEnv = process.env as PlaywrightPortEnv): string {
  if (env.PORT) {
    return env.PORT;
  }
  if (env.PLAYWRIGHT_TEST_BASE_URL) {
    try {
      const parsed = new URL(env.PLAYWRIGHT_TEST_BASE_URL);
      if (parsed.port) return parsed.port;
    } catch {
      // ignore invalid URL
    }
  }
  // In non-CI local development, default to 3000 to preserve normal developer workflow (e.g. pnpm dev on :3000)
  if (!env.CI) {
    return '3000';
  }
  // In CI environments where PORT was not explicitly passed, dynamically find an available port
  try {
    const freePort = execSync(
      "node -e 'const s=require(\"net\").createServer();s.listen(0,()=>{console.log(s.address().port);s.close();})'",
      { encoding: 'utf8' }
    ).trim();
    if (freePort) return freePort;
  } catch {
    // fallback
  }
  return '3100';
}

const PORT = resolvePort();
process.env.PORT = PORT;
const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL || `http://localhost:${PORT}`;
process.env.PLAYWRIGHT_TEST_BASE_URL = baseURL;

export default defineConfig({
  testDir: '../../tests/e2e/browser',
  timeout: process.env.CI ? 60 * 1000 : 45 * 1000,
  expect: {
    timeout: process.env.CI ? 15 * 1000 : 10 * 1000,
  },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    actionTimeout: 15 * 1000,
    navigationTimeout: 30 * 1000,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  testIgnore: ['**/*persisted.spec.ts'],
  webServer: [
    {
      command:
        process.env.PLAYWRIGHT_SERVER_MODE === 'start'
          ? `APP_ENV=test TEST_AUTH_ENABLED=true E2E_TEST=true NEXT_PUBLIC_E2E_TEST=true NEXT_PUBLIC_GIS_OPTIMIZED_TEST=true NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 ./node_modules/.bin/next start -p ${PORT}`
          : `APP_ENV=test TEST_AUTH_ENABLED=true E2E_TEST=true NEXT_PUBLIC_E2E_TEST=true ./node_modules/.bin/next dev --webpack -p ${PORT}`,
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
      cwd: __dirname,
    },
  ],
});
