import { expect, test } from '../support/playwright';
import {
  backendURL,
  gotoWithNetworkRetry,
  realAvailableCaseIdByCategory,
  realApiStatus,
  requireRealAccountE2E,
  roleHomePage,
  signInWithRole,
} from './role-accounts';

// Real-session coverage of the manual runbooks (docs/testing/manual/*) on
// hosted data. No fixtures. The traffic flow claims/releases one case and
// records the exact analyst query required by issue #191.
// Runs wherever the auth suite runs: local (AUTH_E2E_* overrides) and the
// PR-preview job in deploy-vercel.yml (preview_url/backend_url outputs).
test.describe('manual runbook flows on real sessions (no fixtures, read-only)', () => {
  test.beforeEach(() => {
    if (process.env.RUN_REAL_ACCOUNT_E2E !== 'true') {
      test.skip(true, 'opt in with RUN_REAL_ACCOUNT_E2E=true');
    }
    requireRealAccountE2E();
  });

  test('analyst triage -> case evidence -> overview (manual/COCKPIT.md)', async ({ page }) => {
    await signInWithRole(page, 'analyst');
    await gotoWithNetworkRetry(page, roleHomePage('analyst'));
    const triageQueue = page.getByRole('region', { name: 'Triage queue' });
    await expect(triageQueue).toBeVisible({ timeout: 30_000 });

    const caseButton = triageQueue.locator('button[aria-pressed]').first();
    const emptyQueue = triageQueue.getByText(/no available cases|no processed cases/i);
    await expect(caseButton.or(emptyQueue)).toBeVisible({ timeout: 30_000 });

    if (await caseButton.isVisible()) {
      await caseButton.click();
      await expect(page.getByRole('tab', { name: /overview|conversation/i }).first()).toBeVisible({
        timeout: 30_000,
      });
    }
    await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 15_000 });
    expect(backendURL().length).toBeGreaterThan(0);
  });

  test('analyst corroborates ERR-01 traffic under Điều 12.2 (manual/TRAFFIC_EVIDENCE.md)', async ({ page }) => {
    await signInWithRole(page, 'analyst');
    const routeCaseId = await realAvailableCaseIdByCategory(page, ['ERR-01', 'route_integrity']);
    expect(routeCaseId, 'an available ERR-01 case is required for hosted traffic acceptance').toBeTruthy();
    await gotoWithNetworkRetry(page, `/workplace?caseId=${encodeURIComponent(routeCaseId!)}`);
    const queue = page.getByRole('region', { name: 'Triage queue' });
    await expect(queue).toBeVisible({ timeout: 30_000 });

    const routeCaseButton = queue.locator('button[aria-pressed="true"]');
    await expect(routeCaseButton).toBeVisible({ timeout: 30_000 });
    // #368 dropped the visible case ID from the aria-pressed selector button
    // itself; the copyable case-id control lives in a sibling element inside
    // the same queue card (article). Assert via that stable card scope.
    const routeCase = queue.locator('article:has(button[aria-pressed="true"])');
    await expect(routeCase).toContainText(`#${routeCaseId!.slice(-8)}`);

    const claim = routeCase.getByRole('button', { name: 'Claim', exact: true });
    const release = routeCase.getByRole('button', { name: 'Release', exact: true });
    await expect(claim.or(release)).toBeVisible({ timeout: 30_000 });
    if (await claim.isVisible()) {
      await claim.click();
      await expect(release).toBeVisible({ timeout: 30_000 });
    }

    try {
      const input = page.getByPlaceholder('Ask Agents about this case…');
      await expect(input).toBeEnabled({ timeout: 30_000 });
      const historicalBadges = page.getByLabel('Tool fetch_corridor_historical_traffic, done');
      const incidentBadges = page.getByLabel('Tool query_traffic_incident_feed, done');
      const historicalBadgeCount = await historicalBadges.count();
      const incidentBadgeCount = await incidentBadges.count();
      const assistantMessages = page.locator('.is-assistant');
      const assistantMessageCount = await assistantMessages.count();
      await input.fill('Kiểm tra tình trạng kẹt xe và sự cố giao thông trên đoạn đường này');
      await input.press('Enter');

      await expect(historicalBadges).toHaveCount(historicalBadgeCount + 1, { timeout: 90_000 });
      await expect(incidentBadges).toHaveCount(incidentBadgeCount + 1, { timeout: 90_000 });
      await expect(assistantMessages).toHaveCount(assistantMessageCount + 1, { timeout: 90_000 });
      const currentReply = assistantMessages.nth(assistantMessageCount);
      await expect(currentReply.getByText(/Điều 12\.2/)).toBeVisible({ timeout: 90_000 });
      await expect(currentReply.getByText(/không tự động kết luận gian lận/i)).toBeVisible({ timeout: 90_000 });
    } finally {
      if (await release.isVisible().catch(() => false)) {
        const [releaseResponse] = await Promise.all([
          page.waitForResponse(response =>
            response.request().method() === 'POST' && response.url().includes(`/api/v1/cases/${routeCaseId}/release`)
          ),
          release.click(),
        ]);
        expect(releaseResponse.ok(), `case release failed with HTTP ${releaseResponse.status()}`).toBe(true);
      }
    }
  });

  test('driver dispute read path (manual/COCKPIT.md driver scope)', async ({ page }) => {
    await signInWithRole(page, 'driver');
    await gotoWithNetworkRetry(page, roleHomePage('driver'));
    await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 30_000 });

    const firstCase = page.locator('a[href*="/driver/dispute/"], button').first();
    if (await firstCase.count()) {
      await firstCase.click();
      await expect(page.getByText(/access denied/i)).toHaveCount(0, { timeout: 15_000 });
    }
  });

  test('admin organization scope API (manual/AUTHENTICATION.md org scope)', async ({ page }) => {
    await signInWithRole(page, 'admin');
    expect(await realApiStatus(page, '/api/v1/me')).toBe(200);
    expect(await realApiStatus(page, '/api/v1/account/settings')).toBe(200);

    await gotoWithNetworkRetry(page, '/organization');
    await expect(page.getByRole('heading', { name: 'Organization', exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('table', { name: 'Organization members', exact: true })).toBeVisible({ timeout: 30_000 });

    const trigger = page.getByRole('button', { name: 'Invite user', exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: 'Invite user to organization', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('textbox', { name: 'Email address', exact: true })).toBeFocused();
    await expect(dialog.getByRole('combobox', { name: 'Role', exact: true })).toHaveText('Analyst');
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});
