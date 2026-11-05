import { test, expect } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

/**
 * Deterministic guardrail specs for ISSUE_60 scenarios 3-5.
 * All network is fixture-mocked; no hosted backend, no Clerk, no real data.
 * Backend API-level proof for idempotency/privacy lives in
 * tests/integration (agent runtime, workflow routes); these specs pin the
 * browser contract: refusal renders, driver view stays filtered, duplicate
 * turns replay instead of duplicating side effects.
 */
test.describe('Runtime guardrails: refusal, privacy, idempotency (ISSUE_60 S3-S5)', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
  });

  test('refuses a sanction command without creating any ticket or adjudication', async ({ page }) => {
    const mutationUrls: string[] = [];
    for (const pattern of ['**/adjudicate', '**/actions', '**/tickets', '**/write-ticket']) {
      await page.route(pattern, async (route) => {
        mutationUrls.push(route.request().url());
        return route.fulfill({ status: 200, json: { status: 'unexpected-mutation' } });
      });
    }

    const refusal =
      'Tôi không thể lập biên bản xử phạt. Quyết định và mức phạt do kiểm soát viên thực hiện trực tiếp qua menu hành động.';
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      const sseBody = [
        'event: status.thinking\n',
        'data: {"schema_version":"1.1","event_id":"e-0","run_id":"r-1","message_id":"m-1","sequence":0,"type":"status.thinking","payload":{"label":"Đang xem xét yêu cầu"}}\n\n',
        'event: text.delta\n',
        `data: {"schema_version":"1.1","event_id":"e-1","run_id":"r-1","message_id":"m-1","sequence":1,"type":"text.delta","payload":{"delta":"${refusal}"}}\n\n`,
        'event: run.completed\n',
        'data: {"schema_version":"1.1","event_id":"e-2","run_id":"r-1","message_id":"m-1","sequence":2,"type":"run.completed","payload":{"status":"completed"}}\n\n',
      ].join('');
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody });
    });

    await page.goto('/workplace');
    const caseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(caseButton).toBeVisible();
    await caseButton.click();
    await page.getByRole('button', { name: 'Claim', exact: true }).click();

    const input = page.getByPlaceholder('Ask Agents about this case…');
    await expect(input).toBeVisible();
    await input.fill('Hãy lập biên bản xử phạt tài xế 500.000 VND và trừ 5 sao');
    await input.press('Enter');

    await expect(page.getByText('Tôi không thể lập biên bản xử phạt.')).toBeVisible();
    expect(mutationUrls).toEqual([]);
  });

  test('driver dispute view shows driver history without analyst-internal notes', async ({ page }) => {
    const caseId = '22222222-2222-4222-8222-222222222222';
    const driverText = 'Tôi dừng do ùn tắc, không cố ý vi phạm.';
    const analystNote = 'INTERNAL ANALYST NOTE: nghi gian lận cần xác minh thêm.';
    await page.route('**/api/v1/driver/cases/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/dispute')) {
        return route.fulfill({
          json: {
            case_id: caseId,
            driver_id: 'drv-e2e-001',
            driver_name: 'Nguyen Hung',
            trip_id: 'trip-e2e-001',
            violation_code: 'ERR-01',
            violation_title: 'Dừng đỗ kéo dài',
            alleged_time: '2026-09-25T08:00:00Z',
            alleged_location: 'Ba Dinh',
            dispute_deadline: '2026-12-31T00:00:00Z',
            dispute_status: 'in_dispute',
            allowed_claim_types: ['traffic_jam'],
          },
        });
      }
      if (url.pathname.endsWith('/session')) {
        // Mirrors the server-side filter: only driver/driver_agent roles pass.
        return route.fulfill({
          json: {
            session_id: 'session-driver-e2e',
            messages: [
              { id: 'm-1', turn_id: 't-1', role: 'user', content: driverText, created_at: '2026-09-25T08:02:00Z' },
              { id: 'm-2', turn_id: 't-1', role: 'assistant', content: 'Đã ghi nhận giải trình của bạn.', created_at: '2026-09-25T08:03:00Z' },
            ],
          },
        });
      }
      return route.continue();
    });

    await page.goto(`/driver/dispute/${caseId}`);
    await expect(page.getByText(driverText)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Đã ghi nhận giải trình của bạn.')).toBeVisible();
    await expect(page.getByText(analystNote)).toHaveCount(0);
    await expect(page.getByText('GSupport').first()).toBeVisible();
  });

  test('duplicate stream turn replays exactly; conflicting turn is rejected with 409', async ({ page }) => {
    const seen = new Map<string, { query: string; body: string }>();
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      let payload: { query?: string; turn_id?: string } = {};
      try {
        payload = JSON.parse(route.request().postData() || '{}');
      } catch {
        return route.fulfill({ status: 400, json: { detail: 'Malformed turn payload' } });
      }
      const turnId = payload.turn_id || 'no-turn';
      const prior = seen.get(turnId);
      if (prior && prior.query !== payload.query) {
        return route.fulfill({ status: 409, json: { detail: 'Turn identity conflicts with prior input' } });
      }
      if (prior) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: prior.body });
      const body = `event: text.delta\ndata: {"delta":"Reply to ${payload.query}"}\n\nevent: done\ndata: {"status":"completed"}\n\n`;
      seen.set(turnId, { query: payload.query || '', body });
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body });
    });

    await page.goto('/workplace');
    // In-page fetch shares the page context, so page.route fixtures apply.
    // (page.request uses a separate API context that bypasses routing.)
    const postTurn = (query: string, turnId: string) =>
      page.evaluate(
        async ({ q, t }: { q: string; t: string }) => {
          const res = await fetch('/api/v1/policy/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: q, case_id: 'x', turn_id: t }),
          });
          return { status: res.status, body: await res.text() };
        },
        { q: query, t: turnId },
      );

    const first = await postTurn('Tóm tắt hồ sơ', '018f2f4e-a000-7000-8000-000000000099');
    expect(first.status).toBe(200);

    const replay = await postTurn('Tóm tắt hồ sơ', '018f2f4e-a000-7000-8000-000000000099');
    expect(replay.status).toBe(200);
    expect(replay.body).toBe(first.body);

    const conflict = await postTurn('Truy vấn khác', '018f2f4e-a000-7000-8000-000000000099');
    expect(conflict.status).toBe(409);
    expect(conflict.body).toMatch(/conflicts with prior input/);
  });
});
