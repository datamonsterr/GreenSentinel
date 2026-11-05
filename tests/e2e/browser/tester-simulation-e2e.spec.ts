import { test, expect } from '@playwright/test';

test.describe('Desktop console and Workplace fixture browser regression', () => {
  const RUN_ID = 'run-sim-e2e-001';
  const CASE_ID = 'case-sim-run-sim-e2e';
  let caseStatus = 'OPEN';
  const notifications = [
    {
      id: 'notif-1',
      run_id: RUN_ID,
      recipient_type: 'driver',
      recipient_id: 'drv-sim-001',
      channel: 'APP_INBOX',
      body: 'Navigating to pickup.',
      intercepted_at: new Date().toISOString(),
    },
    {
      id: 'notif-2',
      run_id: RUN_ID,
      recipient_type: 'passenger',
      recipient_id: 'passenger-001',
      channel: 'APP_INBOX',
      body: "I'm at the pickup point.",
      intercepted_at: new Date().toISOString(),
    },
    {
      id: 'notif-3',
      run_id: RUN_ID,
      recipient_type: 'driver',
      recipient_id: 'drv-sim-001',
      channel: 'APP_INBOX',
      body: 'Passenger boarded. Heading to destination.',
      intercepted_at: new Date().toISOString(),
    },
  ];

  const samples = [
    {
      run_id: RUN_ID,
      step_index: 0,
      latitude: 21.0285,
      longitude: 105.8524,
      speed_mps: 12.0,
      heading_deg: 45.0,
      is_fault_injected: false,
      fault_type: null,
      emitted_at: new Date().toISOString(),
    },
    {
      run_id: RUN_ID,
      step_index: 10,
      latitude: 21.032,
      longitude: 105.855,
      speed_mps: 14.5,
      heading_deg: 50.0,
      is_fault_injected: true,
      fault_type: 'JUMP',
      emitted_at: new Date().toISOString(),
    },
  ];

  test.beforeEach(async ({ page }) => {
    caseStatus = 'OPEN';

    // Mock styles for maplibre to prevent external vector tile network calls in CI
    await page.route('**/styles/liberty', (route) =>
      route.fulfill({
        json: {
          version: 8,
          sources: {},
          layers: [{ id: 'test-bg', type: 'background', paint: { 'background-color': '#f8fafc' } }],
        },
      })
    );

    // Mock /test/api/v1 endpoints with realistic state
    await page.route('**/test/api/v1/**', async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname;

      if (path === '/test/api/v1/actors' && req.method() === 'GET') {
        return route.fulfill({ status: 200, json: {
          drivers: [{ id: 'drv-sim-001', display_name: 'Driver 001' }],
          passengers: [{ id: 'pass-sim-001', display_name: 'Passenger 001' }],
          vehicles: [{ id: 'veh-sim-001', display_name: 'Vehicle 001' }],
          policies: [{ id: 'pol-sim-001', display_name: 'Policy 001' }],
        } });
      }

      if (path.startsWith('/test/api/v1/drivers') && req.method() === 'GET') {
        return route.fulfill({ status: 200, json: [
          { driver_id: 'drv-sim-001', display_name: 'Driver 001', email: 'driver001@example.com', license_plate: '30A-12345' },
        ] });
      }

      if (path === '/test/api/v1/routes/resolve' && req.method() === 'POST') {
        return route.fulfill({ status: 200, json: {
          route_geometry: { type: 'LineString', coordinates: [[105.8524, 21.0285], [105.8497, 21.0118], [105.8342, 21.0345]] },
          pickup_route: { coordinates: [[105.8524, 21.0285], [105.8497, 21.0118]], distance_m: 2500, duration_s: 300, provider: 'fixture' },
          destination_route: { coordinates: [[105.8497, 21.0118], [105.8342, 21.0345]], distance_m: 3000, duration_s: 400, provider: 'fixture' },
          provider: 'fixture',
        } });
      }

      if (path === '/test/api/v1/plans' && req.method() === 'POST') {
        return route.fulfill({
          status: 201,
          json: { id: 'plan-e2e-001', name: 'E2E Plan' },
        });
      }

      if (path === '/test/api/v1/definitions' && req.method() === 'POST') {
        return route.fulfill({
          status: 201,
          json: { id: 'def-e2e-001', plan_id: 'plan-e2e-001' },
        });
      }

      if (path === '/test/api/v1/runs' && req.method() === 'POST') {
        return route.fulfill({
          status: 202,
          json: { id: RUN_ID, total_steps: 25, current_step: 0, status: 'RUNNING' },
        });
      }

      if (path === `/test/api/v1/runs/${RUN_ID}/stream`) {
        const sseBody = [
          `id: evt-1\nevent: step.progress\ndata: ${JSON.stringify({
            event_id: 'evt-1',
            event_type: 'step.progress',
            step_index: 5,
            sample: samples[0],
          })}\n\n`,
          `id: evt-2\nevent: step.progress\ndata: ${JSON.stringify({
            event_id: 'evt-2',
            event_type: 'step.progress',
            step_index: 10,
            sample: samples[1],
            active_fault: 'JUMP',
          })}\n\n`,
          `id: evt-3\nevent: run.completed\ndata: ${JSON.stringify({
            event_id: 'evt-3',
            event_type: 'run.completed',
            step_index: 25,
          })}\n\n`,
        ].join('');
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: sseBody,
        });
      }

      if (path === `/test/api/v1/runs/${RUN_ID}/overview`) {
        return route.fulfill({ json: {
          run_id: RUN_ID, status: 'COMPLETED', trips_input: 1, trips_processed: 0,
          trips_classified: 0, classification_counts: {}, stages: [],
        } });
      }
      if (path === `/test/api/v1/cases/${CASE_ID}/detail`) {
        return route.fulfill({ status: 503, json: { detail: 'Explicit fixture detail failure; use recorded raw samples.' } });
      }

      if (path === '/test/api/v1/cases' && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: [
            {
              id: CASE_ID,
              trip_id: 'trip-sim-001',
              run_id: RUN_ID,
              risk_score: 0.92,
              anomaly_types: ['JUMP'],
              status: caseStatus,
              created_at: new Date().toISOString(),
            },
          ],
        });
      }

      if (path === `/test/api/v1/runs/${RUN_ID}/samples`) {
        return route.fulfill({
          status: 200,
          json: samples,
        });
      }

      if (path === `/test/api/v1/runs/${RUN_ID}/notifications`) {
        return route.fulfill({
          status: 200,
          json: notifications,
        });
      }

      if (path === `/test/api/v1/cases/${CASE_ID}/triage` && req.method() === 'POST') {
        const postData = JSON.parse(req.postData() || '{}');
        caseStatus = postData.decision === 'INVESTIGATE' ? 'UNDER_REVIEW' : 'CLOSED';
        return route.fulfill({
          status: 200,
          json: {
            case_id: CASE_ID,
            decision: postData.decision,
            new_status: caseStatus,
            rationale: postData.rationale,
            audit_event_id: 'audit-e2e-001',
            timestamp: new Date().toISOString(),
          },
        });
      }

      return route.continue();
    });
  });

  test('runs simulation in /test cockpit and verifies active telemetry', async ({ page }) => {
    await page.goto('/test');
    await page.waitForLoadState('domcontentloaded');

    // 1. Verify 3-zone layout is present
    await expect(page.getByText(/Driver App|Màn hình Tài xế/i)).toBeVisible();
    await expect(page.getByText(/Customer App|Màn hình Khách hàng/i)).toBeVisible();
    await expect(page.getByLabel(/Vị trí xuất phát của tài xế/i)).toBeVisible();
    const driverInput = page.getByPlaceholder(/Tìm tài xế theo email/i);
    await driverInput.fill('driver');
    await page.getByText('Driver 001').first().click();
    await page.getByLabel('Khách', { exact: true }).selectOption('pass-sim-001');
    await page.getByLabel('Xe', { exact: true }).selectOption('veh-sim-001');
    await page.getByLabel('Chính sách', { exact: true }).selectOption('pol-sim-001');

    // 2. Start simulation run
    const startButton = page.getByRole('button', { name: /Start Simulation|Chạy mô phỏng/i });
    await expect(startButton).toBeVisible();
    await startButton.click();

    // 3. Verify simulation executes through SSE updates
    await expect(page.getByText(/Đang chạy|Hoàn tất/i).first()).toBeVisible({ timeout: 15000 });
  });

  for (const width of [1024, 1600]) {
    test(`keeps the desktop results dock at 40% at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto('/test');
      await expect(page.getByRole('option', { name: 'Passenger 001' })).toBeAttached();
      await page.getByRole('button', { name: 'Mở bảng xử lý' }).click();
      await expect(page.getByRole('button', { name: 'Thu gọn' })).toBeVisible();
      const dock = page.getByRole('region', { name: 'Kết quả xử lý' });
      await expect(dock).toBeVisible();
      expect(await page.getByRole('complementary', { name: 'Hội thoại chuyến đi' }).evaluate((node) => node.getBoundingClientRect().width)).toBe(width < 1200 ? 270 : 330);
      expect(await page.getByRole('complementary', { name: 'Điểm dừng và điều khiển' }).evaluate((node) => node.getBoundingClientRect().width)).toBe(width < 1200 ? 300 : 360);
      const fraction = await dock.evaluate((node) => node.getBoundingClientRect().height / node.parentElement!.getBoundingClientRect().height);
      expect(fraction).toBeCloseTo(0.4, 2);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
      await page.screenshot({ path: testInfo.outputPath(`desktop-${width}.png`) });
      await page.getByRole('button', { name: 'Thu gọn' }).click();
      expect(await dock.evaluate((node) => node.getBoundingClientRect().height)).toBeCloseTo(38, 0);
    });
  }

  test('triages a recorded fixture case through /test/workplace continuity', async ({ page }) => {
    // Navigate to Test Workplace
    await page.goto('/test/workplace');
    await page.waitForLoadState('domcontentloaded');

    // 1. Verify case auto-generated from simulation appears in triage queue
    const caseCard = page.locator(`button:has-text("${CASE_ID}")`);
    await expect(caseCard).toBeVisible({ timeout: 10000 });
    await expect(caseCard.getByText('0.92')).toBeVisible();
    await expect(caseCard.getByText('JUMP')).toBeVisible();

    // 2. Select the case
    await caseCard.click();

    // 3. Verify intercepted notifications in Evidence Viewer
    await expect(page.getByText(/Intercepted Sandbox Notifications \(3\)/i)).toBeVisible();
    await expect(page.getByText("I'm at the pickup point.")).toBeVisible();
    await expect(page.getByText('Navigating to pickup.')).toBeVisible();

    // 4. Verify Map & Chart view switching
    const chartTab = page.getByRole('button', { name: 'Chart', exact: true });
    await expect(chartTab).toBeVisible();
    await chartTab.click({ force: true });
    await expect(page.getByText(/● Speed \(m\/s\)/i)).toBeVisible();
    await expect(page.getByText(/● DAVI \(est\.\)/i)).toBeVisible();

    const mapTab = page.getByRole('button', { name: 'Map', exact: true });
    await expect(mapTab).toBeVisible();
    await mapTab.click({ force: true });

    // 5. Enter adjudication rationale and commit decision
    const rationaleInput = page.getByPlaceholder(/Enter rationale for audit log/i);
    await expect(rationaleInput).toBeVisible();
    await rationaleInput.fill('GPS jump verified from telemetry anomaly breadcrumbs.');

    const approveButton = page.getByRole('button', { name: 'Approve', exact: true });
    await expect(approveButton).toBeVisible();
    await approveButton.click();

    // 6. Verify case status transitions to CLOSED
    await expect(caseCard.getByText('CLOSED')).toBeVisible({ timeout: 5000 });
  });
});
