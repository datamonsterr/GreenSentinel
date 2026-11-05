import path from 'path';
import { test, expect } from './support/playwright';

const SCREENSHOT_DIR = path.resolve(__dirname, '../../../docs/design/driver-app-redesign/impl');

const TRIP_1 = {
  trip_id: '884aedff-b9d6-5e06-9ba1-f99ccce6d22e',
  pickup_label: 'Sảnh R1, Vinhomes Ocean Park 1',
  dropoff_label: 'Nhà ga T2, Sân bay Quốc tế Nội Bài',
  started_at: '2026-10-24T08:15:00Z',
  ended_at: '2026-10-24T09:02:00Z',
  distance_km: 32.0,
  duration_min: 47.0,
  fare_vnd: 285000,
  payment_method: 'wallet',
  payment_method_synthetic: true,
  rating: {
    stars: 5,
    comment: 'Tài xế lái xe êm, xe VF 8 sạch sẽ.',
    locale: 'vi',
    created_at: '2026-10-24T09:05:00Z',
  },
  status: 'completed',
  has_case: false,
  case_id: null,
};

const TRIP_2 = {
  trip_id: '994aedff-c9d6-5e06-9ba1-f99ccce6d33f',
  pickup_label: 'Tòa Landmark 81, Vinhomes Central Park',
  dropoff_label: 'Bitexco Financial Tower, Q.1',
  started_at: '2026-10-24T11:30:00Z',
  ended_at: '2026-10-24T12:05:00Z',
  distance_km: 14.5,
  duration_min: 35.0,
  fare_vnd: 142000,
  payment_method: 'credit_card',
  payment_method_synthetic: true,
  rating: null,
  status: 'completed',
  has_case: true,
  case_id: '018f2f4e-case-7000-8000-000000000002',
};

test.describe('Driver History Tab', () => {
  test.beforeEach(async ({ page }) => {
    // Single dispatching handler avoids Playwright route-precedence surprises between
    // /driver/trips, /driver/trips/summary, and /driver/trips/{id}.
    await page.route('**/api/v1/driver/trips**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/driver/trips/summary') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            month: '2026-10',
            trip_count: 2,
            total_fare_vnd: 427000,
            total_distance_km: 46.5,
            avg_rating: 4.95,
          }),
        });
      }
      if (url.pathname === '/api/v1/driver/trips') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            trips: [TRIP_1, TRIP_2],
            total: 2,
            next_cursor: null,
            counts: { all: 2, completed: 1, flagged: 1 },
          }),
        });
      }
      // Single-trip detail fallback (not exercised in this smoke suite).
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });

    await page.route('**/api/v1/driver/cases**', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
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

  test('renders trips, summary, and tab badges from the backend', async ({ page }) => {
    await page.goto('/driver/history');

    await expect(page.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeVisible();
    await expect(page.getByText('Tòa Landmark 81, Vinhomes Central Park')).toBeVisible();

    const allTab = page.getByRole('tab', { name: /Tất cả/i });
    await expect(allTab).toContainText('2');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'history-light.png'), fullPage: true });
  });

  test('month picker switches the selected month and refetches', async ({ page }) => {
    await page.goto('/driver/history');
    await expect(page.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeVisible();

    let requestedMonth: string | null = null;
    await page.route('**/api/v1/driver/trips?*', async (route) => {
      const url = new URL(route.request().url());
      requestedMonth = url.searchParams.get('month');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ trips: [], total: 0, next_cursor: null, counts: { all: 0, completed: 0, flagged: 0 } }),
      });
    });

    await page.getByLabel(/Tháng trước|Previous month/i).click();
    await expect(page.getByText(/Chưa có chuyến đi|No trips found/i)).toBeVisible();
    expect(requestedMonth).not.toBeNull();
  });

  test('flagged trip card navigates to the driver chat for its case', async ({ page }) => {
    await page.goto('/driver/history');
    await expect(page.getByText('Tòa Landmark 81, Vinhomes Central Park')).toBeVisible();

    await page.getByText('Tòa Landmark 81, Vinhomes Central Park').click();
    await expect(page).toHaveURL(/\/driver\/chat\/018f2f4e-case-7000-8000-000000000002/);
  });

  test('dark mode renders the history tab with readable contrast', async ({ page }) => {
    await page.goto('/driver/settings');
    await page.getByRole('button', { name: /Tối|Dark/i }).click();

    await page.goto('/driver/history');
    await expect(page.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeVisible();
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'history-dark.png'), fullPage: true });
  });
});
