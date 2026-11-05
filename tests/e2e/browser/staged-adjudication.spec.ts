import { test, expect } from './support/playwright';
import {
  installStagedAdjudicationFixture, STAGED_ANALYST_ID, STAGED_JUDGMENT_ID,
  STAGED_SUMMARY, STAGED_PRECEDENT, STAGED_CONVERSATION,
} from './staged-adjudication-fixture';

const commitName = 'Save judgment & view AI';
const counterargumentName = /phản biện|counter.?argument/i;

test('236: claimed case masks every AI conclusion surface before independent judgment', async ({ page }) => {
  await installStagedAdjudicationFixture(page);
  await page.goto('/workplace');
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.reload();
  // Check the whole workspace: queue tags can anchor the same case as the header.
  await expect(page.getByText(/intentional_dic/)).toHaveCount(0);
  await expect(page.getByText(/92%/)).toHaveCount(0);
  await expect(page.getByLabel(/AI advice:/)).toHaveCount(0);
  await expect(page.getByLabel(/Xác suất nghi vấn vi phạm/)).toHaveCount(0);
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  await expect(page.getByText(/Rec: APPROVE/)).toHaveCount(0);
  await expect(page.getByText(STAGED_PRECEDENT, { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Áp dụng quy trình án lệ' })).toHaveCount(0);
});

test('236: raw summary map telemetry and conversation remain accessible before commitment', async ({ page }) => {
  const state = await installStagedAdjudicationFixture(page);
  await page.goto('/workplace');
  await expect(page.getByRole('button', { name: 'Claim', exact: true })).toBeVisible();
  await expect(page.getByLabel(/AI advice:/)).toHaveCount(0);
  const brief = page.getByRole('region', { name: 'Forensic Brief', exact: true });
  await expect(brief).toBeVisible();
  await expect(brief.getByText(STAGED_SUMMARY, { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Maps', exact: true }).click();
  await expect(page.locator('#panel-maps')).toBeVisible();
  await expect(page.getByRole('img', { name: 'Pickup source 236', exact: true })).toBeVisible();
  const sensors = page.getByRole('region', { name: 'Platform and Sensor Reliability' });
  await sensors.getByRole('button').click();
  await expect(sensors.getByRole('button')).toHaveAttribute('aria-expanded', 'true');
  const telemetry = page.getByRole('region', { name: 'Stall and Drift Telemetry' });
  await telemetry.getByRole('button').click();
  await expect(telemetry.getByRole('button')).toHaveAttribute('aria-expanded', 'true');
  await page.getByRole('tab', { name: 'Customer', exact: true }).click();
  const conversation = page.getByRole('region', { name: 'Driver–customer conversation' });
  await expect(conversation.getByText(STAGED_CONVERSATION, { exact: true })).toBeVisible();
  expect(state.preliminaryRequests).toHaveLength(0);
});

test('236: reload of claimed but uncommitted case keeps AI hidden', async ({ page }) => {
  await installStagedAdjudicationFixture(page);
  await page.goto('/workplace');
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('region', { name: 'Forensic Brief', exact: true })).toBeVisible();
  await expect(page.getByLabel(/AI advice:/)).toHaveCount(0);
  await expect(page.getByLabel(/Xác suất nghi vấn vi phạm/)).toHaveCount(0);
  await expect(page.getByText(/92%/)).toHaveCount(0);
});

test('236: keyboard commits one of three labeled choices and reveals within five seconds', async ({ page }) => {
  const state = await installStagedAdjudicationFixture(page);
  await page.goto('/workplace');
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  await page.getByRole('button', { name: 'View AI results', exact: true }).click();
  const choices = page.getByRole('radiogroup', { name: /phán đoán|judgment/i });
  await expect(choices.getByRole('radio')).toHaveCount(3);
  await expect(choices.getByRole('radio', { name: 'Suspected fraud', exact: true })).toBeVisible();
  await expect(choices.getByRole('radio', { name: 'Insufficient evidence', exact: true })).toBeVisible();
  const choice = choices.getByRole('radio', { name: 'No fraud / force majeure' });
  const start = Date.now();
  await choice.focus();
  await expect(choice).toBeFocused();
  await choice.press('Space');
  await expect(choice).toBeChecked();
  const save = page.getByRole('button', { name: commitName });
  await expect(save).toHaveAccessibleName(commitName);
  await save.focus();
  await save.press('Enter');
  await expect(page.getByRole('region', { name: counterargumentName })).toBeVisible({ timeout: 5000 });
  expect(Date.now() - start).toBeLessThanOrEqual(5000);
  await expect(page.getByLabel(/AI advice:.*92%/)).toBeVisible();
  expect(state.preliminaryRequests).toHaveLength(1);
  expect(state.preliminaryRequests[0]).toMatchObject({ analyst_id: STAGED_ANALYST_ID });
  expect(state.preliminaryRequests[0].note ?? null).toBeNull();
});

test('236: committed mismatch preserves HITL signature rationale reference and visible history', async ({ page }) => {
  const state = await installStagedAdjudicationFixture(page, true);
  await page.goto('/workplace');
  await page.getByRole('button', { name: 'Claim', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  // Seed a committed server record independently so final-action checks run even if gate UI is absent.
  const rationale = page.getByRole('textbox', { name: 'Decision rationale' });
  await rationale.fill('123456789');
  await expect(page.getByRole('button', { name: 'Dismiss', exact: true })).toBeDisabled();
  expect(state.adjudicationRequests).toHaveLength(0);
  await rationale.fill('1234567890');
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click();
  await expect.poll(() => state.adjudicationRequests.length).toBe(1);
  expect(state.adjudicationRequests[0]).toMatchObject({
    analyst_id: STAGED_ANALYST_ID, rationale: '1234567890', outcome: 'DISAGREE',
    preliminary_judgment_id: STAGED_JUDGMENT_ID,
  });
  await page.getByRole('tab', { name: /History/i }).click();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  await expect(page.getByText(/No fraud \/ force majeure/)).toBeVisible();
  await expect(page.getByText(/lệch|mismatch/i)).toBeVisible();
  await page.reload();
  await page.getByRole('tab', { name: /History/i }).click();
  await page.getByRole('tab', { name: 'Complete', exact: true }).click();
  await expect(page.getByText(/No fraud \/ force majeure/)).toBeVisible();
  await expect(page.getByText(/lệch|mismatch/i)).toBeVisible();
});

test('236: persisted history renders independent judgment AI suggestion and textual delta after reload', async ({ page }) => {
  const state = await installStagedAdjudicationFixture(page, true);
  state.finalDecision = {
    outcome: 'DISAGREE', analyst_id: STAGED_ANALYST_ID,
    rationale: 'Traffic corroboration establishes an exonerating cause.',
    preliminary_judgment_id: STAGED_JUDGMENT_ID, preliminary_judgment: state.judgment,
    ai_suggestion: { category: 'intentional_dic', confidence: 0.92, recommended_action: 'AGREE' },
    delta: 'mismatch',
  };
  await page.goto('/workplace');
  for (let reload = 0; reload < 2; reload++) {
    if (reload) await page.reload();
    await page.getByRole('tab', { name: /History/i }).click();
    await expect(page.getByRole('tab', { name: 'Complete', exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Complete', exact: true }).click();
    await expect(page.getByText(/No fraud \/ force majeure/)).toBeVisible();
    await expect(page.getByText(/lệch|mismatch/i)).toBeVisible();
    await expect(page.getByText(/intentional_dic/).first()).toBeVisible();
  }
});
