import { test, expect, type Page } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

async function claimCase(page: Page) {
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeEnabled();
}

const finalActions = ['Approve conclusion', 'Dismiss', 'Request evidence'];

test.describe('Source-backed six-tab workspace', () => {
  test.beforeEach(async ({ page }) => {
    await installApiFixtures(page);
    await page.goto('/workplace');
  });

  test('opens the API case and retains customer evidence and Maps controls', async ({ page }) => {
    const queue = page.getByRole('region', { name: 'Triage queue' });
    await expect(queue).toBeVisible();
    await expect(page.getByText('#FC-8921', { exact: true })).toHaveCount(0);
    await expect(page.getByText('AI Forensic Summary', { exact: true })).toHaveCount(0);
    await queue.locator('button[aria-pressed]').first().click();
    await page.getByRole('tab', { name: 'Customer', exact: true }).click();
    const conversation = page.getByRole('region', { name: 'Driver–customer conversation' });
    await expect(conversation.getByText('Traffic is slowing the trip.', { exact: true })).toBeVisible();
    await expect(conversation.getByRole('textbox')).toHaveCount(0);
    await page.getByRole('tab', { name: 'Maps', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Center whole trip' })).toBeEnabled();
  });

  test('keeps decisions in Complete and removes case-card rejection and legacy sanctions', async ({ page }) => {
    const queue = page.getByRole('region', { name: 'Triage queue' });
    await expect(queue.getByRole('button', { name: /^(Reject|Dismiss)$/ })).toHaveCount(0);
    await expect(page.getByRole('textbox', { name: 'Decision rationale' })).toHaveCount(0);
    await claimCase(page);
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await page.getByRole('textbox', { name: 'Decision rationale' }).fill('Evidence reviewed');
    for (const label of finalActions) await expect(page.getByRole('button', { name: label, exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Suspend 24h', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Submit Decision', exact: true })).toHaveCount(0);
  });

  for (const [label, path, outcome] of [
    ['Request evidence', '/actions', 'REQUEST_EVIDENCE'],
    ['Dismiss', '/adjudicate', 'DISAGREE'],
    ['Approve conclusion', '/adjudicate', 'AGREE'],
  ] as const) {
    test('validates rationale and sends explicit ' + label + ' through the case API', async ({ page }) => {
      const requests: Record<string, unknown>[] = [];
      await page.route('**/api/v1/cases/*' + path, async route => {
        requests.push(route.request().postDataJSON());
        await route.fallback();
      });
      await claimCase(page);
      await page.getByRole('tab', { name: 'Complete', exact: true }).click();
      const rationale = page.getByRole('textbox', { name: 'Decision rationale' });
      const action = page.getByRole('button', { name: label, exact: true });
      await rationale.fill('Short');
      await expect(action).toBeDisabled();
      await expect(page.getByText('Rationale requires at least 10 characters.', { exact: true })).toBeVisible();
      expect(requests).toHaveLength(0);
      await rationale.fill('Reviewed source evidence independently.');
      await expect(action).toBeEnabled();
      await action.click();
      await expect.poll(() => requests.length).toBe(1);
      if (path === '/actions') {
        expect(requests[0]).toEqual({ action_type: outcome, analyst_id: 'analyst-e2e', notes: 'Reviewed source evidence independently.' });
      } else {
        expect(requests[0]).toMatchObject({ outcome, analyst_id: 'analyst-e2e', expected_case_version: 3, rationale: 'Reviewed source evidence independently.', preliminary_judgment_id: 'judgment-11111111-1111-4111-8111-111111111111' });
      }
    });
  }

  test('completes five streamed Copilot turns and retains their replies', async ({ page }) => {
    test.setTimeout(90_000);
    await claimCase(page);
    const input = page.getByPlaceholder('Ask Agents about this case…');
    const questions = ['Tóm tắt vi phạm', 'Bằng chứng telemetry', 'Giải trình của tài xế', 'Điều khoản áp dụng', 'Kết luận xử lý'];
    for (const question of questions) {
      await input.fill(question);
      await input.press('Enter');
      await expect(page.getByText('Reply to ' + question, { exact: true })).toBeVisible();
      await expect(input).toBeEnabled();
    }
    for (const question of questions) {
      await expect(page.getByText(question, { exact: true })).toBeVisible();
      await expect(page.getByText('Reply to ' + question, { exact: true })).toBeVisible();
    }
  });

  test('preserves the recorded motivation narrative and consistent Copilot reward', async ({ page }) => {
    await claimCase(page);
    await expect(page.getByRole('tabpanel', { name: 'Overview', exact: true }).getByText(/tài xế có thể kéo dài hành trình/i)).toHaveCount(0);
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    const motivation = page.getByRole('region', { name: 'AI results', exact: true });
    await expect(motivation.getByText(/tài xế có thể kéo dài hành trình/i)).toBeVisible();
    await expect(motivation.getByText(/25[.,\s]000\s*₫/)).toBeVisible();
    const input = page.getByPlaceholder('Ask Agents about this case…');
    await input.fill('Tóm tắt động cơ và hành vi của tài xế');
    await input.press('Enter');
    const copilotPanel = page.getByRole('tabpanel', { name: 'Analyst Copilot' });
    await expect(copilotPanel.getByText(/tài xế có thể kéo dài hành trình để hưởng thêm 25\.000 đồng/i)).toBeVisible();
    await expect(copilotPanel.getByText(/Lợi ích tăng thêm ước tính: 25\.000 ₫/i)).toBeVisible();
  });

  test('shows both traffic corroboration tools and Điều 12.2 guidance', async ({ page }) => {
    await claimCase(page);

    const input = page.getByPlaceholder('Ask Agents about this case…');
    await input.fill('Kiểm tra tình trạng kẹt xe và sự cố giao thông trên đoạn đường này');
    await input.press('Enter');

    await expect(page.getByLabel('Tool fetch_corridor_historical_traffic, done')).toBeVisible();
    await expect(page.getByLabel('Tool query_traffic_incident_feed, done')).toBeVisible();
    await expect(page.getByText(/Điều 12\.2/)).toBeVisible();
    await expect(page.getByText(/không tự động kết luận gian lận/i)).toBeVisible();
  });

  test('keeps classification out of case cards and reveals category/confidence in Complete', async ({ page }) => {
    const queue = page.getByRole('region', { name: 'Triage queue' });
    await expect(queue.getByText(/route_integrity|92%|confidence|Jev/i)).toHaveCount(0);
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await expect(page.getByLabel('AI advice: route_integrity, 92% confidence')).toBeVisible();
    await expect(page.getByTitle('Model confidence in the classification; not a calibrated probability of fraud.')).toContainText('92%');
  });
});

for (const options of [{ isLockedByOther: true }, { role: 'driver' }]) {
  test('keeps case decisions read-only for ' + (options.role || 'another analyst lease'), async ({ page }) => {
    await installApiFixtures(page, options);
    const writes: string[] = [];
    page.on('request', request => {
      if (request.method() === 'POST' && /\/(?:actions|adjudicate|preliminary-assessment)$/.test(new URL(request.url()).pathname)) writes.push(request.url());
    });
    await page.goto('/workplace');
    if (options.isLockedByOther) await expect(page.getByRole('button', { name: 'Claimed by another analyst', exact: true })).toBeDisabled();
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Decision rationale' })).toBeDisabled();
    for (const label of finalActions) {
      const action = page.getByRole('button', { name: label, exact: true });
      await expect(action).toBeDisabled();
      await action.click({ force: true });
    }
    expect(writes).toEqual([]);
  });
}

  test('gates copilot chat when case is unclaimed and enables upon claiming (Issue #380)', async ({ page }) => {
    await installApiFixtures(page, { isUnclaimed: true });
    await page.goto('/workplace');

    const caseButton = page.getByRole('region', { name: 'Triage queue' }).locator('button[aria-pressed]').first();
    await expect(caseButton).toBeVisible();
    await caseButton.click();

    const input = page.getByPlaceholder('Claim case to chat with AI Copilot…');
    await expect(input).toBeVisible();
    await expect(input).toBeDisabled();

    const claimBtn = page.getByRole('button', { name: 'Claim', exact: true });
    await expect(claimBtn).toBeVisible();
    await claimBtn.click();

    const activeInput = page.getByPlaceholder('Ask Agents about this case…');
    await expect(activeInput).toBeVisible();
    await expect(activeInput).toBeEnabled();
  });

test('shows missing map evidence explicitly without fabricated values', async ({ page }) => {
  await installApiFixtures(page, { missingTelemetry: true });
  await page.goto('/workplace');
  await page.getByRole('tab', { name: 'Maps', exact: true }).click();
  const maps = page.getByRole('tabpanel', { name: 'Maps', exact: true });
  await maps.getByRole('button', { name: 'Stall and Drift Telemetry', exact: true }).click();
  for (const label of ['Stall duration', 'DAVI', 'Drift distance', 'Telemetry samples']) {
    // Missing values render the designed empty state on the metric card, never a placeholder number.
    const card = maps.getByRole('group', { name: `${label}: No data yet`, exact: true });
    await expect(card.getByText('No data yet', { exact: true })).toBeVisible();
  }
  // Map status chips and the kinematic footer also use the designed empty state.
  await expect(maps.getByText(/\b(Unavailable|undefined|NaN)\b/)).toHaveCount(0);
  await expect(maps.getByTestId('ambient-traffic-status')).toContainText('No data yet');
  await expect(maps.getByText('420s', { exact: true })).toHaveCount(0);
  await expect(maps.getByText('0.82', { exact: true })).toHaveCount(0);
});

test('retains the incomplete-evidence guardrail warning', async ({ page }) => {
  await installApiFixtures(page, { isBlockingGuardrail: true });
  await page.goto('/workplace');
  await expect(page.getByText('Evidence incomplete. Review before approving.', { exact: true })).toBeVisible();
});

for (const isBlockingGuardrail of [false, true]) {
  test('keeps tabs compact and contiguous with case content, guardrail=' + isBlockingGuardrail, async ({ page }) => {
    await installApiFixtures(page, { isBlockingGuardrail });
    await page.goto('/workplace');
    await expect(page.getByRole('group', { name: 'Case header' })).toHaveCount(0);
    const tabs = page.getByRole('tablist', { name: 'Case views' });
    for (const label of ['Overview', 'Maps', 'Customer', 'Driver', 'Complete']) {
      const tab = tabs.getByRole('tab', { name: label, exact: true });
      await tab.click();
      const panel = page.getByRole('tabpanel', { name: label, exact: true });
      await expect(panel).toBeVisible();
      await expect(page.getByRole('region', { name: 'Case workspace', exact: true }).getByRole('tabpanel')).toHaveCount(1);
      const dimensions = await tab.evaluate(button => {
        const strip = button.closest('[role="tablist"]')!;
        const content = document.getElementById(button.getAttribute('aria-controls')!)!;
        const style = getComputedStyle(button);
        const stripBottom = strip.getBoundingClientRect().bottom;
        const panelTop = content.getBoundingClientRect().top;
        const notices = Array.from(strip.parentElement!.children).filter(element =>
          // WorkflowStepper (8343b4b) renders as a sibling block between the tab strip and the Overview panel, like the status notices.
          (element.getAttribute('role') === 'status' || element.getAttribute('data-testid') === 'workflow-stepper') && element.getBoundingClientRect().height > 0 &&
          element.getBoundingClientRect().top >= stripBottom && element.getBoundingClientRect().bottom <= panelTop);
        const noticeBottom = notices.length ? Math.max(...notices.map(element => element.getBoundingClientRect().bottom)) : stripBottom;
        return { gap: panelTop - noticeBottom, buttonHeight: button.getBoundingClientRect().height, stripHeight: strip.getBoundingClientRect().height, fontSize: style.fontSize, iconSize: getComputedStyle(button.querySelector('[aria-hidden="true"]')!).fontSize };
      });
      expect(dimensions.gap).toBeGreaterThanOrEqual(0);
      expect(dimensions.gap, label + ' layout: ' + JSON.stringify(dimensions)).toBeLessThanOrEqual(24);
      expect(dimensions.buttonHeight).toBeGreaterThanOrEqual(28);
      expect(dimensions.buttonHeight).toBeLessThanOrEqual(36);
      expect(dimensions.stripHeight).toBeLessThanOrEqual(40);
      expect(dimensions.fontSize).toBe('11px');
      expect(dimensions.iconSize).toBe('14px');
    }
  });
}

test('preserves full metadata, keyboard navigation and readable zoomed layouts', async ({ page }) => {
  const codes = ['stationary_duration_over_180s', 'passenger_forced_cancellation', 'exceptionally_long_assessment_signal_that_must_remain_available_in_full', 'fourth_signal'];
  const driverName = 'Nguyen Hung Long Driver Name With Additional Identity Details';
  await installApiFixtures(page, { driverName, assessment: { category: 'ERR-ASSESSMENT', confidence: 0.87, reason_codes: codes } });
  await page.goto('/workplace');
  await page.getByRole('tablist', { name: 'Case views' }).getByRole('tab', { name: 'Driver', exact: true }).click();
  const driverPanel = page.getByRole('tabpanel', { name: 'Driver', exact: true });
  await expect(driverPanel.getByTitle('Name', { exact: true })).toBeVisible();
  await expect(driverPanel.getByText(driverName, { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  const panel = page.getByRole('tabpanel', { name: 'Complete', exact: true });
  const signals = panel.locator(`[title^="Reason codes: "]`);
  for (const code of codes) await expect(signals).toContainText(code);
  await expect(page.getByLabel('AI advice: ERR-ASSESSMENT, 87% confidence')).toBeVisible();
  const tabs = page.getByRole('tablist', { name: 'Case views' });
  await tabs.getByRole('tab', { name: 'Overview', exact: true }).focus();
  for (const [key, label] of [['ArrowRight', 'Maps'], ['ArrowRight', 'Customer'], ['ArrowRight', 'Driver'], ['ArrowRight', 'Complete'], ['ArrowRight', 'Overview'], ['ArrowLeft', 'Complete'], ['Home', 'Overview'], ['End', 'Complete']]) {
    await page.keyboard.press(key);
    const selected = tabs.getByRole('tab', { name: label, exact: true });
    await expect(selected).toBeFocused();
    await expect(selected).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name: label, exact: true })).toBeVisible();
    expect(await selected.evaluate(element => element.matches(':focus-visible'))).toBe(true);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const zoom of ['1', '2']) {
    await page.evaluate(value => { document.body.style.zoom = value; }, zoom);
    await expect(panel).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    for (const code of codes) await expect(signals).toContainText(code);
    await expect(tabs.getByRole('tab')).toHaveCount(5);
  }
});
