import { defineConfig, devices } from '../support/playwright';

const FRONTEND_DEFAULTS: Record<string, string> = {
  preview: 'https://green-sentinel.vercel.app',
  dev: 'https://green-sentinel-dev.vercel.app',
  staging: 'https://green-sentinel-staging.vercel.app',
  prod: 'https://green-sentinel.vercel.app',
};

function resolveFrontendURL(): string {
  if (process.env.AUTH_E2E_FRONTEND_URL) return process.env.AUTH_E2E_FRONTEND_URL;
  const raw = (process.env.E2E_TARGET_ENV || 'preview').toLowerCase();
  const env = raw === 'production' ? 'prod' : raw;
  return FRONTEND_DEFAULTS[env] || FRONTEND_DEFAULTS.preview;
}

export default defineConfig({
  testDir: '.',
  timeout: 180_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: resolveFrontendURL(),
    ...devices['Desktop Chrome'],
    // Auth headers and Clerk tickets can be present in traces/screenshots.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
