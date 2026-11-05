import { test, expect } from '@playwright/test';

test.describe('Test Console Preset Detail, Run Dialog, and Batch Logs Flow', () => {
  const PRESET_ID = 'vietnam-road-1k';
  const BATCH_ID = 'batch-e2e-001';

  test.beforeEach(async ({ page }) => {
    // Mock MapLibre styles
    await page.route('**/styles/liberty', (route) =>
      route.fulfill({
        json: {
          version: 8,
          sources: {},
          layers: [{ id: 'test-bg', type: 'background', paint: { 'background-color': '#f8fafc' } }],
        },
      })
    );

    // Mock /test/api/v1 endpoints
    await page.route('**/test/api/v1/**', async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname;

      if (path === '/test/api/v1/actors' && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: {
            drivers: [{ id: 'drv-sim-001', display_name: 'Driver 001' }],
            passengers: [{ id: 'pass-sim-001', display_name: 'Passenger 001' }],
            vehicles: [{ id: 'veh-sim-001', display_name: 'Vehicle 001' }],
          },
        });
      }

      if (path === '/test/api/v1/routes/resolve' && req.method() === 'POST') {
        return route.fulfill({
          status: 200,
          json: {
            route_geometry: { type: 'LineString', coordinates: [[105.8524, 21.0285], [105.8497, 21.0118], [105.8342, 21.0345]] },
            pickup_route: { coordinates: [[105.8524, 21.0285], [105.8497, 21.0118]], distance_m: 2500, duration_s: 300, provider: 'fixture' },
            destination_route: { coordinates: [[105.8497, 21.0118], [105.8342, 21.0345]], distance_m: 3000, duration_s: 400, provider: 'fixture' },
            provider: 'fixture',
          },
        });
      }

      if (path === '/test/api/v1/runs' && req.method() === 'GET') {
        return route.fulfill({ status: 200, json: [] });
      }

      if (path === '/test/api/v1/drivers/linked' && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: [
            {
              driver_id: 'drv-e2e-1',
              display_name: 'Tài xế Nguyễn Văn A',
              email: 'nva@example.com',
              principal_id: 'p-e2e-1',
              license_plate: '29A-123.45',
            },
            {
              driver_id: 'drv-e2e-2',
              display_name: 'Tài xế Trần Thị B',
              email: 'ttb@example.com',
              principal_id: 'p-e2e-2',
              license_plate: '29B-678.90',
            },
          ],
        });
      }

      if (path === '/test/api/v1/presets' && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: {
            presets: [
              {
                id: PRESET_ID,
                title: 'Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)',
                description: '1.000 chuyến hành trình thực tế tại Việt Nam',
                kind: 'vietnam',
                available: true,
                unavailable_reason: null,
                source_label: 'vietnam_road',
                selection_size: 1000,
                available_trips: 1000,
                metadata: {},
                metrics: {},
                sample_trips: [],
              },
            ],
            source: { revision: '914a3656' },
          },
        });
      }

      if (path === `/test/api/v1/presets/${PRESET_ID}` && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: {
            id: PRESET_ID,
            title: 'Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)',
            description: '1.000 chuyến hành trình thực tế tại Việt Nam',
            kind: 'vietnam',
            available: true,
            unavailable_reason: null,
            source_label: 'vietnam_road',
            selection_size: 1000,
            available_trips: 1000,
            trip_count: 1000,
            source_release: 'synthesized_vietnam_trip',
            revision: 'rev-vn-e2e',
            trips_sha256: 'sha256-vn-trip-hash',
            license: 'ODbL (OpenStreetMap contributors)',
            metadata: {},
            metrics: {},
            sample_trips: [
              {
                trip_ref: 'vn_trip_e2e_01',
                label: 'no_violation',
                severity: 'none',
                scenario: 'normal_route',
                city: 'Hà Nội',
                driver_display_name: 'Tài xế Nguyễn Văn A',
                license_plate: '29A-123.45',
                pickup_name: 'Hồ Hoàn Kiếm',
                dropoff_name: 'Keangnam 72',
                distance_m: 8500,
                duration_s: 1200,
                telemetry_points: 120,
              },
            ],
            distributions: {
              total_records: 1000,
              by_label: {
                fraud: 300,
                no_violation: 700,
                insufficient_evidence: 0,
                grouped: { fraud: 300, no_violation: 700, insufficient_evidence: 0 },
                per_code: { 'ERR-01': 150, 'ERR-02': 150 },
              },
              per_code: { 'ERR-01': 150, 'ERR-02': 150 },
              by_severity: { P1: 150, P2: 150, none: 700 },
              by_scenario: { normal_route: 700, deviation: 300 },
              by_city: { 'Hà Nội': 1000 },
              by_cancellation_actor: { none: 1000 },
            },
          },
        });
      }

      if (path === `/test/api/v1/presets/${PRESET_ID}/runs` && req.method() === 'POST') {
        return route.fulfill({
          status: 201,
          json: {
            id: BATCH_ID,
            organization_id: 'org-e2e',
            preset_id: PRESET_ID,
            params: { trips_per_batch: 1, interval_s: 2, driver_ids: ['drv-e2e-1', 'drv-e2e-2'] },
            status: 'RUNNING',
            counters: { total: 1, queued: 0, running: 1, completed: 0, failed: 0 },
            created_at: new Date().toISOString(),
            started_at: new Date().toISOString(),
            completed_at: null,
            cancelled_at: null,
          },
        });
      }

      if (path === `/test/api/v1/presets/runs/${BATCH_ID}` && req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          json: {
            id: BATCH_ID,
            organization_id: 'org-e2e',
            preset_id: PRESET_ID,
            params: { trips_per_batch: 1, interval_s: 2, driver_ids: ['drv-e2e-1', 'drv-e2e-2'] },
            status: 'COMPLETED',
            counters: { total: 1, completed: 1, running: 0, queued: 0 },
            created_at: new Date().toISOString(),
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            cancelled_at: null,
            trips: [
              {
                id: 'trip-e2e-1',
                batch_id: BATCH_ID,
                trip_ref: 'vn_trip_e2e_01',
                order: 0,
                status: 'COMPLETED',
                driver_id: 'drv-e2e-1',
                driver_name: 'Tài xế Nguyễn Văn A',
                expected_label: 'no_violation',
                predicted_label: 'no_violation',
                confidence: 0.94,
                case_id: null,
                run_id: 'run-e2e-1',
                error: null,
                created_at: new Date().toISOString(),
                started_at: new Date().toISOString(),
                completed_at: new Date().toISOString(),
                snapshot: {
                  driver_name: 'Tài xế Nguyễn Văn A',
                  conversation: [{ role: 'customer', text: 'Xin chào tài xế' }],
                  gps_summary: { points: 120, mock_location_count: 0, max_accuracy_m: 5.0 },
                  speed_stats: { min_mps: 0.0, avg_mps: 12.0, max_mps: 18.0 },
                },
              },
            ],
          },
        });
      }

      if (path === `/test/api/v1/presets/runs/${BATCH_ID}/events` && req.method() === 'GET') {
        const sseContent = [
          'event: connect\ndata: {"status":"connected"}\n\n',
          `id: evt-b1\nevent: trip.classifier_received\ndata: ${JSON.stringify({
            event_id: 'evt-b1',
            event_type: 'trip.classifier_received',
            batch_id: BATCH_ID,
            trip_ref: 'vn_trip_e2e_01',
            reached_classifier: true,
            occurred_at: new Date().toISOString(),
          })}\n\n`,
          `id: evt-b2\nevent: trip.classified\ndata: ${JSON.stringify({
            event_id: 'evt-b2',
            event_type: 'trip.classified',
            batch_id: BATCH_ID,
            trip_ref: 'vn_trip_e2e_01',
            label: 'no_violation',
            confidence: 0.94,
            reached_classifier: true,
            occurred_at: new Date().toISOString(),
          })}\n\n`,
          `id: evt-b3\nevent: batch.completed\ndata: ${JSON.stringify({
            event_id: 'evt-b3',
            event_type: 'batch.completed',
            batch_id: BATCH_ID,
            reached_classifier: false,
            occurred_at: new Date().toISOString(),
          })}\n\n`,
        ].join('');

        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: sseContent,
        });
      }

      return route.fulfill({ status: 200, json: {} });
    });
  });

  test('preset selection, tab navigation, run dialog driver selection, and batch execution', async ({ page }) => {
    await page.goto('/test');

    // Switch to Presets tab
    const presetsTabBtn = page.getByRole('button', { name: /Chuyến mẫu/i });
    await presetsTabBtn.click();

    // Verify preset card is displayed
    const presetCard = page.getByText('Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)');
    await expect(presetCard).toBeVisible();

    // Click preset card -> selects preset and displays detail on Presets tab without tab navigation
    await presetCard.click();
    await expect(page.getByTestId('preset-detail-container')).toBeVisible();

    // Info tab assertions
    await expect(page.getByText('synthesized_vietnam_trip')).toBeVisible();
    await expect(page.getByText('rev-vn-e2e')).toBeVisible();
    await expect(page.getByText('sha256-vn-trip-hash')).toBeVisible();

    // Samples tab navigation
    await page.getByTestId('tab-trigger-samples').click();
    await expect(page.getByText('vn_trip_e2e_01')).toBeVisible();
    await expect(page.getByTestId('open-manual-vn_trip_e2e_01')).toBeVisible();

    // Distribution tab navigation
    await page.getByTestId('tab-trigger-distribution').click();
    await expect(page.getByText(/Gian lận: 300/i)).toBeVisible();
    await expect(page.getByText(/Không vi phạm: 700/i)).toBeVisible();
    await expect(page.getByText('ERR-01')).toBeVisible();

    // Click "Chạy đợt mô phỏng" button to open run dialog
    await page.getByTestId('preset-run-button').click();

    // Run dialog assertions
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText('Tài xế Nguyễn Văn A')).toBeVisible();
    await expect(page.getByText('Tài xế Trần Thị B')).toBeVisible();

    // Deselect all drivers -> Run button disabled
    const selectAllDrivers = page.getByRole('checkbox', { name: 'Chọn tất cả tài xế' });
    await selectAllDrivers.click();
    const runBtn = page.getByRole('button', { name: /Bắt đầu chạy/i });
    await expect(runBtn).toBeDisabled();

    // Select all drivers -> Run button enabled
    await selectAllDrivers.click();
    await expect(runBtn).toBeEnabled();

    // Start batch run
    await runBtn.click();

    // Dialog closes and switches to Logs tab
    await expect(page.getByRole('dialog')).not.toBeVisible();
    await expect(page.getByTestId('tab-content-logs')).toBeVisible();

    // Batch logs display the trip
    await expect(page.getByText('vn_trip_e2e_01')).toBeVisible();
    await expect(page.getByText(/Dự đoán: no_violation/i)).toBeVisible();

    // Expand trip to view details
    await page.getByTestId('trip-header-vn_trip_e2e_01').click();
    await expect(page.getByTestId('trip-details-vn_trip_e2e_01')).toBeVisible();
    await expect(page.getByText('Xin chào tài xế')).toBeVisible();
  });
});
