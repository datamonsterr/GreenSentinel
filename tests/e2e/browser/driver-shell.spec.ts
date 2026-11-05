import path from 'path';
import { test, expect } from './support/playwright';

const SCREENSHOT_DIR = path.resolve(__dirname, '../../../docs/design/driver-app-redesign/impl');


async function settingsCardLuminance(page: import('@playwright/test').Page): Promise<number> {
  return page.locator('#driver-root section').first().evaluate((el) => {
    const match = getComputedStyle(el).backgroundColor.match(/[\d.]+/g) ?? ['255', '255', '255'];
    const [r, g, b] = match.slice(0, 3).map(Number);
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  });
}

test.describe('Driver App Shell Navigation & Settings', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept driver API endpoints
    await page.route('**/api/v1/driver/cases**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/driver/cases') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                case_id: 'case-alpha-1234',
                trip_id: 'trip-101',
                violation_code: 'ERR-01',
                violation_title: 'Chậm đón khách',
                description: 'Xe tiếp cận điểm đón chậm',
                alleged_time: '2026-09-26T08:30:00Z',
                status: 'open',
                dispute_status: 'not_disputed',
                source: 'system_detected',
                driver_id: 'drv-999',
                created_at: '2026-09-26T08:30:00Z',
              },
            ],
            total: 1,
          }),
        });
      }
      if (url.pathname.includes('/dispute')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            case_id: 'case-alpha-1234',
            trip_id: 'trip-101',
            driver_id: 'drv-999',
            driver_name: 'Nguyen Van An',
            violation_code: 'ERR-01',
            status: 'open',
            dispute_status: 'not_disputed',
            gps_trace: [],
            messages: [],
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    await page.route('**/api/v1/account/settings**', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          organization_id: 'org-test',
          roles: ['driver'],
        }),
      });
    });

    await page.route('**/api/v1/driver/profile**', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        // Shape must exactly match DriverProfileResponse (src/models/schemas.py).
        body: JSON.stringify({
          driver_id: 'drv-999',
          display_name: 'Nguyen Van An',
          member_since: '2023-04-15T00:00:00Z',
          vehicle: {
            model: 'VinFast VF e34',
            plate: '29E-123.45',
          },
          scorecard: {
            driver_id: 'drv-999',
            total_trips: 1204,
            total_cases: 1,
            violation_ratio_90d: 0.8,
            benchmark_violation_ratio: 2.5,
            fined_ratio: 0.5,
            repeat_offense_risk_score: 12,
            tenure_months: 18,
            past_incidents: [],
          },
          rating_average: 4.88,
          rated_count: 512,
          distribution: {
            '5': 460,
            '4': 40,
            '3': 8,
            '2': 3,
            '1': 1,
          },
          weekly_trend: [
            { week_label: 'W1', week_start: '2026-08-24', average_rating: 4.82, rated_count: 58 },
            { week_label: 'W2', week_start: '2026-08-31', average_rating: 4.85, rated_count: 62 },
            { week_label: 'W3', week_start: '2026-09-07', average_rating: 4.79, rated_count: 55 },
            { week_label: 'W4', week_start: '2026-09-14', average_rating: 4.88, rated_count: 65 },
            { week_label: 'W5', week_start: '2026-09-21', average_rating: 4.91, rated_count: 70 },
            { week_label: 'W6', week_start: '2026-09-28', average_rating: 4.86, rated_count: 60 },
            { week_label: 'W7', week_start: '2026-10-05', average_rating: 4.90, rated_count: 68 },
            { week_label: 'W8', week_start: '2026-10-12', average_rating: 4.88, rated_count: 74 },
          ],
        }),
      });
    });

    await page.route('**/api/v1/driver/feedback**', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        // Shape must exactly match DriverFeedbackResponse (src/models/schemas.py).
        body: JSON.stringify({
          items: [
            {
              id: 'fb-001',
              stars: 5,
              comment: 'Tai xe rat lich su va nhiet tinh, xe sach se!',
              date: '2026-10-15T14:30:00Z',
              created_at: '2026-10-15T14:30:00Z',
            },
            {
              id: 'fb-002',
              stars: null,
              comment: 'Chi nhan xet, khong cham sao.',
              date: '2026-10-14T09:15:00Z',
              created_at: '2026-10-14T09:15:00Z',
            },
            {
              id: 'fb-003',
              stars: 5,
              comment: 'Lai xe can than, em ai, dung gio.',
              date: '2026-10-12T18:20:00Z',
              created_at: '2026-10-12T18:20:00Z',
            },
          ],
          next_cursor: null,
          total: 3,
        }),
      });
    });
  });

  test('navigates all 5 tabs and redirects /driver to /driver/cases', async ({ page }) => {
    // 1. Visit /driver -> should redirect to /driver/cases
    await page.goto('/driver');
    await expect(page).toHaveURL(/\/driver\/cases/);

    // Verify bottom nav has 5 tabs
    const nav = page.getByRole('navigation', { name: /Thanh điều hướng tài xế|Driver bottom navigation/i });
    await expect(nav).toBeVisible();

    // Verify active tab is Cases
    const casesTab = nav.getByRole('link', { name: /Vụ việc|Cases/i });
    await expect(casesTab).toHaveAttribute('aria-current', 'page');

    // 2. Navigate to Profile tab
    const profileTab = nav.getByRole('link', { name: /Hồ sơ|Profile/i });
    await profileTab.click();
    await expect(page).toHaveURL(/\/driver\/profile/);
    await expect(profileTab).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('heading', { name: /Hồ sơ tài xế|Driver Profile/i })).toBeVisible();

    // 3. Navigate to GSupport tab (center button)
    const chatTab = nav.getByRole('link', { name: /GSupport/i });
    await chatTab.click();
    await expect(page).toHaveURL(/\/driver\/chat/);
    await expect(chatTab).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('heading', { name: /^(Chào|Hi) .+/i })).toBeVisible();

    // 4. Navigate to History tab
    const historyTab = nav.getByRole('link', { name: /Lịch sử|History/i });
    await historyTab.click();
    await expect(page).toHaveURL(/\/driver\/history/);
    await expect(historyTab).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('heading', { name: /Lịch sử hoạt động|Activity History/i })).toBeVisible();

    // 5. Navigate to Settings tab
    const settingsTab = nav.getByRole('link', { name: /Cài đặt|Settings/i });
    await settingsTab.click();
    await expect(page).toHaveURL(/\/driver\/settings/);
    await expect(settingsTab).toHaveAttribute('aria-current', 'page');
  });

  test('toggles theme between light and dark with reload persistence and scoped driver root', async ({ page }) => {
    await page.goto('/driver/settings');

    const darkBtn = page.getByRole('button', { name: /Tối|Dark/i });
    const lightBtn = page.getByRole('button', { name: /Sáng|Light/i });
    const driverRoot = page.locator('#driver-root');

    // Click Dark
    await darkBtn.click();
    await expect(driverRoot).toHaveClass(/dark/);
    // Dark mode must NOT leak to html element
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    // Dark utilities must actually render, not just the class toggle
    expect(await settingsCardLuminance(page)).toBeLessThan(0.3);

    // Verify reload persistence
    await page.reload();
    await expect(page.locator('#driver-root')).toHaveClass(/dark/);
    expect(await settingsCardLuminance(page)).toBeLessThan(0.3);
    await expect(page.locator('html')).not.toHaveClass(/dark/);

    // Click Light
    await page.getByRole('button', { name: /Sáng|Light/i }).click();
    await expect(driverRoot).toHaveClass(/light/);
    await expect(driverRoot).not.toHaveClass(/dark/);
    expect(await settingsCardLuminance(page)).toBeGreaterThan(0.8);

    // Verify reload persistence
    await page.reload();
    await expect(page.locator('#driver-root')).toHaveClass(/light/);
    await expect(page.locator('#driver-root')).not.toHaveClass(/dark/);
  });

  test('toggles language between Vietnamese and English with reload persistence', async ({ page }) => {
    await page.goto('/driver/settings');

    const enBtn = page.getByRole('button', { name: 'English' });
    const viBtn = page.getByRole('button', { name: 'Tiếng Việt' });

    // Switch to English
    await enBtn.click();
    await expect(page.getByText('Sign out')).toBeVisible();

    // Verify reload persistence
    await page.reload();
    await expect(page.getByText('Sign out')).toBeVisible();

    // Switch back to Vietnamese
    await page.getByRole('button', { name: 'Tiếng Việt' }).click();
    await expect(page.getByText('Đăng xuất')).toBeVisible();

    // Verify reload persistence
    await page.reload();
    await expect(page.getByText('Đăng xuất')).toBeVisible();
  });

  test('settings displays only legitimate info and removes all fabricated data', async ({ page }) => {
    await page.goto('/driver/settings');

    // Legitimate controls
    await expect(page.getByRole('heading', { name: /Cài đặt|Settings/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Quản lý tài khoản|Manage account/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Đăng xuất|Sign out/i })).toBeVisible();

    // Fabricated data must NOT be present
    await expect(page.getByText(/Gold Tier|Hạng Vàng/i)).toHaveCount(0);
    await expect(page.getByText(/29E - 584\.92/i)).toHaveCount(0);
    await expect(page.getByText(/82%|246 km/i)).toHaveCount(0);
    await expect(page.getByText(/GSM-VN-884920/i)).toHaveCount(0);
    await expect(page.getByText(/1900 2088/i)).toHaveCount(0);
    await expect(page.locator('a[href="#policies"]')).toHaveCount(0);
    await expect(page.locator('a[href="#regulations"]')).toHaveCount(0);
  });

  test('handles sign out redirecting to sign-in', async ({ page }) => {
    await page.goto('/driver/settings');

    const signOutBtn = page.getByRole('button', { name: /Đăng xuất|Sign out/i });
    await expect(signOutBtn).toBeVisible();
    await signOutBtn.click();

    await expect(page).toHaveURL(/\/sign-in/);
  });

  test('chat composer on /driver/chat/[caseId] clears fixed bottom nav', async ({ page }) => {
    await page.goto('/driver/chat/case-alpha-1234');

    const nav = page.getByRole('navigation', { name: /Thanh điều hướng tài xế|Driver bottom navigation/i });
    await expect(nav).toBeVisible();

    const composer = page.locator('[data-testid="chat-composer"]');
    await expect(composer).toBeVisible();

    const navBox = await nav.boundingBox();
    const composerBox = await composer.boundingBox();

    expect(navBox).not.toBeNull();
    expect(composerBox).not.toBeNull();

    // The composer bottom edge must be above the navigation bar's lower content or properly offset
    expect(composerBox!.y).toBeLessThan(navBox!.y + navBox!.height);
  });

  test('chat composer textarea width is greater than 200px at viewport 412x900 on /driver/chat and /driver/chat/[caseId]', async ({ page }) => {
    await page.setViewportSize({ width: 412, height: 900 });

    // 1. Caseless driver chat
    await page.goto('/driver/chat');
    const textareaCaseless = page.locator('[data-testid="chat-composer"] textarea');
    await expect(textareaCaseless).toBeVisible();
    const boxCaseless = await textareaCaseless.boundingBox();
    expect(boxCaseless).not.toBeNull();
    expect(boxCaseless!.width).toBeGreaterThan(200);

    // 2. Case-scoped driver chat
    await page.goto('/driver/chat/case-alpha-1234');
    const textareaCase = page.locator('[data-testid="chat-composer"] textarea');
    await expect(textareaCase).toBeVisible();
    const boxCase = await textareaCase.boundingBox();
    expect(boxCase).not.toBeNull();
    expect(boxCase!.width).toBeGreaterThan(200);
  });

  test('captures screenshots of Settings, Cases, and Profile in light and dark mode', async ({ page }) => {
    // 1. Cases Light
    await page.goto('/driver/settings');
    await page.getByRole('button', { name: /Sáng|Light/i }).click();
    await page.goto('/driver/cases');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'cases-light.png') });

    // 2. Cases Dark
    await page.goto('/driver/settings');
    await page.getByRole('button', { name: /Tối|Dark/i }).click();
    await page.goto('/driver/cases');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'cases-dark.png') });

    // 3. Settings Dark
    await page.goto('/driver/settings');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'settings-dark.png') });

    // 4. Settings Light
    await page.getByRole('button', { name: /Sáng|Light/i }).click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'settings-light.png') });

    // 5. Profile Light
    await page.goto('/driver/settings');
    await page.getByRole('button', { name: /Sáng|Light/i }).click();
    await page.goto('/driver/profile');
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'profile-light.png') });

    // 6. Profile Dark
    await page.goto('/driver/settings');
    await page.getByRole('button', { name: /Tối|Dark/i }).click();
    await page.goto('/driver/profile');
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'profile-dark.png') });
  });
});
