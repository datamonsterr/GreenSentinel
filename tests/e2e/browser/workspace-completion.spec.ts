import { test, expect } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

const caseId = '11111111-1111-4111-8111-111111111111';

test('keeps dismissal in Complete behind independent judgment in both locales', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await installApiFixtures(page);
  let preliminary: Record<string, unknown> | null = null;
  let dismissals = 0;
  await page.route(`**/api/v1/cases/${caseId}`, route => route.fulfill({ json: {
    case: { id: caseId, status: 'OPEN', version: 3, priority: 'P1', driver_name: 'Nguyen Hung' },
    trip: { pickup_address: '12 Le Loi, Ba Dinh', dropoff_address: '88 Tran Duy Hung, Cau Giay', driver_status: 'picking_up', match_type: 'now', fare_amount_vnd: 120000 },
    telemetry_samples: [], features: {}, timeline_milestones: [], missingness_alerts: [],
    guardrails: { is_blocking: false, blocking_reasons: [] },
    active_lease: { analyst_id: 'analyst-e2e', expires_at: '2099-01-01T00:00:00Z' },
    preliminary_judgment: preliminary,
    assessment: { category: 'route_integrity', confidence: 0.92, reason_codes: ['ERR-02'] },
    forensic_brief: { summary_text: 'Observed stop; traffic evidence remains unavailable.', evidence_sources: ['telemetry'] },
    conversation: [{ role: 'driver', text: 'Traffic is slowing the trip.', occurred_at: '2026-09-25T08:02:00Z' }],
  } }));
  await page.route(`**/api/v1/cases/${caseId}/preliminary-assessment`, async route => {
    preliminary = { ...route.request().postDataJSON(), id: 'judgment-browser', case_id: caseId };
    await route.fulfill({ json: preliminary });
  });
  await page.route(`**/api/v1/cases/${caseId}/adjudicate`, async route => {
    const body = route.request().postDataJSON();
    expect(body.outcome).toBe('DISAGREE');
    expect(body.preliminary_judgment_id).toBe('judgment-browser');
    dismissals += 1;
    await route.fulfill({ json: { ...body, case_id: caseId, status: 'adjudicated', new_version: 4 } });
  });
  await page.goto('/workplace');
  await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reject', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Dismiss', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('overview-en.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: /→/ })).toBeVisible();
  await expect(page.getByRole('tabpanel', { name: 'Overview' }).getByTestId('trip-status-row').getByText(/120[,.]000 ₫/)).toBeVisible();
  const triageSection = page.getByRole('region', { name: 'Triage queue', exact: true });
  const workspaceSection = page.getByRole('region', { name: 'Case workspace', exact: true });
  const triageBox = await triageSection.boundingBox();
  const workspaceBox = await workspaceSection.boundingBox();
  expect(triageBox).not.toBeNull();
  expect(workspaceBox).not.toBeNull();
  expect(triageBox!.y + triageBox!.height).toBeLessThanOrEqual(workspaceBox!.y + 1);
  await page.getByRole('tablist', { name: 'Case views' }).getByRole('tab', { name: 'Driver', exact: true }).click();
  await expect(page.getByRole('tablist', { name: 'Case views' }).getByRole('tab', { name: 'Driver', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.screenshot({ path: testInfo.outputPath('overview-mobile-en.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  const dismiss = page.getByRole('button', { name: 'Dismiss', exact: true });
  await expect(dismiss).toBeDisabled();
  await expect(page.getByRole('region', { name: 'AI results', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'View AI results', exact: true }).click();
  await page.getByRole('radio', { name: 'No fraud / force majeure', exact: true }).check();
  await page.getByRole('button', { name: 'Save judgment & view AI', exact: true }).click();
  await expect(page.getByLabel('AI advice: route_integrity, 92% confidence')).toBeVisible();
  await expect(page.getByText('ERR-02', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Decision rationale', exact: true }).fill('Traffic evidence supports dismissal.');
  await expect(dismiss).toBeEnabled();
  expect(dismissals).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('complete-en.png') });
  await page.getByRole('button', { name: 'Switch language to Vietnamese', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Hoàn tất', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('textbox', { name: 'Lý do thẩm định', exact: true })).toHaveValue('Traffic evidence supports dismissal.');
  await expect(page.locator('article').getByRole('button', { name: 'Bác bỏ', exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('complete-vi.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('complete-mobile-vi.png'), fullPage: true });
  await expect(page.getByText('ERR-02', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Tổng quan', exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const mobileTrip = page.getByRole('button', { name: /→/ });
  await expect(mobileTrip).toBeVisible();
  await expect(page.getByRole('tabpanel', { name: 'Tổng quan' }).getByTestId('trip-status-row').getByText(/120[,.]000 ₫/)).toBeVisible();
  await expect.poll(() => mobileTrip.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('overview-mobile-vi.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Hoàn tất', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('button', { name: 'Bác bỏ', exact: true }).click();
  await expect.poll(() => dismissals).toBe(1);
  expect(errors).toEqual([]);
});
