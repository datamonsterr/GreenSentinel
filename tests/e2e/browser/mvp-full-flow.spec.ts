import { test, expect } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

test.describe('POC v1 workspace', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
    await page.goto('/workplace');
    await page.waitForLoadState('domcontentloaded');
  });

  test('loads a real API shaped queue and case workspace', async ({ page }) => {
    await expect(page.getByRole('region', { name: 'Triage queue' })).toBeVisible();
    await expect(page.getByText('Nguyen Hung').first()).toBeVisible();
    await page.getByRole('button', { name: /P1 · #/ }).click();
    await expect(page.getByRole('tabpanel', { name: 'Overview', exact: true }).getByText('12 Le Loi, Ba Dinh')).toBeVisible();
    await page.getByRole('tab', { name: 'Customer', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Customer', exact: true })).toBeVisible();
  });

  test('supports map controls and compact Copilot streaming states', async ({ page }) => {
    await page.getByRole('button', { name: 'Claim', exact: true }).click();
    await page.getByRole('tab', { name: 'Maps', exact: true }).click();
    await expect(page.locator('#panel-maps')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Center whole trip', exact: true })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Analyst Copilot' })).toBeVisible();
    const input = page.getByPlaceholder('Ask Agents about this case…');
    await input.fill('Review this case');
    await input.press('Enter');
    await expect(page.getByText('Evidence reviewed.')).toBeVisible();
    await expect(page.getByText('Đã dùng 1 công cụ')).toBeVisible();
    await page.getByText('Đã dùng 1 công cụ').click();
    await expect(page.getByText('Đã tải chi tiết vụ việc')).toBeVisible();
  });

  test('keeps the three current case actions in Complete', async ({ page }) => {
    await page.getByRole('button', { name: 'Claim', exact: true }).click();
    await page.reload();
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await page.getByLabel('Decision rationale').fill('Evidence supports the decision.');
    for (const label of ['Dismiss', 'Request evidence', 'Approve conclusion']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeEnabled();
    }
    await expect(page.getByText('Submit Decision')).toHaveCount(0);
    await expect(page.getByText('Suspend 24h')).toHaveCount(0);
  });
});
