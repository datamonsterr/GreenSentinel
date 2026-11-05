import { test, expect } from '@playwright/test';
import { installApiFixtures } from './api-fixtures';

for (const outcome of ['Disagree', 'Agree']) {
  test(`${outcome} removes the committed case from triage after reload`, async ({ page }) => {
    await installApiFixtures(page);
    let committed = false;
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/adjudicate')) {
        expect(route.request().postDataJSON()).toMatchObject({ outcome: outcome.toUpperCase(), expected_case_version: 3, preliminary_judgment_id: 'judgment-11111111-1111-4111-8111-111111111111' });
        committed = true;
        return route.fulfill({ json: { case_id: '11111111-1111-4111-8111-111111111111', outcome: outcome === 'Disagree' ? 'DISAGREE' : 'AGREE', status: 'adjudicated', new_version: 4 } });
      }
      if (committed && path === '/api/v1/cases') {
        return route.fulfill({ json: { items: [], total: 0, limit: 50, offset: 0 } });
      }
      return route.fallback();
    });
    await page.goto('/workplace');
    await page.getByRole('button', { name: 'Claim', exact: true }).click();
    await page.reload();
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await page.getByRole('textbox', { name: 'Decision rationale' }).fill('Reviewed source evidence and confirmed this decision.');
    await page.getByRole('button', { name: outcome === 'Agree' ? 'Approve conclusion' : 'Dismiss', exact: true }).click();
    await expect(page.getByText('No available cases', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('No available cases', { exact: true })).toBeVisible();
  });
}

// Opt-in: the caller must provide an API backed by an exclusively owned database.
// Requests are forwarded unchanged; queue membership and decisions are never mocked.
for (const outcome of ['Disagree', 'Agree']) {
test(`persisted API ${outcome} survives reload and a second browser session`, async ({ page, browser, request }, testInfo) => {
  const target = process.env.ISSUE143_BROWSER_API;
  test.skip(!target, 'Set ISSUE143_BROWSER_API to the isolated PostgreSQL-backed API');
  const forward = async (sessionPage: import('@playwright/test').Page) => {
    await sessionPage.route('**/api/v1/**', async route => {
      const source = new URL(route.request().url());
      const response = await route.fetch({ url: `${target}${source.pathname}${source.search}` });
      await route.fulfill({ response });
    });
  };
  await forward(page);
  const before = await (await request.get(`${target}/api/v1/cases`)).json();
  expect(before.items.length).toBeGreaterThan(0);
  const candidate = before.items.find((item: {status: string}) => ['ready', 'in_review', 'evidence_requested', 'escalated'].includes(item.status));
  expect(candidate).toBeDefined();
  const caseId = candidate.id;
  const code = `#${caseId.slice(-8)}`;
  await page.goto('/workplace');
  await expect(page.getByText(code, { exact: true })).toBeVisible();
  await page.getByText(code, { exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('before-decision.png'), fullPage: true });
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  const reveal = page.getByRole('button', { name: 'View AI results', exact: true });
  if (await reveal.isVisible()) {
    await reveal.click();
    await page.getByRole('radio', { name: outcome === 'Dismiss' ? 'No fraud / force majeure' : 'Suspected fraud', exact: true }).check();
    await page.getByRole('button', { name: 'Save judgment & view AI', exact: true }).click();
    await expect(page.getByRole('region', { name: 'AI results', exact: true })).toBeVisible();
  }
  await page.getByRole('textbox', { name: 'Decision rationale' }).fill(`Local persisted browser verification: evidence reviewed; ${outcome.toLowerCase()} confirmed.`);
  const committed = page.waitForResponse(response => response.url().endsWith('/adjudicate'));
  await page.getByRole('button', { name: outcome === 'Agree' ? 'Approve conclusion' : 'Dismiss', exact: true }).click();
  expect((await committed).status()).toBe(200);
  await expect(page.getByText(code, { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Triage queue')).toBeVisible();
  await expect(page.getByText(code, { exact: true })).toHaveCount(0);
  const second = await browser.newPage();
  await forward(second);
  await second.goto('/workplace');
  await expect(second.getByLabel('Triage queue')).toBeVisible();
  await expect(second.getByText(code, { exact: true })).toHaveCount(0);
  for (const availability of ['available', 'mine']) {
    const active = await (await request.get(`${target}/api/v1/cases?availability=${availability}&limit=200`)).json();
    expect(active.items.some((item: {id: string}) => item.id === caseId)).toBe(false);
  }
  const retained = await (await request.get(`${target}/api/v1/cases/${caseId}`)).json();
  expect(retained.case.status).toBe('resolved');
  await page.screenshot({ path: testInfo.outputPath('after-reload.png'), fullPage: true });
  await testInfo.attach('persisted-case', { body: JSON.stringify({ caseId, outcome, before, retained }), contentType: 'application/json' });
  await second.close();
  console.log(`Persisted browser case: ${caseId}; terminal status: resolved; active queues exclude it.`);
});
}

test('at 1440x900 document.documentElement.scrollHeight <= innerHeight + 1 and scrollY stays 0 with 30+ queue cases', async ({ page }) => {
  await installApiFixtures(page);
  const queueCases = Array.from({ length: 35 }, (_, i) => {
    const num = i + 1;
    const hex = num.toString(16).padStart(12, '0');
    const id = `22222222-2222-4222-8222-${hex}`;
    return {
      id,
      status: 'OPEN',
      priority: (i % 3 === 0 ? 'P0' : i % 3 === 1 ? 'P1' : 'P2') as 'P0' | 'P1' | 'P2',
      priority_score: 0.8,
      category: 'route_integrity',
      confidence: 0.9,
      version: 1,
      driver_name: `Driver ${num}`,
      vehicle_plate: `29A-${10000 + num}`,
      district: 'Ba Dinh',
      sla_countdown_s: 300,
    };
  });

  await page.route('**/api/v1/cases*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/cases' && route.request().method() === 'GET') {
      return route.fulfill({
        json: {
          items: queueCases,
          total: queueCases.length,
          limit: 50,
          offset: 0,
        },
      });
    }
    return route.fallback();
  });

  await page.route('**/api/v1/cases/22222222-2222-4222-8222-*', async route => {
    const url = new URL(route.request().url());
    const caseId = url.pathname.split('/').pop() || '';
    const index = queueCases.findIndex(c => c.id === caseId);
    const item = queueCases[index] || queueCases[0];
    return route.fulfill({
      json: {
        case: item,
        trip: {
          pickup_address: '12 Le Loi, Ba Dinh',
          dropoff_address: '88 Tran Duy Hung, Cau Giay',
          pickup: { coordinates: [105.82, 21.03] },
          dropoff: { coordinates: [105.8, 21.01] },
        },
        telemetry_samples: [],
        features: {},
        conversation: [],
        forensic_brief: null,
        route_geometry: null,
        candidate_routes: [],
        timeline_milestones: [],
        missingness_alerts: [],
        guardrails: { is_blocking: false, blocking_reasons: [] },
        active_lease: null,
        preliminary_judgment: null,
        adjudication: null,
      },
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/workplace');
  await expect(page.getByLabel('Triage queue')).toBeVisible();
  await expect(page.getByRole('button', { name: /Driver \d+/i })).toHaveCount(35);

  // Verify page document does not overflow window height
  const { scrollHeight, innerHeight } = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }));
  expect(scrollHeight).toBeLessThanOrEqual(innerHeight + 1);

  // Select a lower card in the queue
  const lowerCard = page.getByRole('button', { name: /Driver 30/i });
  await lowerCard.scrollIntoViewIfNeeded();
  await lowerCard.click();
  await expect(lowerCard).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page.getByRole('tabpanel', { name: 'Overview' }).getByText('12 Le Loi, Ba Dinh', { exact: true }),
  ).toBeVisible();

  // Verify window scrollY stays 0 and document does not scroll
  const scrollY = await page.evaluate(() => window.scrollY);
  expect(scrollY).toBe(0);

  const scrollHeightAfter = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(scrollHeightAfter).toBeLessThanOrEqual(innerHeight + 1);
});

test('390px header keeps the language toggle clear of the app switcher', async ({ page }) => {
  await installApiFixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/workplace');

  const appSwitcher = page.getByRole('button', { name: /GreenSentinel app catalog|Danh mục ứng dụng GreenSentinel/i });
  const languageGroup = page.getByRole('group', { name: /language|ngôn ngữ/i });
  await expect(appSwitcher).toBeVisible();
  await expect(languageGroup).toBeVisible();
  await expect(page.getByRole('button', { name: 'Switch language to English', exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Switch language to Vietnamese', exact: true }),
  ).toBeVisible();

  const appBox = await appSwitcher.boundingBox();
  const languageBox = await languageGroup.boundingBox();
  expect(appBox).not.toBeNull();
  expect(languageBox).not.toBeNull();
  expect(languageBox!.x).toBeGreaterThanOrEqual(appBox!.x + appBox!.width);

  const { documentScrollWidth, viewportWidth } = await page.evaluate(() => ({
    documentScrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(documentScrollWidth).toBeLessThanOrEqual(viewportWidth + 1);
});
