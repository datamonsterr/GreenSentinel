import { test, expect } from './support/playwright';

/**
 * Issue #483: Confirmation-gated accept/reject flow in GSupport case chat.
 * Covers: reject tap -> agent asks reason -> user types reason ->
 * confirmation card visible -> Yes -> receipt visible & action bar hidden.
 */
test.describe('Driver GSupport Accept/Reject Confirmation Flow (#483)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/driver/cases/*/session', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'sess-483', messages: [] }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/dispute', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          case_id: 'case-483-e2e-1',
          driver_id: 'drv-999',
          driver_name: 'Nguyen Van An',
          violation_code: 'ERR-05',
          violation_title: 'Route deviation check',
          dispute_status: 'in_dispute',
          allowed_claim_types: ['traffic_gridlock'],
        }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/statement-draft', async (route) => {
      if (route.request().method() === 'PUT') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'saved' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ draft: null }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/confirmations', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ confirmation_token: 'tok-single-use-483' }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/statement', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'submitted',
          dispute_status: 'analyst_escalated',
        }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/acknowledge', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'acknowledged',
          dispute_status: 'pending_analyst_review',
        }),
      });
    });

    await page.route('**/api/v1/driver/cases/*/chat/stream', async (route) => {
      let raw = route.request().url();
      try {
        const postData = route.request().postDataJSON();
        if (postData && postData.message) raw += ` ${postData.message}`;
      } catch {
        // GET streams carry the message in the query string (already in url)
      }
      let msg = raw;
      try {
        msg = decodeURIComponent(raw);
      } catch {
        // keep raw on malformed encoding
      }

      if (/autoSendPrompt|Kiểm tra chi tiết|Check details/i.test(msg)) {
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body:
            'event: token\ndata: {"token":"Đã kiểm tra vụ việc."}\n\n' +
            'event: blocks\ndata: {"blocks":[]}\n\n' +
            'event: done\ndata: {"status":"completed","reply":"Đã kiểm tra vụ việc.","dispute_status":"in_dispute","blocks":[]}\n\n',
        });
      }

      if (/từ chối|reject/i.test(msg)) {
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body:
            'event: token\ndata: {"token":"Vui lòng cho biết lý do bạn đi lệch tuyến?"}\n\n' +
            'event: blocks\ndata: {"blocks":[]}\n\n' +
            'event: done\ndata: {"status":"completed","reply":"Vui lòng cho biết lý do bạn đi lệch tuyến?","dispute_status":"in_dispute","blocks":[]}\n\n',
        });
      }

      const confirmationBlock = {
        type: 'confirmation',
        action: 'submit_statement',
        checklist: [
          { key: 'incident_type', ok: true, label: 'Thời tiết / Đường ngập' },
          { key: 'description', ok: true, label: 'Né điểm ngập Nguyễn Hữu Cảnh' },
          { key: 'evidence', ok: true, label: 'Khớp dữ liệu thời tiết & GPS' },
        ],
        summary: 'Đường ngập sâu Nguyễn Hữu Cảnh, CSGT phân luồng qua Điện Biên Phủ',
      };

      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: token\ndata: {"token":"GSupport đã ghi nhận thông tin giải trình của bạn:"}\n\n' +
          `event: blocks\ndata: ${JSON.stringify({ blocks: [confirmationBlock] })}\n\n` +
          `event: done\ndata: ${JSON.stringify({
            status: 'completed',
            reply: 'GSupport đã ghi nhận thông tin giải trình của bạn:',
            dispute_status: 'pending_confirmation',
            blocks: [confirmationBlock],
          })}\n\n`,
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

  test('reject tap -> agent asks reason -> user types reason -> confirmation card -> Yes -> receipt visible', async ({
    page,
  }) => {
    await page.goto('/driver/chat/case-483-e2e-1');

    const actionBar = page.getByTestId('driver-action-bar');
    await expect(actionBar).toBeVisible();
    await expect(page.getByText('Đã kiểm tra vụ việc.')).toBeVisible();

    // 1. Tap Reject & explain
    await page.getByTestId('driver-action-reject').click();

    // 2. Agent asks for the reason
    await expect(page.getByText('Vui lòng cho biết lý do bạn đi lệch tuyến?')).toBeVisible();

    // 3. User types reason in composer and sends
    const composer = page.getByTestId('chat-composer');
    await composer.locator('textarea').fill('Đường Nguyễn Hữu Cảnh bị ngập sâu nên phải đi vòng');
    await composer.locator('button[type="submit"]').click();

    // 4. Confirmation card renders with checklist and summary
    const confirmCard = page.getByTestId('driver-confirmation-card');
    await expect(confirmCard).toBeVisible();
    await expect(
      confirmCard.getByText('Đường ngập sâu Nguyễn Hữu Cảnh, CSGT phân luồng qua Điện Biên Phủ')
    ).toBeVisible();

    // 5. Tap Yes -> issues confirmation token, submits statement, shows receipt, hides action bar
    await page.getByTestId('driver-confirm-yes').click();

    await expect(page.getByTestId('driver-submit-receipt')).toBeVisible();
    await expect(actionBar).toBeHidden();
  });
});
