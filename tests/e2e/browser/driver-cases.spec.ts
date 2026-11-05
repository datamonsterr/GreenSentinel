import { test, expect } from './support/playwright';

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

test.describe('Driver Cases Tab (PR #503 smoke)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/driver/cases**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/v1/driver/cases') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              case_id: '018f2f4e-a000-7000-8000-000000001234',
              case_code: '#1234',
              trip_id: 'trip-raw-secret-101',
              driver_id: 'drv-secret-999',
              violation_code: 'ERR-01',
              violation_title: 'Chậm đón khách',
              description: 'Xe tiếp cận điểm đón chậm',
              alleged_time: '2026-09-26T08:30:00Z',
              status: 'open',
              dispute_status: 'not_disputed',
              dispute_deadline: '2099-01-01T00:00:00Z',
              source: 'system_detected',
              created_at: '2026-09-26T08:30:00Z',
            },
          ],
          total: 1,
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

  test('renders the cases list, hides raw UUIDs, and navigates to the chat screen on tap', async ({ page }) => {
    await page.goto('/driver/cases');

    // Short case code renders; raw UUID never does.
    const card = page.getByRole('button', { name: /#1234/i });
    await expect(card).toBeVisible();
    await expect(page.locator('body')).not.toContainText('018f2f4e-a000-7000-8000-000000001234');

    const bodyText = await page.locator('body').innerText();
    expect(UUID_RE.test(bodyText)).toBe(false);

    await card.click();
    await expect(page).toHaveURL(/\/driver\/chat\/018f2f4e-a000-7000-8000-000000001234/, { timeout: 30000 });
  });
});

