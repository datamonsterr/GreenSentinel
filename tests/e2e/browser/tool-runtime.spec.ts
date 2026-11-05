import { test, expect } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

test.describe('Tool runtime execution and chat stream recovery (T8)', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
    await page.goto('/workplace');
  });

  test('displays thinking indicator and paired tool activity during v1.1 policy stream', async ({ page }) => {
    const CASE_ID = '11111111-1111-4111-8111-111111111111';

    // Route policy chat stream to emit canonical v1.1 events
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      const sseBody = [
        'event: status.thinking\n',
        'data: {"schema_version":"1.1","event_id":"e-0","run_id":"r-1","message_id":"m-1","sequence":0,"type":"status.thinking","payload":{"label":"Đang tra cứu dữ liệu chuyến đi"}}\n\n',
        'event: tool.start\n',
        'data: {"schema_version":"1.1","event_id":"e-1","run_id":"r-1","message_id":"m-1","sequence":1,"type":"tool.start","payload":{"tool_id":"search_policy_documents","tool_name":"search_policy_documents","tool_call_id":"c-101","label":"Tra cứu quy chế 2026"}}\n\n',
        'event: tool.end\n',
        'data: {"schema_version":"1.1","event_id":"e-2","run_id":"r-1","message_id":"m-1","sequence":2,"type":"tool.end","payload":{"tool_id":"search_policy_documents","tool_call_id":"c-101","status":"succeeded","duration_ms":150,"summary":"Điều 14.2 quy định"}}\n\n',
        'event: text.delta\n',
        'data: {"schema_version":"1.1","event_id":"e-3","run_id":"r-1","message_id":"m-1","sequence":3,"type":"text.delta","payload":{"delta":"Theo kết quả tra cứu, Điều 14.2 quy định mức xử lý cho vi phạm dừng đỗ."}}\n\n',
        'event: run.completed\n',
        'data: {"schema_version":"1.1","event_id":"e-4","run_id":"r-1","message_id":"m-1","sequence":4,"type":"run.completed","payload":{"status":"completed"}}\n\n',
      ].join('');

      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sseBody,
      });
    });

    // Select the first case from triage queue
    await page.goto('/workplace');
    const caseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(caseButton).toBeVisible();
    await caseButton.click();
    await page.getByRole('button', { name: 'Claim', exact: true }).click();

    const input = page.getByPlaceholder('Ask Agents about this case…');
    await expect(input).toBeVisible();
    await input.fill('Tra cứu điều 14.2');
    await input.press('Enter');

    // Verify response text and tool row are displayed
    await expect(
      page.getByText('Theo kết quả tra cứu, Điều 14.2 quy định mức xử lý cho vi phạm dừng đỗ.')
    ).toBeVisible();
    await expect(page.getByText('Đã dùng 1 công cụ')).toBeVisible();
    await page.getByText('Đã dùng 1 công cụ').click();
    await expect(page.getByText('Đã tìm kiếm tài liệu quy chế')).toBeVisible();
  });

  test('retains partial text and shows error when stream is interrupted abruptly before completion', async ({ page }) => {
    // Route policy chat stream to emit partial text and then abruptly close without terminal event
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      const sseBody = [
        'event: status.thinking\n',
        'data: {"schema_version":"1.1","event_id":"e-0","run_id":"r-1","message_id":"m-1","sequence":0,"type":"status.thinking","payload":{"label":"Đang phân tích"}}\n\n',
        'event: tool.start\n',
        'data: {"schema_version":"1.1","event_id":"e-1","run_id":"r-1","message_id":"m-1","sequence":1,"type":"tool.start","payload":{"tool_id":"query_cases_db","tool_call_id":"c-999","label":"Tra cứu cơ sở dữ liệu"}}\n\n',
        'event: text.delta\n',
        'data: {"schema_version":"1.1","event_id":"e-2","run_id":"r-1","message_id":"m-1","sequence":2,"type":"text.delta","payload":{"delta":"Đoạn văn bản một phần trước khi mất mạng."}}\n\n',
      ].join('');

      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sseBody,
      });
    });

    await page.goto('/workplace');
    const caseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(caseButton).toBeVisible();
    await caseButton.click();
    await page.getByRole('button', { name: 'Claim', exact: true }).click();

    const input = page.getByPlaceholder('Ask Agents about this case…');
    await expect(input).toBeVisible();
    await input.fill('Kiểm tra mạng chập chờn');
    await input.press('Enter');

    // Partial text and alert must be preserved
    await expect(page.getByText('Đoạn văn bản một phần trước khi mất mạng.')).toBeVisible();
    await expect(page.getByRole('alert')).toBeVisible();
  });
});
