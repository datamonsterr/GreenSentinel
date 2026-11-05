import { test, expect } from './support/playwright';

/**
 * Issue #482: case-less GSupport chat (greeting + suggestions) and the
 * case-detail auto-send flow.
 */
test.describe('Driver GSupport Chat (case-less and case-detail)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/driver/chat/stream', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: token\ndata: {"token":"Chào bạn, "}\n\n' +
          'event: token\ndata: {"token":"tôi có thể giúp gì?"}\n\n' +
          'event: blocks\ndata: {"blocks":[]}\n\n' +
          'event: done\ndata: {"status":"completed","reply":"Chào bạn, tôi có thể giúp gì?","blocks":[]}\n\n',
      });
    });

    await page.route('**/api/v1/driver/cases/*/chat/stream', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: token\ndata: {"token":"Đã kiểm tra vụ việc."}\n\n' +
          'event: blocks\ndata: {"blocks":[]}\n\n' +
          'event: done\ndata: {"status":"completed","reply":"Đã kiểm tra vụ việc.","dispute_status":"in_dispute","blocks":[]}\n\n',
      });
    });

    await page.route('**/api/v1/driver/cases/*/session', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'sess-1', messages: [] }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/dispute', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          case_id: 'case-chat-e2e-1',
          driver_id: 'drv-999',
          driver_name: 'Nguyen Van An',
          violation_code: 'ERR-01',
          violation_title: 'Unusual route check',
          dispute_status: 'in_dispute',
          allowed_claim_types: ['traffic_gridlock'],
        }),
      });
    });

    await page.route('**/api/v1/account/settings**', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ organization_id: 'org-test', roles: ['driver'] }),
      });
    });
  });

  test('shows greeting and 4 suggestion chips on /driver/chat', async ({ page }) => {
    await page.goto('/driver/chat');

    await expect(page.getByTestId('driver-chat-greeting')).toBeVisible();
    const suggestions = page.getByTestId('driver-chat-suggestions');
    await expect(suggestions.locator('button')).toHaveCount(4);
  });

  test('auto-sends the case-check prompt once on an empty case thread', async ({ page }) => {
    await page.goto('/driver/chat/case-chat-e2e-1');

    await expect(page.getByTestId('case-chip')).toBeVisible();
    // The assistant reply to the auto-sent prompt should appear without any
    // manual composer interaction.
    await expect(page.getByText('Đã kiểm tra vụ việc.')).toBeVisible();
  });

  test('user chat bubble has white text and dark green background in light and dark themes', async ({ page }) => {
    await page.goto('/driver/chat');

    await expect(page.getByTestId('driver-chat-greeting')).toBeVisible();
    const suggestions = page.getByTestId('driver-chat-suggestions');
    await suggestions.locator('button').first().click();

    const userBubble = page.getByTestId('driver-user-bubble').first();
    await expect(userBubble).toBeVisible();

    // Light theme check: text is white, background is dark green (bg-emerald-800: rgb(6, 95, 70) / oklch(0.432 0.095 166.913))
    const lightColor = await userBubble.evaluate((el) => window.getComputedStyle(el).color);
    const lightBg = await userBubble.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(lightColor).toBe('rgb(255, 255, 255)');
    expect(['rgb(6, 95, 70)', 'oklch(0.432 0.095 166.913)']).toContain(lightBg);

    // Switch to dark theme
    await page.evaluate(() => {
      const root = document.getElementById('driver-root');
      if (root) {
        root.classList.remove('light');
        root.classList.add('dark');
      }
    });

    // Dark theme check: text is white, background is dark green (dark:bg-emerald-700: rgb(4, 120, 87) / oklch(0.508 0.118 165.612))
    const darkColor = await userBubble.evaluate((el) => window.getComputedStyle(el).color);
    const darkBg = await userBubble.evaluate((el) => window.getComputedStyle(el).backgroundColor);
    expect(darkColor).toBe('rgb(255, 255, 255)');
    expect(['rgb(4, 120, 87)', 'oklch(0.508 0.118 165.612)']).toContain(darkBg);
  });
});

