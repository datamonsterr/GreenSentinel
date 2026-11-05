import os from 'os';
import fs from 'fs';
import path from 'path';

import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1280, height: 720 } });

interface MapSourceLike {
  _data?: unknown;
  serialize?(): { data: unknown };
}
interface MapLike {
  getSource(id: string): MapSourceLike | undefined;
  getLayer(id: string): unknown;
  getStyle(): { sources: Record<string, { data: unknown }> };
  queryRenderedFeatures(...args: unknown[]): Array<{ geometry: { coordinates: number[] } }>;
}
interface SourceGeometry {
  type: string;
  coordinates: unknown;
}
interface SourceData {
  features?: Array<{ properties: Record<string, unknown>; geometry: SourceGeometry }>;
  geometry?: SourceGeometry;
}
interface TelemetryRow {
  occurred_at?: string;
  recorded_at?: string;
  position?: { coordinates: number[] };
}
interface AlertRow {
  start_time: string;
  end_time: string;
  gap_duration_s: number;
  reason: string;
}

test.describe('road telemetry fixture in the real browser map', () => {
  test('renders both canonical legs and scrubs canonical telemetry from backend', async ({ page, request }) => {
    // Check prerequisites
    if (!process.env.ISSUE61_DATABASE_URL) {
      throw new Error('local API/database prerequisites are unavailable');
    }

    const CASE_ID = '4f1dd091-33f2-5a3a-9a7c-948afe9ec637';

    // Fetch the real persisted data from the backend to assert against
    const res = await request.get(`/api/v1/cases/${CASE_ID}`);
    expect(res.ok()).toBeTruthy();
    const caseDetail = await res.json();

    expect(caseDetail.case.id).toBe(CASE_ID);
    expect(caseDetail.telemetry_samples).toEqual(expect.any(Array));
    const telemetry = caseDetail.telemetry_samples;
    const backendPickup = caseDetail.trip?.pickup?.coordinates;
    const backendDropoff = caseDetail.trip?.dropoff?.coordinates;
    const backendPickupRoute = caseDetail.route_geometry?.pickup_route?.coordinates;
    const backendDestRoute = caseDetail.route_geometry?.destination_route?.coordinates;
    for (const coordinate of [backendPickup, backendDropoff]) {
      expect(coordinate).toEqual([expect.any(Number), expect.any(Number)]);
      expect(coordinate.every(Number.isFinite)).toBe(true);
    }
    for (const route of [backendPickupRoute, backendDestRoute]) {
      expect(route).toEqual(expect.any(Array));
      expect(route.length).toBeGreaterThan(1);
      for (const coordinate of route) {
        expect(coordinate).toEqual([expect.any(Number), expect.any(Number)]);
        expect(coordinate.every(Number.isFinite)).toBe(true);
      }
    }
    expect(telemetry.length).toBeGreaterThan(1);
    const firstEvent = telemetry.find((event: any) =>
      event.position?.coordinates?.length === 2 &&
      event.position.coordinates.every(Number.isFinite) &&
      Number.isFinite(Date.parse(event.occurred_at || event.recorded_at)));
    expect(firstEvent).toBeDefined();
    expect(firstEvent).toEqual(telemetry[0]);
    const scrubEvent = telemetry[1];
    const firstTime = Date.parse(firstEvent.occurred_at || firstEvent.recorded_at);
    const scrubTime = Date.parse(scrubEvent.occurred_at || scrubEvent.recorded_at);
    const scrubSeconds = (scrubTime - firstTime) / 1000;
    expect(Number.isFinite(scrubSeconds)).toBe(true);
    expect(scrubSeconds).toBeGreaterThan(0);

    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));

    // The queue defaults to available cases. Select by case identity, not button index.
    const queueRes = await request.get('/api/v1/cases?availability=available');
    expect(queueRes.ok()).toBeTruthy();
    const cases = await queueRes.json();
    expect(cases.items).toEqual(expect.arrayContaining([expect.objectContaining({ id: CASE_ID })]));

    const selectedResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/v1/cases/${CASE_ID}` &&
      response.request().method() === 'GET');
    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const canonicalCase = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(canonicalCase).toHaveCount(1);
    await canonicalCase.click();
    await expect(canonicalCase).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('tab', { name: 'Maps' }).click();
    const selected = await selectedResponse;
    expect(selected.ok()).toBeTruthy();
    expect((await selected.json()).case.id).toBe(CASE_ID);

    const timeline = page.getByTestId('trip-timeline-bar');
    const marks = page.getByTestId('timeline-checkpoint-marks');

    // Require the canonical roles and their recorded lifecycle times; additional milestones are allowed.
    // Pickup anchors to the recorded arrival at pickup, never the penultimate telemetry sample.
    const seed = JSON.parse(fs.readFileSync(
      path.resolve(process.cwd(), '../../tests/fixtures/road_telemetry/normal_trip.json'), 'utf8'));
    const recordedArrival = seed.trip_assignment.arrived_at;
    const recordedEnd = seed.trip_assignment.ended_at;
    expect(Number.isFinite(Date.parse(recordedArrival))).toBe(true);
    expect(Number.isFinite(Date.parse(recordedEnd))).toBe(true);
    const expectedMilestones = [
      { type: 'start_match', event: firstEvent, label: 'Điểm bắt đầu' },
      { type: 'pickup', event: { occurred_at: recordedArrival }, label: 'Điểm đón khách (Pickup Point)' },
      { type: 'dropoff_destination', event: { occurred_at: recordedEnd }, label: 'Đích đến (Dropoff Destination)' },
    ];
    expect(caseDetail.timeline_milestones).toEqual(expect.any(Array));
    for (const { type, event, label } of expectedMilestones) {
      const expectedTime = Date.parse(event.occurred_at || event.recorded_at);
      expect(Number.isFinite(expectedTime)).toBe(true);
      const milestone = caseDetail.timeline_milestones.find((item: any) => item.type === type);
      expect(milestone, `Required milestone ${type}`).toBeDefined();
      expect(Date.parse(milestone.timestamp)).toBe(expectedTime);
      const mark = marks.getByTestId(`milestone-${type}`);
      await expect(mark).toBeVisible();
      await expect(mark).toHaveAttribute('aria-label', `${label} (${milestone.timestamp})`);
    }
    await expect(marks.locator('button, details, summary')).toHaveCount(0);
    await expect(timeline.getByRole('button')).toHaveCount(1);
    await expect(marks).toHaveCSS('pointer-events', 'none');

    // Static rendered markers retain the exact persisted source coordinates.
    for (const [testId, coordinate] of [
      ['driver-initial-marker', firstEvent.position.coordinates],
      ['customer-pickup-marker', backendPickup],
      ['destination-marker', backendDropoff],
    ] as const) {
      const marker = page.getByTestId(testId);
      await expect(marker).toBeVisible();
      await expect(marker).toHaveAttribute('data-longitude', String(coordinate[0]));
      await expect(marker).toHaveAttribute('data-latitude', String(coordinate[1]));
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

    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      return map.queryRenderedFeatures(undefined, { layers: ['pickup-route-line', 'destination-route-line'] }).length;
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
        pickup: data('pickup-route-source').geometry.coordinates,
        destination: data('destination-route-source').geometry.coordinates,
        points: data('trip-points-source').features.map((feature: any) => ({
          kind: feature.properties.kind, coordinates: feature.geometry.coordinates,
        })),
      };
    });

    expect(beforeScrub.pickup).toEqual(backendPickupRoute);
    expect(beforeScrub.destination).toEqual(backendDestRoute);
    for (const [kind, coordinates] of [
      ['initial', firstEvent.position.coordinates],
      ['pickup', backendPickup],
      ['destination', backendDropoff],
      ['driver', firstEvent.position.coordinates],
    ] as const) {
      expect(beforeScrub.points.filter((point: any) => point.kind === kind)).toEqual([{ kind, coordinates }]);
    }

    const scrubber = page.getByTestId('timeline-scrubber-slider');
    await expect(scrubber).toHaveAttribute('max', /[1-9]/);

    // Native keyboard controls update the same recorded replay state.
    await scrubber.focus();
    await scrubber.press('Home');
    await expect(scrubber).toHaveValue('0');
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'observed');
    await scrubber.press('ArrowRight');
    await expect(scrubber).toHaveValue('0.001');
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'interpolated');
    await scrubber.press('ArrowLeft');
    await expect(scrubber).toHaveValue('0');
    await expect(scrubber).toBeFocused();
    await scrubber.press('End');
    await expect(scrubber).toHaveValue((await scrubber.getAttribute('max'))!);
    await scrubber.press('Home');
    const rangeBounds = (await scrubber.boundingBox())!;
    await page.mouse.move(rangeBounds.x + 6, rangeBounds.y + rangeBounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(rangeBounds.x + rangeBounds.width / 4, rangeBounds.y + rangeBounds.height / 2, { steps: 8 });
    await page.mouse.up();
    expect(Number(await scrubber.inputValue())).toBeGreaterThan(0);
    expect(Number(await scrubber.inputValue())).toBeLessThan(Number(await scrubber.getAttribute('max')));

    // Exact observed speed at seek
    await scrubber.fill(String(scrubSeconds));

    await expect(page.getByTestId('speedometer-readout')).toContainText(
      `${(scrubEvent.speed_mps * 3.6).toFixed(1)} km/h`,
    );
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const source = map.getSource('trip-points-source');
      const raw = source._data ?? source.serialize().data ?? map.getStyle().sources['trip-points-source'].data;
      const data = (raw.data ?? raw).geojson ?? (raw.data ?? raw);
      return data.features.find((feature: any) => feature.properties.kind === 'driver').geometry.coordinates;
    })).toEqual(scrubEvent.position.coordinates);

    // Both expected legs and the observed trajectory must actually render with distinct styles.
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      return ['pickup-route-line', 'destination-route-line', 'driver-trajectory-line'].map((id) => ({
        rendered: map.queryRenderedFeatures(undefined, { layers: [id] }).length > 0,
        visibility: map.getLayoutProperty(id, 'visibility'),
        color: map.getPaintProperty(id, 'line-color'),
        width: map.getPaintProperty(id, 'line-width'),
      }));
    })).toEqual([
      { rendered: true, visibility: 'visible', color: '#2563eb', width: 3.5 },
      { rendered: true, visibility: 'visible', color: '#7c3aed', width: 3.5 },
      { rendered: true, visibility: 'visible', color: '#ea580c', width: 4.5 },
    ]);

    // Bounded/labeled estimate between fixes and manual camera stability
    await scrubber.fill((scrubSeconds / 2).toFixed(3));
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'interpolated');
    const readCamera = () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      const center = map.getCenter();
      return { center: [center.lng, center.lat], zoom: map.getZoom(), moving: map.isMoving() };
    });
    const cameraBeforePan = await readCamera();
    const canvasBounds = (await page.getByTestId('maplibre-container').locator('canvas').boundingBox())!;
    const canvasX = canvasBounds.x + canvasBounds.width / 2;
    const canvasY = canvasBounds.y + canvasBounds.height / 2;
    await page.mouse.move(canvasX, canvasY);
    await page.mouse.down();
    await page.mouse.move(canvasX + 30, canvasY + 15, { steps: 8 });
    await page.mouse.up();
    await expect.poll(async () => (await readCamera()).center).not.toEqual(cameraBeforePan.center);
    await page.mouse.move(canvasX, canvasY);
    await page.mouse.wheel(0, -120);
    await expect.poll(async () => (await readCamera()).zoom).toBeGreaterThan(cameraBeforePan.zoom);
    await expect.poll(async () => (await readCamera()).moving).toBe(false);

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

    await page.getByRole('button', { name: /Tạm dừng/ }).click();
    const first = motion[0], last = motion.at(-1)!;
    expect(last.cursor - first.cursor).toBeCloseTo(last.elapsed - first.elapsed, 0);
    expect(last.cursor - first.cursor).toBeGreaterThan(1);
    expect(last.coordinate).not.toEqual(first.coordinate);
    const meters = (a: number[], b: number[]) => Math.hypot((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), b[1] - a[1]) * 111_195;

    // Manual camera stability: center and zoom must not change during motion
    for (let i = 1; i < motion.length; i++) {
      expect(meters(motion[i - 1].coordinate, motion[i].coordinate)).toBeLessThan(50 * (motion[i].elapsed - motion[i - 1].elapsed) + 2);
      expect(motion[i].center).toEqual(first.center);
      expect(motion[i].zoom).toEqual(first.zoom);
    }

    for (const frame of motion) {
      const p = frame.coordinate;
      const distanceToRoad = Math.min(...backendPickupRoute.slice(1).map((b: number[], i: number) => {
        const a = backendPickupRoute[i], dx = b[0] - a[0], dy = b[1] - a[1];
        const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
        return meters(p, [a[0] + dx * t, a[1] + dy * t]);
      }));
      expect(distanceToRoad).toBeLessThan(2);
    }

    // A page reload starts a new replay session and still retrieves the same source evidence.
    await page.reload();
    await canonicalCase.click();
    await expect(canonicalCase).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('tab', { name: 'Maps' }).click();
    await expect(page.getByTestId('driver-initial-marker')).toHaveAttribute('data-longitude', String(firstEvent.position.coordinates[0]));
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as any).__maplibreInstance;
      if (!map?.getSource('pickup-route-source') || !map.getSource('destination-route-source')) return null;
      const coordinates = (id: string) => {
        const raw = map.getSource(id).serialize().data;
        const data = (raw.data ?? raw).geojson ?? (raw.data ?? raw);
        return data.geometry.coordinates;
      };
      return [coordinates('pickup-route-source'), coordinates('destination-route-source')];
    })).toEqual([backendPickupRoute, backendDestRoute]);
  });

  test('renders persisted GPS gap warnings with an accessible tooltip from real telemetry', async ({ page, request }, testInfo) => {
    if (!process.env.ISSUE61_DATABASE_URL) {
      throw new Error('local API/database prerequisites are unavailable');
    }

    const CASE_ID = '0fa6dbcb-9a37-5389-9fbc-1a15e825291d';
    const GAP_SECONDS = 60;

    const res = await request.get(`/api/v1/cases/${CASE_ID}`);
    expect(res.ok()).toBeTruthy();
    const caseDetail = await res.json();
    const telemetry = caseDetail.telemetry_samples as TelemetryRow[];
    expect(telemetry).toHaveLength(5);
    const recordedAt = (event: TelemetryRow) => event.occurred_at ?? event.recorded_at ?? '';
    const positioned = telemetry.filter((event) => {
      const coordinates = event.position?.coordinates;
      return coordinates?.length === 2 && coordinates.every(Number.isFinite);
    });
    expect(positioned.length).toBeGreaterThan(1);
    expect(positioned.map((event) => event.position!.coordinates)).toEqual([
      [105.853875, 21.028501],
      [105.853851, 21.029524],
      [105.853828, 21.030548],
      [105.853804, 21.031571],
    ]);
    const alert = (caseDetail.missingness_alerts as AlertRow[])[0];
    expect(alert.gap_duration_s).toBe(GAP_SECONDS);
    expect(alert.reason).toContain('Tín hiệu GPS không khả dụng');
    const gapStartClock = alert.start_time.slice(11, 19);
    const gapEndClock = alert.end_time.slice(11, 19);
    const firstTime = Date.parse(recordedAt(positioned[0]));
    const anchor = positioned.filter((event) => Date.parse(recordedAt(event)) <= Date.parse(alert.start_time)).at(-1)!;
    const anchorCoordinates = [105.853804, 21.031571];
    expect(anchor.position?.coordinates).toEqual(anchorCoordinates);
    const gapMidSecond = (Date.parse(alert.start_time) + (Date.parse(alert.end_time) - Date.parse(alert.start_time)) / 2 - firstTime) / 1000;

    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));

    const selectedResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/v1/cases/${CASE_ID}` &&
      response.request().method() === 'GET');
    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const canonicalCase = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(canonicalCase).toHaveCount(1);
    await canonicalCase.click();
    expect((await (await selectedResponse).json()).case.id).toBe(CASE_ID);

    const scrubber = page.getByTestId('timeline-scrubber-slider');

    // Red dashed warning band anchored to the exact recorded gap window.
    const band = page.locator(`[data-testid="timeline-gap-band"][aria-label*="${gapStartClock}"][aria-label*="${gapEndClock}"]`);
    await expect(band).toHaveCount(1);
    await expect(band).toHaveAttribute('aria-label', new RegExp(`Mất dữ liệu GPS ${GAP_SECONDS}s.*Tín hiệu GPS không khả dụng`));
    await expect(page.getByTestId('timeline-gap-bands')).toHaveCSS('pointer-events', 'none');

    // Persistent passive explanation exposing timestamps, duration and reason.
    const tooltip = page.locator('[data-testid="timeline-gap-tooltip"]').filter({ hasText: gapStartClock }).filter({ hasText: gapEndClock });
    await expect(tooltip).toHaveCount(1);
    await expect(tooltip).not.toHaveAttribute('role', 'status');
    await expect(tooltip).toContainText(new RegExp(`${gapStartClock}.*${gapEndClock}`));
    await expect(tooltip).toContainText(new RegExp(`${GAP_SECONDS}s`));
    await expect(tooltip).toContainText('Tín hiệu GPS không khả dụng');
    const tooltipId = await tooltip.getAttribute('id');
    expect(tooltipId).toBeTruthy();
    await expect(scrubber).toHaveAttribute('aria-describedby', new RegExp(`(^| )${tooltipId}( |$)`));
    await expect(tooltip).not.toHaveAttribute('tabindex');
    const describedBy = await scrubber.getAttribute('aria-describedby');
    for (const id of describedBy?.split(/\s+/) ?? []) {
      await expect(page.locator(`#${id}`)).toHaveCount(1);
    }

    // The dedicated gap-warnings overlay stays separate from the measured trail.
    await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      return Boolean(map?.getSource('gap-warnings-source') && map?.getLayer('gap-warnings'));
    })).toBe(true);
    await expect.poll(async () => page.evaluate((anchor) => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      if (!map) return false;
      const meters = (a: number[], b: number[]) => Math.hypot((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), b[1] - a[1]) * 111_195;
      // Rendered geometry is quantized to the internal tile grid (~9m at zoom 9), so match by tolerance.
      return (map.queryRenderedFeatures(undefined, { layers: ['gap-warnings'] }) ?? [])
        .some((feature) => meters(feature.geometry.coordinates, anchor) < 20);
    }, anchorCoordinates)).toBe(true);

    await scrubber.fill(String(gapMidSecond));
    // At a missing interval, any measured trail ends at the last observed fix.
    // An unmatched road may also have no line; it must never advance past the fix.
    const priorFixes = positioned.filter((event) => Date.parse(recordedAt(event)) <= Date.parse(alert.start_time)).map((event) => event.position!.coordinates);
    await expect.poll(async () => page.evaluate((allowed) => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      const source = map?.getSource('driver-trajectory-source');
      let data = source?.serialize?.().data ?? source?._data;
      for (let depth = 0; depth < 4 && data && typeof data === 'object'; depth++) {
        const wrapped = data as { type?: string; data?: unknown; geojson?: unknown };
        if (wrapped.type) break;
        data = wrapped.geojson ?? wrapped.data;
      }
      const geometry = (data as SourceData | undefined)?.geometry;
      if (!geometry) return true;
      const paths = geometry.type === 'MultiLineString' ? geometry.coordinates as number[][][] : [geometry.coordinates as number[][]];
      const last = paths.at(-1)?.at(-1);
      return Boolean(last && allowed.some((fix) => Math.hypot(last[0] - fix[0], last[1] - fix[1]) * 111195 < 2));
    }, priorFixes)).toBe(true);

    // Source GPS dots remain available even when the unknown road trail is empty.
    const expectedObserved = positioned.filter((event) => Date.parse(recordedAt(event)) <= (Date.parse(alert.start_time) + Date.parse(alert.end_time)) / 2)
      .map((event) => event.position!.coordinates);
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      const raw = map?.getSource('driver-observations-source')?._data ?? map?.getSource('driver-observations-source')?.serialize?.().data;
      const data = (raw as { data?: SourceData; geojson?: SourceData } | undefined)?.data ?? (raw as { geojson?: SourceData } | undefined)?.geojson ?? raw as SourceData | undefined;
      return data?.features?.map((feature) => feature.geometry.coordinates);
    })).toEqual(expectedObserved);

    // Playback inside the gap holds the pre-gap source fix without inventing motion.
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'gap');
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      const source = map?.getSource('trip-points-source');
      const raw = source?._data ?? source?.serialize?.().data ?? map?.getStyle().sources['trip-points-source']?.data;
      const data = (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.geojson
        ?? (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.data
        ?? (raw as SourceData | undefined);
      return data?.features?.find((feature) => feature.properties.kind === 'driver')?.geometry.coordinates ?? null;
    })).toEqual(anchorCoordinates);
    await testInfo.attach('gap-desktop', { body: await page.screenshot(), contentType: 'image/png' });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(scrubber).toBeVisible();
    await scrubber.focus();
    await expect(scrubber).toBeFocused();
    // focus() only guarantees minimal scroll; taller post-Oct-7 content leaves
    // the scrubber below the inner scrollport (probed 78px shy), where the
    // point is correctly owned by the in-flow footer. Settle it fully into
    // view first so the hit test measures clickability, not scroll state.
    await scrubber.scrollIntoViewIfNeeded();
    expect(await scrubber.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      const x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2;
      return y >= 0 && y <= innerHeight && document.elementFromPoint(x, y) === element;
    })).toBe(true);
    await expect(scrubber).toHaveAccessibleDescription(new RegExp(`${gapStartClock}.*${gapEndClock}`));
    await expect(page.getByTestId('timeline-gap-info').locator('[tabindex]')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    const mobileRange = (await scrubber.boundingBox())!;
    await page.mouse.click(mobileRange.x + mobileRange.width / 2, mobileRange.y + mobileRange.height / 2);
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'gap');
    await scrubber.press('Home');
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'observed');
    await scrubber.press('End');
    await expect(page.getByTestId('playback-quality')).toHaveAttribute('data-mode', 'gap');
    await testInfo.attach('gap-mobile-375px', { body: await page.screenshot(), contentType: 'image/png' });

    // 200% layout zoom at desktop width keeps native controls usable.
    await page.setViewportSize({ width: 1280, height: 1440 });
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
    // Vertical scrolling is expected at 200%; the range must remain reachable.
    await scrubber.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280);
    expect(await scrubber.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2) === element;
    })).toBe(true);
    await scrubber.press('Home');
    await expect(scrubber).toHaveValue('0');
    await expect(scrubber).toHaveAccessibleDescription(new RegExp(`${gapStartClock}.*${gapEndClock}`));
    await testInfo.attach('gap-desktop-200-percent-layout-zoom', { body: await page.screenshot(), contentType: 'image/png' });
  });

  test('shows the explicit unavailable GPS and traffic states for a case with no persisted telemetry', async ({ page, request }) => {
    if (!process.env.ISSUE61_DATABASE_URL) {
      throw new Error('local API/database prerequisites are unavailable');
    }

    const CASE_ID = '93c6b9d7-7655-52d5-a789-255d1cee1a57';

    const res = await request.get(`/api/v1/cases/${CASE_ID}`);
    expect(res.ok()).toBeTruthy();
    const caseDetail = await res.json();
    expect(caseDetail.telemetry_samples).toEqual([]);
    expect(caseDetail.missingness_alerts).toEqual([]);
    expect(Object.keys(caseDetail.route_geometry).sort()).toEqual(['destination_route', 'pickup_route']);
    expect(caseDetail.traffic_corroboration).toBeNull();

    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));

    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const absentCase = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(absentCase).toHaveCount(1);
    await absentCase.click();
    await page.getByRole('tab', { name: 'Maps' }).click();

    const label = page.getByTestId('gps-unavailable-label');
    await expect(label).toBeVisible();
    await expect(label).toContainText('Tín hiệu GPS: Không khả dụng');

    // Absent traffic observations surface the dedicated unavailable traffic state.
    const traffic = page.getByTestId('traffic-corroboration-panel');
    await expect(traffic).toBeVisible();
    await expect(traffic).toHaveText('Chưa có dữ liệu giao thông');

    // Nothing may be invented for the missing trail: no driver marker, no breadcrumb geometry.
    await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
    await expect(page.getByTestId('driver-initial-marker')).toHaveCount(0);
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      if (!map) return null;
      const trail = map.getSource('driver-trajectory-source');
      const raw = trail?._data ?? trail?.serialize?.().data ?? map.getStyle().sources['driver-trajectory-source']?.data;
      const data = (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.geojson
        ?? (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.data
        ?? (raw as SourceData | undefined);
      return data?.features?.length ?? -1;
    })).toBe(0);

    // Seeded routing evidence still renders for both legs despite the missing telemetry.
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      if (!map) return [false, false];
      return ['pickup-route-line', 'destination-route-line'].map((id) =>
        map.queryRenderedFeatures(undefined, { layers: [id] }).length > 0);
    })).toEqual([true, true]);
  });

  test('renders the persisted GPS-unavailable gap band seeded through the real ingest API', async ({ page, request }) => {
    if (!process.env.ISSUE61_DATABASE_URL) {
      throw new Error('local API/database prerequisites are unavailable');
    }

    const CASE_ID = '0fa6dbcb-9a37-5389-9fbc-1a15e825291d';
    const GAP_SECONDS = 60;

    const res = await request.get(`/api/v1/cases/${CASE_ID}`);
    expect(res.ok()).toBeTruthy();
    const caseDetail = await res.json();
    const telemetry = caseDetail.telemetry_samples as TelemetryRow[];
    const unavailable = telemetry.filter((event) => event.position?.coordinates?.length !== 2);
    expect(unavailable.length).toBe(1);
    expect(caseDetail.missingness_alerts).toEqual([
      expect.objectContaining({
        gap_duration_s: GAP_SECONDS,
        reason: `Tín hiệu GPS không khả dụng trong ${GAP_SECONDS}.0s`,
        severity: 'critical',
      }),
      expect.objectContaining({
        gap_duration_s: 570,
        end_time: '2026-09-22T07:11:00+00:00',
        severity: 'critical',
      }),
    ]);

    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));

    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const gapCase = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(gapCase).toHaveCount(1);
    await gapCase.click();
    await page.getByRole('tab', { name: 'Maps' }).click();

    await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
    const band = page.locator(`[data-testid="timeline-gap-band"][aria-label*="${GAP_SECONDS}s"]`);
    await expect(band).toHaveCount(1);
    await expect(band).toHaveAttribute('aria-label', new RegExp(`Mất dữ liệu GPS ${GAP_SECONDS}s.*Tín hiệu GPS không khả dụng`));
  });

  test('keeps an unavailable routing leg uninvented and labels the route state', async ({ page, request }) => {
    if (!process.env.ISSUE61_DATABASE_URL) {
      throw new Error('local API/database prerequisites are unavailable');
    }

    const CASE_ID = '48c5b3f6-f887-53b6-9301-8df2ef15f5dc';

    const res = await request.get(`/api/v1/cases/${CASE_ID}`);
    expect(res.ok()).toBeTruthy();
    const caseDetail = await res.json();
    expect(Object.keys(caseDetail.route_geometry)).toEqual(['pickup_route']);
    expect(caseDetail.route_geometry.pickup_route.provenance.status).toBe('ok');
    expect(caseDetail.route_geometry.destination_route).toBeUndefined();

    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8,
      sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));

    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const routeCase = queue.getByRole('button', { name: new RegExp(`#${CASE_ID.slice(-8)}`) });
    await expect(routeCase).toHaveCount(1);
    await routeCase.click();
    await page.getByRole('tab', { name: 'Maps' }).click();

    const label = page.getByTestId('missing-route-destination');
    await expect(label).toBeVisible();
    await expect(label).toContainText('Lộ trình trả khách: Không khả dụng');
    await expect(page.getByTestId('missing-route-both')).toHaveCount(0);
    await expect(page.getByTestId('missing-route-pickup')).toHaveCount(0);

    // The missing leg stays empty in the map state; only the recorded pickup leg renders.
    await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      if (!map) return null;
      const source = map.getSource('destination-route-source');
      const raw = source?._data ?? source?.serialize?.().data ?? map.getStyle().sources['destination-route-source']?.data;
      const data = (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.geojson
        ?? (raw as { geojson?: SourceData; data?: SourceData } | undefined)?.data
        ?? (raw as SourceData | undefined);
      const coordinates = data?.geometry?.coordinates as number[] | undefined;
      return coordinates?.length ?? data?.features?.length ?? -1;
    })).toBe(0);
    await expect.poll(async () => page.evaluate(() => {
      const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
      if (!map) return false;
      return map.queryRenderedFeatures(undefined, { layers: ['pickup-route-line'] }).length > 0;
    })).toBe(true);
  });

  test('renders selected persisted routes and observed GPS within the 1.5s budget', async ({ page, request }, testInfo) => {
    test.setTimeout(240_000);
    const caseId = '4f1dd091-33f2-5a3a-9a7c-948afe9ec637';
    const persistedResponse = await request.get(`/api/v1/cases/${caseId}`);
    expect(persistedResponse.ok()).toBe(true);
    const persisted = await persistedResponse.json();
    const expectedGps = persisted.telemetry_samples.find((sample: TelemetryRow) => sample.position?.coordinates)?.position.coordinates;
    expect(expectedGps).toEqual([expect.any(Number), expect.any(Number)]);
    // Use a known empty observation state. An arbitrary queue case can have no GPS
    // or share the target's first coordinate, so coordinate inequality is invalid.
    const otherCaseId = '93c6b9d7-7655-52d5-a789-255d1cee1a57';
    const otherResponse = await request.get(`/api/v1/cases/${otherCaseId}`);
    expect(otherResponse.ok()).toBe(true);
    const otherPersisted = await otherResponse.json();
    expect(otherPersisted.case.id).toBe(otherCaseId);
    expect(otherPersisted.telemetry_samples).toEqual([]);
    await page.route('**/styles/liberty', (route) => route.fulfill({ json: {
      version: 8, sources: {},
      layers: [{ id: 'test-background', type: 'background', paint: { 'background-color': '#f8fafc' } }],
    } }));
    await page.goto('/workplace');
    const queue = page.getByRole('region', { name: 'Triage queue' });
    const otherCase = queue.getByRole('button', { name: new RegExp(`#${otherCaseId.slice(-8)}`) });
    const target = queue.getByRole('button', { name: new RegExp(`#${caseId.slice(-8)}`) });
    await expect(otherCase).toHaveCount(1);
    await expect(target).toHaveCount(1);
    const budgetMs = 1500;
    const samples: Array<{ elapsedMs: number; completed: boolean }> = [];
    const selectOther = async () => {
      if (await otherCase.getAttribute('aria-pressed') !== 'true') {
        const response = page.waitForResponse((item) =>
          new URL(item.url()).pathname === `/api/v1/cases/${otherCaseId}` &&
          item.request().method() === 'GET');
        await otherCase.click();
        await page.getByRole('tab', { name: 'Maps' }).click();
        const selected = await response;
        expect(selected.ok()).toBe(true);
        expect((await selected.json()).case.id).toBe(otherCaseId);
      }
      await expect(otherCase).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('maplibre-container')).toBeVisible();
      await expect(page.locator('.maplibregl-canvas')).toBeVisible();
      await expect(page.getByTestId('map-loading-overlay')).toBeHidden();
      // Require the API-verified empty state before measuring a fresh target selection.
      await expect.poll(() => page.evaluate(() => {
        const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
        const source = map?.getSource('driver-observations-source');
        const raw = source?._data ?? source?.serialize?.().data;
        const data = (raw as { data?: SourceData; geojson?: SourceData } | undefined)?.data ?? (raw as { geojson?: SourceData } | undefined)?.geojson ?? raw as SourceData | undefined;
        return data?.features;
      })).toEqual([]);
    };
    const measureTarget = async () => {
      await page.evaluate(({ suffix, expectedGps }) => {
        (window as unknown as { __gisBudget: Promise<{ elapsedMs: number; completed: boolean }> }).__gisBudget = new Promise((resolve) => {
          const onClick = (event: MouseEvent) => {
            const button = (event.target as Element | null)?.closest('button');
            if (!button?.textContent?.includes(suffix)) return;
            document.removeEventListener('click', onClick, true);
            const started = performance.now();
            const tick = () => {
              const map = (window as unknown as { __maplibreInstance?: MapLike }).__maplibreInstance;
              const raw = map?.getSource('driver-observations-source')?._data ?? map?.getSource('driver-observations-source')?.serialize?.().data;
              const data = (raw as { data?: SourceData; geojson?: SourceData } | undefined)?.data ?? (raw as { geojson?: SourceData } | undefined)?.geojson ?? raw as SourceData | undefined;
              const observedMatches = JSON.stringify(data?.features?.[0]?.geometry.coordinates) === JSON.stringify(expectedGps);
              const bounds = document.querySelector('[data-testid="maplibre-container"]')?.getBoundingClientRect();
              const visible = Boolean(bounds && bounds.width > 0 && bounds.height > 0);
              const complete = Boolean(visible && map && observedMatches && ['pickup-route-line', 'destination-route-line', 'driver-observations'].every((layer) => map.getLayer(layer) && map.queryRenderedFeatures(undefined, { layers: [layer] }).length > 0));
              const elapsedMs = performance.now() - started;
              if (complete || elapsedMs > 10000) resolve({ elapsedMs, completed: complete }); else requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
          };
          document.addEventListener('click', onClick, true);
        });
      }, { suffix: `#${caseId.slice(-8)}`, expectedGps });
      const response = page.waitForResponse((item) => new URL(item.url()).pathname === `/api/v1/cases/${caseId}`);
      await target.click();
      await page.getByRole('tab', { name: 'Maps' }).click();
      expect((await response).ok()).toBe(true);
      return page.evaluate(() => (window as unknown as { __gisBudget: Promise<{ elapsedMs: number; completed: boolean }> }).__gisBudget);
    };
    await selectOther();
    expect((await measureTarget()).completed).toBe(true);
    for (let index = 0; index < 20; index += 1) {
      await selectOther();
      samples.push(await measureTarget());
    }
    const sorted = samples.map(({ elapsedMs }) => elapsedMs).sort((a, b) => a - b);
    const p95Ms = sorted[Math.ceil(0.95 * sorted.length) - 1];
    const evidence = { p95Ms, samples, budgetMs, definition: 'optimized test build; 20 fresh case selections after untimed warm-up; click to both routes and observed GPS dot; offline basemap',
      environment: { os: os.type(), release: os.release(), architecture: os.arch(), cpus: os.cpus().length, browser: testInfo.project.name } };
    console.log(`AC-MVP-02 selection p95: ${p95Ms.toFixed(0)}ms; ${evidence.definition}`);
    await testInfo.attach('gis-selection-render-budget', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' });
    expect(samples.every(({ completed }) => completed)).toBe(true);
    expect(p95Ms).toBeLessThanOrEqual(evidence.budgetMs);
  });
});
