import { test, expect, type Page } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

async function claimCase(page: Page) {
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeEnabled();
}

test.describe('Analyst Copilot Panel (Issue #443 DoD)', () => {
  const CASE_ID = '11111111-1111-4111-8111-111111111111';

  test.beforeEach(async ({ page, context }) => {
    try {
      await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    } catch {}
    await installApiFixtures(page);
    await page.goto('/workplace');

    const caseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(caseButton).toBeVisible();
    await caseButton.click();
    await claimCase(page);
  });

  test('1. Header: segmented switcher without Agents title or case badge, keyboard navigable', async ({ page }) => {
    // Verify "Agents" title and case code badge are removed from the header
    const copilotHeader = page.locator('#tab-ai-copilot').locator('..');
    await expect(page.getByText(/^Agents$/i)).toHaveCount(0);
    await expect(copilotHeader.getByText(new RegExp(`#${CASE_ID.slice(-8)}`))).toHaveCount(0);

    // Verify compact 2-option switcher: Analyst Copilot | Driver
    const copilotTab = page.locator('#tab-ai-copilot');
    const driverTab = page.locator('#tab-driver-relay');

    await expect(copilotTab).toBeVisible();
    await expect(driverTab).toBeVisible();
    await expect(copilotTab).toHaveAttribute('id', 'tab-ai-copilot');
    await expect(driverTab).toHaveAttribute('id', 'tab-driver-relay');
    await expect(copilotTab).toHaveAttribute('aria-selected', 'true');
    await expect(driverTab).toHaveAttribute('aria-selected', 'false');

    // Test keyboard navigation
    await copilotTab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(driverTab).toBeFocused();
    await expect(driverTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#panel-driver-relay')).toBeVisible();

    await page.keyboard.press('ArrowLeft');
    await expect(copilotTab).toBeFocused();
    await expect(copilotTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#panel-ai-copilot')).toBeVisible();
  });

  test('1a. Analyst panel fills the sidebar and user bubbles render dark with white text', async ({ page }) => {
    const panel = page.getByTestId('analyst-copilot-panel');
    const panelBox = await panel.boundingBox();
    expect(panelBox).not.toBeNull();
    const workspace = page.locator('div.flex-1.flex.flex-col.lg\\:flex-row').first();
    const workspaceBox = await workspace.boundingBox();
    const queueBox = await page.getByRole('region', { name: 'Triage queue' }).boundingBox();
    const caseBox = await page.getByRole('region', { name: 'Case workspace' }).boundingBox();
    expect(workspaceBox).not.toBeNull();
    expect(queueBox).not.toBeNull();
    expect(caseBox).not.toBeNull();
    expect(panelBox!.x + panelBox!.width).toBeCloseTo(workspaceBox!.x + workspaceBox!.width, 0);
    expect(panelBox!.width).toBeCloseTo(workspaceBox!.width - queueBox!.width - caseBox!.width, 0);

    const prompt = panel.getByPlaceholder('Ask Agents about this case…');
    const promptBox = await prompt.locator('xpath=ancestor::form[1]').boundingBox();
    expect(promptBox).not.toBeNull();
    expect(promptBox!.width).toBeGreaterThan(panelBox!.width - 40);

    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: text.delta\ndata: {"delta":"Đã nhận yêu cầu."}\n\nevent: run.completed\ndata: {"status":"completed"}\n\n',
      });
    });
    await prompt.fill('Kiểm tra màu tin nhắn');
    await prompt.press('Enter');

    const userBubble = panel.getByText('Kiểm tra màu tin nhắn', { exact: true }).locator('..');
    await expect(userBubble).toBeVisible();
    await expect(userBubble).toHaveCSS('background-color', 'rgb(86, 94, 116)');
    await expect(userBubble).toHaveCSS('color', 'rgb(255, 255, 255)');

    await page.setViewportSize({ width: 375, height: 800 });
    await page.reload();
    const mobileCaseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(mobileCaseButton).toBeVisible();
    await mobileCaseButton.click({ force: true });
    const mobilePanel = page.getByTestId('analyst-copilot-panel');
    const mobilePanelBox = await mobilePanel.boundingBox();
    expect(mobilePanelBox).not.toBeNull();
    expect(mobilePanelBox!.x).toBeGreaterThanOrEqual(0);
    expect(mobilePanelBox!.x + mobilePanelBox!.width).toBeLessThanOrEqual(375);
  });

  test('2. Context Ring: displays token percentage, breakdown popover, and clear context flow', async ({ page }) => {
    // Ring button displays 18% (1800 total / 10000 window from api-fixtures)
    const contextTrigger = page.getByLabel('Ngữ cảnh AI Copilot');
    await expect(contextTrigger).toBeVisible();
    await expect(contextTrigger).toHaveText(/18(\.0)?%/);

    // Click to open context popover
    await contextTrigger.click();

    // Verify token breakdown rows
    await expect(page.getByText('System')).toBeVisible();
    await expect(page.getByText('Hồ sơ vụ việc')).toBeVisible();
    await expect(page.getByText('Lịch sử hội thoại')).toBeVisible();
    await expect(page.getByText('Kết quả công cụ')).toBeVisible();
    await expect(page.getByText('Câu hỏi')).toBeVisible();
    await expect(page.getByText('400', { exact: true })).toBeVisible();
    await expect(page.getByText('600', { exact: true })).toBeVisible();

    // Click destructive "Xóa ngữ cảnh" button
    const clearButton = page.getByRole('button', { name: 'Xóa ngữ cảnh' });
    await expect(clearButton).toBeVisible();
    await clearButton.click();

    // Confirm step
    await expect(page.getByText('Xác nhận xóa?')).toBeVisible();
    const confirmButton = page.getByRole('button', { name: 'Xác nhận' });
    await confirmButton.click();

    // Popover closes or confirms completion
    await expect(page.getByText('Xác nhận xóa?')).toHaveCount(0);
  });

  test('3. Rich markdown, links (case, driver, trip, policy citations), grouped tools, and suggestions', async ({ page }) => {
    // Custom SSE response with rich formatting, custom link schemes, grouped tools, citations, and suggestions
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      let body: any = {};
      try {
        body = JSON.parse(route.request().postData() || '{}');
      } catch {}
      const query = (body.query || body.prompt || '').trim();

      if (query.includes('Phân tích chi tiết lộ trình')) {
        const sseBody = [
          'event: text.delta\n',
          `data: {"delta":${JSON.stringify(`Reply to ${query}`)}}\n\n`,
          'event: run.completed\n',
          'data: {"status":"completed"}\n\n',
        ].join('');
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: sseBody,
        });
      }

      const richMarkdown = [
        'Đoạn văn bản thứ nhất phân tích hành vi của tài xế.',
        '',
        'Đoạn văn bản thứ hai chứa **thông tin in đậm quan trọng** và liên kết [Xem hồ sơ](case://22222222-2222-4222-8222-222222222222) cùng với [Hồ sơ tài xế](driver://drv-e2e) và [Xem chuyến đi](trip://trip-e2e-99?pickup=VinUni&dest=Keangnam).',
        '',
        '| Tiêu chí | Kết quả |',
        '| :--- | :--- |',
        '| Dừng đón | Vượt 180s |',
        '| Quy chế | [1](policy://c1) |',
      ].join('\n');

      const sseBody = [
        'event: status.thinking\n',
        'data: {"schema_version":"1.1","label":"Đang đối soát chứng cứ vi phạm"}\n\n',
        'event: tool.start\n',
        'data: {"tool_call_id":"call-t1","tool_name":"inspect_trip_telemetry"}\n\n',
        'event: tool.end\n',
        'data: {"tool_call_id":"call-t1","status":"completed"}\n\n',
        'event: tool.start\n',
        'data: {"tool_call_id":"call-t2","tool_name":"search_policy_documents"}\n\n',
        'event: tool.end\n',
        'data: {"tool_call_id":"call-t2","status":"completed"}\n\n',
        'event: citation\n',
        'data: {"id":"c1","source":"Quy chế tài xế 2026","section":"Điều 14.2","content":"Nghiêm cấm dừng đỗ đón khách sai vị trí hoặc kéo dài thời gian quá 180 giây.","score":0.96}\n\n',
        'event: text.delta\n',
        `data: {"delta":${JSON.stringify(richMarkdown)}}\n\n`,
        'event: suggestions\n',
        'data: {"items":[{"label":"Phân tích lộ trình","prompt":"Phân tích chi tiết lộ trình viễn thông"},{"label":"Tra cứu tiền lệ","prompt":"Tra cứu tiền lệ xử lý tương tự"}]}\n\n',
        'event: usage\n',
        'data: {"prompt_tokens":2100,"completion_tokens":450,"total_tokens":2550,"context_window":10000,"breakdown":{"system":400,"dossier":800,"history":500,"tool_results":500,"query":350}}\n\n',
        'event: run.completed\n',
        'data: {"status":"completed"}\n\n',
      ].join('');

      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sseBody,
      });
    });

    const input = page.getByPlaceholder('Ask Agents about this case…');
    await input.fill('Phân tích đối soát vi phạm');
    await input.press('Enter');

    // 3a. Paragraphs and bold text
    await expect(page.getByText('Đoạn văn bản thứ nhất phân tích hành vi của tài xế.')).toBeVisible();
    await expect(page.getByText('thông tin in đậm quan trọng')).toBeVisible();

    // 3b. Table rendering
    await expect(page.getByRole('table')).toBeVisible();
    await expect(page.getByText('Tiêu chí')).toBeVisible();
    await expect(page.getByText('Vượt 180s')).toBeVisible();

    // 3c. Grouped tools row (2 completed tools collapsed into 1 row)
    const groupedToolsBtn = page.getByText('Đã dùng 2 công cụ');
    await expect(groupedToolsBtn).toBeVisible();
    await groupedToolsBtn.click();
    await expect(page.getByText('Đã đối soát dữ liệu hành trình')).toBeVisible();
    await expect(page.getByText('Đã tìm kiếm tài liệu quy chế')).toBeVisible();

    // 3d. Custom link case:// click copies ID, tooltip shows full UUID
    const caseLink = page.getByRole('button', { name: 'Xem hồ sơ' });
    await expect(caseLink).toBeVisible();
    await expect(caseLink).not.toHaveText('22222222-2222-4222-8222-222222222222');
    await expect(caseLink).toHaveAttribute('title', '22222222-2222-4222-8222-222222222222');
    await caseLink.click();
    await expect(page.getByText('Đã sao chép mã vụ việc')).toBeVisible();

    // 3e. Custom link driver:// opens driver scorecard Dialog
    const driverLink = page.getByRole('button', { name: 'Hồ sơ tài xế' });
    await expect(driverLink).toBeVisible();
    await driverLink.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(/Hồ sơ tài xế/i)).toBeVisible();
    await expect(dialog.getByText('4.2%')).toBeVisible();
    await page.keyboard.press('Escape');

    // 3f. Custom link trip:// chip calls map center
    const tripChip = page.getByRole('button', { name: /VinUni → Keangnam/i });
    await expect(tripChip).toBeVisible();
    await tripChip.click();

    // 3g. Citation marker policy://c1 hover/click popover and collapsed Sources list
    const citationMarker = page.locator('sup').filter({ hasText: /1/ });
    await expect(citationMarker).toBeVisible();
    await citationMarker.hover();
    await expect(page.getByText('Quy chế tài xế 2026')).toBeVisible();
    await expect(page.getByText('Điều 14.2')).toBeVisible();
    await expect(page.getByText(/Nghiêm cấm dừng đỗ đón khách sai vị trí/i)).toBeVisible();

    // Sources list collapsed at message end
    await expect(page.getByText(/Nguồn trích dẫn/i)).toBeVisible();

    // 3h. Suggestions chips rendered and click sends prompt
    const suggestionChip = page.getByRole('button', { name: 'Phân tích lộ trình' });
    await expect(suggestionChip).toBeVisible();
    await suggestionChip.click();
    await expect(page.getByText('Reply to Phân tích chi tiết lộ trình viễn thông')).toBeVisible({ timeout: 15000 });

    // Capture screenshot of completed Copilot panel DoD for PR evidence
    await page.screenshot({ path: 'tests/e2e/browser/copilot-panel.png', fullPage: false });
  });

  test('4. Image attachment: upload preview, sent as base64 in body, rendered in user bubble', async ({ page }) => {
    let capturedBody: any = null;
    await page.route('**/api/v1/policy/chat/stream', async (route) => {
      try {
        capturedBody = JSON.parse(route.request().postData() || '{}');
      } catch {}
      const sseBody = [
        'event: text.delta\n',
        'data: {"delta":"Đã nhận ảnh hiện trường vi phạm."}\n\n',
        'event: run.completed\n',
        'data: {"status":"completed"}\n\n',
      ].join('');
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody });
    });

    // Upload an image attachment via file input
    const fileInput = page.locator('input[type="file"][accept*="image"]');
    await fileInput.setInputFiles({
      name: 'hien-truong.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        'base64'
      ),
    });

    // Attachment thumbnail preview shown inside PromptInput
    await expect(page.getByText('hien-truong.png')).toBeVisible();

    // Type text and submit
    const input = page.getByPlaceholder('Ask Agents about this case…');
    await input.fill('Ảnh hiện trường điểm đón');
    await input.press('Enter');

    // Verify response
    await expect(page.getByText('Đã nhận ảnh hiện trường vi phạm.')).toBeVisible();

    // Verify user message bubble shows thumbnail image
    const userBubble = page.locator('.is-user');
    await expect(userBubble.locator('img')).toBeVisible();
    await expect(userBubble.getByText('hien-truong.png')).toBeVisible();

    // Verify attachment data was sent in request body
    expect(capturedBody).not.toBeNull();
    expect(capturedBody.attachments).toHaveLength(1);
    expect(capturedBody.attachments[0].name).toBe('hien-truong.png');
    expect(capturedBody.attachments[0].media_type).toBe('image/png');
    expect(capturedBody.attachments[0].data_base64).toBeTruthy();
  });
});
