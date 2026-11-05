import { expect, test } from '../support/playwright';
import {
  backendURL,
  realApiStatus,
  requireRealAccountE2E,
  signInWithRole,
} from './role-accounts';

test.describe('real role accounts on hosted environments (no fixtures)', () => {
  test.beforeEach(() => {
    if (process.env.RUN_REAL_ACCOUNT_E2E !== 'true') {
      test.skip(true, 'opt in with RUN_REAL_ACCOUNT_E2E=true');
    }
    requireRealAccountE2E();
  });

  test('analyst opens a real triage queue and real case workspace', async ({ page }) => {
    await signInWithRole(page, 'analyst');
    expect(await realApiStatus(page, '/api/v1/me')).toBe(200);
    expect(await realApiStatus(page, '/api/v1/cases?availability=available')).toBe(200);

    await page.goto('/workplace', { waitUntil: 'domcontentloaded' });
    const triageQueue = page.getByRole('region', { name: 'Triage queue' });
    await expect(triageQueue).toBeVisible({ timeout: 30_000 });

    // Real data: click the first real case without asserting fixture names.
    const caseButton = triageQueue.locator('button[aria-pressed]').first();
    const emptyQueue = triageQueue.getByText(/no available cases|no processed cases/i);
    await expect(caseButton.or(emptyQueue)).toBeVisible({ timeout: 30_000 });

    if (await caseButton.isVisible()) {
      await caseButton.click();
      await expect(page.getByRole('tab', { name: /overview|conversation/i }).first()).toBeVisible({
        timeout: 30_000,
      });
    }

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('region', { name: 'Triage queue' })).toBeVisible({ timeout: 30_000 });
    expect(await realApiStatus(page, '/api/v1/me')).toBe(200);
    expect(backendURL().length).toBeGreaterThan(0);
  });

  test('driver opens real dispute cases with real clicks', async ({ page }) => {
    await signInWithRole(page, 'driver');
    expect(await realApiStatus(page, '/api/v1/me')).toBe(200);

    await page.goto('/driver', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 30_000 });

    const firstCase = page.locator('a[href*="/driver/dispute/"], button').first();
    if (await firstCase.count()) {
      await firstCase.click();
      await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 15_000 });
    }
  });

  test('admin keeps analyst and driver area access', async ({ page }) => {
    await signInWithRole(page, 'admin');
    expect(await realApiStatus(page, '/api/v1/me')).toBe(200);

    await page.goto('/workplace', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 30_000 });

    await page.goto('/driver', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 30_000 });
  });
});
