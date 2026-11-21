import { expect, test } from './support/playwright';
import manifest from '../../fixtures/road_telemetry/normal_trip.json';

test.use({ viewport: { width: 1280, height: 720 } });

const CASE_ID = '11111111-1111-4111-8111-111111111111';

function caseResponse() {
  return {
    case: { id: CASE_ID, status: 'OPEN', priority: 'P1', priority_score: 0.8, category: 'route_integrity', version: 3, driver_name: 'Nguyen Hung', vehicle_plate: '29A-12345', district: 'Ba Dinh', sla_countdown_s: 240 },
    trip: { vehicle_type: 'Green SM Bike', pickup_address: 'fixture origin', dropoff_address: 'fixture destination', pickup: manifest.trip.pickup, dropoff: manifest.trip.dropoff },
    telemetry_samples: manifest.ingest_events.map((event) => ({
      recorded_at: event.occurred_at,
      position: { coordinates: [event.payload.position.longitude, event.payload.position.latitude] },
      speed_mps: event.payload.speed_mps,
      bearing_deg: event.payload.bearing_deg,
      leg: event.leg,
    })),
    route_geometry: {
      pickup_route: manifest.route_snapshots.find((snapshot) => snapshot.leg === 'pickup')?.route_geojson,
      destination_route: manifest.route_snapshots.find((snapshot) => snapshot.leg === 'destination')?.route_geojson,
    },
    forensic_brief: {
      case_id: CASE_ID,
      generated_at: '2026-09-25T08:03:00Z',
      abnormality_count: 0,
      abnormalities: [],
      summary_text: 'Forensic Brief: canonical road telemetry verified.',
      evidence_sources: [],
    },
    conversation: [], candidate_routes: [], timeline_milestones: [
      { id: 'origin', type: 'start_match', timestamp: manifest.ingest_events[0].occurred_at, title: 'Điểm bắt đầu' },
      { id: 'pickup', type: 'pickup', timestamp: manifest.ingest_events.filter((event) => event.leg === 'pickup').at(-1)!.occurred_at, title: 'Điểm đón khách' },
      { id: 'destination', type: 'dropoff_destination', timestamp: manifest.ingest_events.at(-1)!.occurred_at, title: 'Điểm đến' },
    ], missingness_alerts: [],
    guardrails: { is_blocking: false, blocking_reasons: [] }, active_lease: null, adjudication: null,
  };
}

const firstEvent = manifest.ingest_events[0];
const scrubEvent = manifest.ingest_events[1];
const scrubSeconds = (Date.parse(scrubEvent.occurred_at) - Date.parse(firstEvent.occurred_at)) / 1000;

test.describe('road telemetry fixture in the real browser map', () => {
  test('renders both canonical legs and scrubs canonical telemetry', async ({ page }) => {
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/v1/me') {
        return route.fulfill({ json: { id: 'analyst-e2e', display_name: 'E2E Analyst', roles: ['analyst'] } });
      }
      if (path === '/api/v1/account/settings') {
        return route.fulfill({
          json: {
            id: 'analyst-e2e',
            display_name: 'E2E Analyst',
            roles: ['analyst', 'fraud_analyst'],
            primary_role: 'analyst',
            organization_id: 'org-e2e',
          },
        });
      }
      if (path === '/api/v1/cases' && route.request().method() === 'GET') {
        return route.fulfill({ json: { items: [{ id: CASE_ID, status: 'OPEN', priority: 'P1', priority_score: 0.8, category: 'route_integrity', version: 3, driver_name: 'Nguyen Hung', vehicle_plate: '29A-12345', district: 'Ba Dinh', sla_countdown_s: 240 }], total: 1, limit: 50, offset: 0 } });
      }
      if (path === `/api/v1/cases/${CASE_ID}`) {
        return route.fulfill({ json: caseResponse() });
      }
      if (path.endsWith('/forensic-brief')) {
        return route.fulfill({ json: caseResponse().forensic_brief });
      }
      if (path.endsWith('/agent-context')) {
        return route.fulfill({
          json: {
            prompt_tokens: 1500,
            completion_tokens: 300,
            total_tokens: 1800,
            context_window: 10000,
            breakdown: {
              system: 400,
              dossier: 600,
              history: 300,
              tool_results: 300,
              query: 200,
            },
            turn_count: 2,
          },
        });
      }
      if (path.endsWith('/agent-session')) {
        return route.fulfill({ json: { session_id: 'session-e2e', messages: [] } });
      }
      if (path.endsWith('/policy')) {
        return route.fulfill({ json: { case_id: CASE_ID, suspected_category: 'route_integrity', policy_version: '2026.1', action_matrix: {}, applicable_action_rule: {}, clauses: [], related_policies: [], source: 'in_memory_fallback' } });
      }
      if (path.endsWith('/dispute-dossier')) {
        return route.fulfill({
          json: {
            case_id: CASE_ID,
            dispute_status: 'open',
            driver_id: 'driver-e2e',
            transcripts: [],
            recommended_action: 'APPROVE',
          },
        });
      }
      if (path.includes('/scorecard') || path.endsWith('/driver-scorecard')) {
        return route.fulfill({
          json: {
            driver_id: 'drv-e2e',
            violation_ratio_90d: 4.2,
            fined_ratio: 50.0,
            repeat_offense_risk_score: 75,
            benchmark_violation_ratio: 5.0,
            tenure_months: 18,
            past_incidents: [],
          },
        });
      }
      if (path.endsWith('/workflow-trace')) {
        return route.fulfill({ json: { case_id: CASE_ID, traces: [] } });
      }
      if (path.endsWith('/stream')) {
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
      }
      return route.continue();
    });
    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));
    await page.goto('/workplace');

    const queue = page.getByRole('region', { name: 'Triage queue' });
    await expect(queue).toBeVisible();
    const caseBtn = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(caseBtn).toBeVisible();
    if (await caseBtn.getAttribute('aria-pressed') !== 'true') {
      await caseBtn.click();
    }
    await page.getByRole('tab', { name: 'Maps', exact: true }).click();
    await expect(page.getByTestId('maplibre-view')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('maplibre-container')).toBeVisible();
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      return Boolean(
        map?.getSource('pickup-route-source') &&
        map?.getSource('destination-route-source') &&
        map?.getSource('trip-points-source'),
      );
    })).toBe(true);
    await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
    const timeline = page.getByTestId('trip-timeline-bar');
    const marks = page.getByTestId('timeline-checkpoint-marks');
    await expect(marks.locator('[role="img"]')).toHaveCount(3);
    await expect(marks.locator('button, details, summary')).toHaveCount(0);
    await expect(timeline.getByRole('button')).toHaveCount(1);
    await expect(marks).toHaveCSS('pointer-events', 'none');
    await expect(page.getByTestId('milestone-pickup')).toHaveCSS('width', '2px');
    const track = await page.getByTestId('timeline-scrubber-slider').boundingBox();
    const mark = await page.getByTestId('milestone-pickup').boundingBox();
    expect(Math.abs(mark!.y + mark!.height / 2 - track!.y - track!.height / 2)).toBeLessThan(1);
    await expect(page.getByTestId('driver-vehicle-marker')).toHaveAccessibleName('Tài xế · Xe máy');
    await expect(page.getByTestId('driver-vehicle-marker').locator('svg').first()).toHaveAttribute('data-icon', 'motorbike');
    for (const [testId, icon, size] of [
      ['driver-initial-marker', 'initial', 24], ['customer-pickup-marker', 'pickup', 24],
      ['destination-marker', 'destination', 24], ['driver-vehicle-marker', 'motorbike', 28],
    ] as const) {
      const marker = page.getByTestId(testId);
      await expect(marker).toBeVisible();
      await expect(marker.locator('svg').first()).toHaveAttribute('data-icon', icon);
      const box = await marker.boundingBox();
      expect(box!.width).toBe(size);
      expect(box!.height).toBe(size);
    }
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const coordinates = ['pickup-route-source', 'destination-route-source'].flatMap((id) => {
        const raw = map.getSource(id)._data;
        const data = raw?.data ?? raw;
        const geojson = data?.geojson ?? data;
        const geometry = geojson?.geometry;
        return geometry?.coordinates ?? [];
      });
      const canvas = document.querySelector('[data-testid="maplibre-container"] canvas') as HTMLCanvasElement | null;
      const inViewport = (coordinate: [number, number]) => {
        const point = map.project(coordinate);
        return canvas && point.x >= 0 && point.y >= 0 && point.x <= canvas.clientWidth && point.y <= canvas.clientHeight;
      };
      return {
        sourceLoaded: ['pickup-route-source', 'destination-route-source'].every((id) => map.isSourceLoaded(id)),
        rendered: map.queryRenderedFeatures(undefined, { layers: ['pickup-route-line', 'destination-route-line'] }).length,
        endpointsVisible: coordinates.length > 1 && inViewport(coordinates[0]) && inViewport(coordinates.at(-1)),
      };
    })).toEqual({ sourceLoaded: true, rendered: expect.any(Number), endpointsVisible: true });
    // debb2ee: with classified trip segments the legs render as trip-seg-* layers; pickup/destination-route-line are hidden.
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      return map.queryRenderedFeatures(undefined, { layers: ['trip-seg-solid', 'trip-seg-dashed'] }).length;
    })).toBeGreaterThan(0);
    const beforeScrub = await page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const data = (id: string) => {
        const source = map.getSource(id);
        const raw = source._data ?? source.serialize().data ?? map.getStyle().sources[id].data;
        const data = raw.data ?? raw;
        return data.geojson ?? data;
      };
      return {
        pickup: JSON.stringify(data('pickup-route-source')),
        destination: JSON.stringify(data('destination-route-source')),
        points: JSON.stringify(data('trip-points-source')),
      };
    });
    expect(beforeScrub.pickup).toContain(JSON.stringify(
      manifest.route_snapshots.find((snapshot) => snapshot.leg === 'pickup')?.route_geojson.coordinates,
    ));
    expect(beforeScrub.destination).toContain(JSON.stringify(
      manifest.route_snapshots.find((snapshot) => snapshot.leg === 'destination')?.route_geojson.coordinates,
    ));
    expect(beforeScrub.points).toContain(JSON.stringify([
      firstEvent.payload.position.longitude,
      firstEvent.payload.position.latitude,
    ]));

    const scrubber = page.getByTestId('timeline-scrubber-slider');
    await expect(scrubber).toHaveAttribute('max', /[1-9]/);
    await scrubber.fill(String(scrubSeconds));
    await expect(page.getByTestId('speedometer-readout')).toContainText(
      `${(scrubEvent.payload.speed_mps * 3.6).toFixed(1)} km/h`,
    );
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const source = map.getSource('trip-points-source');
      const raw = source._data ?? source.serialize().data ?? map.getStyle().sources['trip-points-source'].data;
      const data = (raw.data ?? raw).geojson ?? (raw.data ?? raw);
      return JSON.stringify(data);
    })).toContain(JSON.stringify([
      scrubEvent.payload.position.longitude,
      scrubEvent.payload.position.latitude,
    ]));

    // Verify motion between fixes, where nearest-sample playback used to jump.
    await scrubber.fill((scrubSeconds / 2).toFixed(3));
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'interpolated');
    await page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const center = map.getCenter();
      map.jumpTo({ center: [center.lng + 0.0005, center.lat], zoom: map.getZoom() + 0.2 });
    });
    await page.getByRole('button', { name: /Replay/ }).click();
    const motion = await page.evaluate(async () => {
      const map = (window as any).__maplibreInstance;
      const frames: Array<{ elapsed: number; cursor: number; coordinate: number[]; center: number[]; zoom: number }> = [];
      const started = performance.now();
      for (let i = 0; i < 16; i++) {
        const raw = map.getSource('trip-points-source').serialize().data;
        const data = raw.geojson ?? raw;
        const center = map.getCenter();
        frames.push({ elapsed: (performance.now() - started) / 1000,
          cursor: Number((document.querySelector('[data-testid="timeline-scrubber-slider"]') as HTMLInputElement).value),
          coordinate: data.features.find((f: any) => f.properties.kind === 'driver').geometry.coordinates,
          center: [center.lng, center.lat], zoom: map.getZoom() });
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      return frames;
    });
    await page.getByRole('button', { name: /Pause/ }).click();
    const first = motion[0], last = motion.at(-1)!;
    expect(last.cursor - first.cursor).toBeCloseTo(last.elapsed - first.elapsed, 0);
    expect(last.cursor - first.cursor).toBeGreaterThan(1);
    expect(last.coordinate).not.toEqual(first.coordinate);
    const meters = (a: number[], b: number[]) => Math.hypot((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), b[1] - a[1]) * 111_195;
    for (let i = 1; i < motion.length; i++) {
      expect(meters(motion[i - 1].coordinate, motion[i].coordinate)).toBeLessThan(50 * (motion[i].elapsed - motion[i - 1].elapsed) + 2);
      expect(motion[i].center).toEqual(first.center);
      expect(motion[i].zoom).toEqual(first.zoom);
    }
    const pickup = manifest.route_snapshots.find((snapshot) => snapshot.leg === 'pickup')!.route_geojson.coordinates;
    for (const frame of motion) {
      const p = frame.coordinate;
      const distanceToRoad = Math.min(...pickup.slice(1).map((b, i) => {
        const a = pickup[i], dx = b[0] - a[0], dy = b[1] - a[1];
        const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
        return meters(p, [a[0] + dx * t, a[1] + dy * t]);
      }));
      expect(distanceToRoad).toBeLessThan(2);
    }
    await page.setViewportSize({ width: 375, height: 812 });
    await page.getByTestId('maplibre-view').scrollIntoViewIfNeeded();
    await expect.poll(() => page.getByTestId('maplibre-view').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
    await expect(page.getByTestId('driver-vehicle-marker')).toHaveCSS('width', '28px');
    await expect(page.getByTestId('customer-pickup-marker')).toHaveCSS('width', '24px');
    await expect(marks.locator('button, details, summary')).toHaveCount(0);
    await expect(page.getByTestId('milestone-pickup')).toHaveCSS('width', '2px');
  });
});
