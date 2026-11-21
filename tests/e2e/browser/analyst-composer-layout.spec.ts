import { test, expect, type Page } from './support/playwright';
import { installApiFixtures } from './api-fixtures';

async function openAnalyst(page: Page, lockedByOther = false) {
  await installApiFixtures(page, { isLockedByOther: lockedByOther });
  await page.goto('/workplace');
  const caseButton = page.getByRole('region', { name: 'Triage queue' })
    .locator('button[aria-pressed]').first();
  await expect(caseButton).toBeVisible();
  // The mobile stacked workspace can place the queue behind its fixed panels.
  await caseButton.click({ force: true });
  if (!lockedByOther) {
    const claim = page.getByRole('button', { name: 'Claim', exact: true });
    await expect(claim).toBeVisible();
    await claim.click();
    await expect(page.getByRole('button', { name: 'Release', exact: true })).toBeEnabled();
  }
  const panel = page.getByTestId('analyst-copilot-panel');
  await expect(panel).toBeVisible();
  if (!lockedByOther) {
    await expect(panel.getByPlaceholder('Ask Agents about this case…')).toBeEnabled();
  }
  return panel;
}

for (const width of [1440, 375]) {
  for (const withImage of [false, true]) {
    test(`composer uses remaining width at ${width}px ${withImage ? 'with image preview' : 'without attachments'}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const panel = await openAnalyst(page);
      const input = panel.getByPlaceholder('Ask Agents about this case…');
      const attachment = panel.getByRole('button', { name: 'Attach image', exact: true });
      const send = panel.getByRole('button', { name: 'Send message', exact: true });
      const form = input.locator('xpath=ancestor::form[1]');

      if (withImage) {
        await panel.locator('input[type="file"]').setInputFiles({
          name: 'composer-evidence.png', mimeType: 'image/png',
          buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64'),
        });
        await expect(panel.getByText('composer-evidence.png', { exact: true })).toBeVisible();
        await expect(panel.getByRole('button', { name: 'Remove attachment', exact: true })).toBeVisible();
      }

      for (const text of ['Review this case', 'Review this case\nCompare the pickup evidence\nExplain the findings']) {
        await input.fill(text);
        await expect(input).toHaveValue(text);
        await input.scrollIntoViewIfNeeded();
        // Measure the actual textarea, not the already-full-width outer form.
        // A flex regression previously left the form wide but the textarea 30px.
        await expect.poll(async () => {
          const [a, i, s] = await Promise.all([attachment.boundingBox(), input.boundingBox(), send.boundingBox()]);
          if (!a || !i || !s) return -1;
          return i.width / (s.x - (a.x + a.width));
        }, { message: 'textarea fills the horizontal space between attachment and send' }).toBeGreaterThan(0.85);

        const [a, i, s, f] = await Promise.all([
          attachment.boundingBox(), input.boundingBox(), send.boundingBox(), form.boundingBox(),
        ]);
        expect(a).not.toBeNull(); expect(i).not.toBeNull(); expect(s).not.toBeNull(); expect(f).not.toBeNull();
        if (withImage) {
          const preview = await panel.getByRole('button', { name: 'Remove attachment', exact: true }).boundingBox();
          expect(preview).not.toBeNull();
          expect(preview!.y + preview!.height, 'attachment preview stays above controls').toBeLessThanOrEqual(
            Math.min(a!.y, i!.y, s!.y),
          );
        }
        expect(a!.x + a!.width).toBeLessThanOrEqual(i!.x);
        expect(i!.x + i!.width).toBeLessThanOrEqual(s!.x);
        const availableWidth = s!.x - (a!.x + a!.width);
        expect(availableWidth - i!.width, 'only normal padding separates controls').toBeLessThanOrEqual(32);
        const centerY = (box: { y: number; height: number }) => box.y + box.height / 2;
        expect(Math.abs(centerY(a!) - centerY(i!)), 'attachment vertically centered').toBeLessThanOrEqual(2);
        expect(Math.abs(centerY(s!) - centerY(i!)), 'send vertically centered').toBeLessThanOrEqual(2);
        expect(f!.x).toBeGreaterThanOrEqual(0);
        expect(f!.x + f!.width).toBeLessThanOrEqual(width);
        expect(s!.x + s!.width).toBeLessThanOrEqual(f!.x + f!.width);
        expect(await input.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
        await page.mouse.move(0, 0); // leave any hover state from earlier steps
        await expect(send).toHaveCSS('background-color', 'rgb(15, 179, 193)'); // bg-primary (cyan theme)
        await expect.poll(async () => send.evaluate((node) => {
          const shadow = getComputedStyle(node).boxShadow;
          const colors = shadow.match(/rgba?\([^)]*\)/g) ?? [];
          return shadow === 'none' || colors.every((color) =>
            color.endsWith(', 0)') || color.endsWith(',0)') || color.includes('/ 0')
          );
        })).toBe(true);
        await send.hover();
        await expect(send).toHaveCSS('background-color', 'rgb(11, 151, 164)'); // hover:bg-primary-container
        await expect(send.locator('svg')).toBeVisible();
      }
      await form.screenshot({ path: testInfo.outputPath('populated-composer.png') });
    });
  }
}

test('composer preserves Shift+Enter newline, Enter submission and ink user text', async ({ page }) => {
  const panel = await openAnalyst(page);
  const input = panel.getByPlaceholder('Ask Agents about this case…');
  await input.fill('Review this case');
  await input.press('Shift+Enter');
  await input.press('End');
  await input.press('X');
  await expect(input).toHaveValue('Review this case\nX');
  await expect(panel.locator('.is-user')).toHaveCount(0);
  const request = page.waitForRequest(req => req.url().endsWith('/policy/chat/stream') && req.method() === 'POST');
  await input.press('Enter');
  expect((await request).postDataJSON().query).toBe('Review this case\nX');
  await expect(input).toHaveValue('');
  const userText = panel.locator('.is-user').getByText('Review this case X', { exact: true });
  await expect(userText).toBeVisible();
  await expect(userText).toHaveCSS('color', 'rgb(58, 69, 82)'); // text-gs-ink-2 on cyan-soft bubble
});

test('composer remains disabled when another analyst owns the case', async ({ page }) => {
  const panel = await openAnalyst(page, true);
  await expect(panel.locator('textarea')).toBeDisabled();
  await expect(panel.getByRole('button', { name: 'Attach image', exact: true })).toBeDisabled();
  await expect(panel.getByRole('button', { name: 'Send message', exact: true })).toBeDisabled();
});
