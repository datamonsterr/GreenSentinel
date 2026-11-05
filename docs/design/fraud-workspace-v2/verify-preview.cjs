let chromium;
for (const mod of [
  process.env.PLAYWRIGHT_MODULE,
  '@playwright/test',
  'playwright',
  '/home/dat/dev/vinuni_aia/P-063/src/webapp/node_modules/@playwright/test',
  '/home/dat/.npm/_npx/e41f203b7505f1fb/node_modules/playwright'
]) {
  if (!mod) continue;
  try {
    const loaded = require(mod);
    chromium = loaded.chromium || (loaded.default && loaded.default.chromium);
    if (chromium) break;
  } catch {}
}
if (!chromium) throw new Error('Could not resolve Playwright module');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
(async () => {
  const executablePath = process.env.CHROMIUM_EXECUTABLE || [
    '/home/dat/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',
    '/home/dat/.cache/ms-playwright/chromium-1227/chrome-linux64/chrome',
    '/usr/bin/chromium',
    '/usr/bin/google-chrome'
  ].find(p => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}), args: ['--disable-gpu'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const base = pathToFileURL(path.join(__dirname, 'preview.html')).href;
  const checks = [];
  const check = (name, ok) => { assert.ok(ok, name); checks.push(name); };
  await page.goto(base);
  check('Locale dictionary keys match', await page.evaluate(() => JSON.stringify(Object.keys(preview.copy.en).sort()) === JSON.stringify(Object.keys(preview.copy.vi).sort())));
  check('No classification before reveal', await page.getByText('Possible deliberate delay', { exact: true }).count() === 0);
  await page.screenshot({ path: path.join(__dirname, 'overview-en.png'), fullPage: true });
  await page.locator('[data-locale=vi]').click();
  check('Vietnamese root language', await page.locator('html').getAttribute('lang') === 'vi');
  await page.screenshot({ path: path.join(__dirname, 'overview-vi.png'), fullPage: true });
  await page.locator('[data-locale=en]').click();
  await page.locator('#tab-overview').focus();
  await page.keyboard.press('ArrowRight');
  check('Arrow key changes and focuses Trip', await page.locator('#tab-trip').getAttribute('aria-selected') === 'true' && await page.locator('#tab-trip').evaluate(el => el === document.activeElement));
  await page.keyboard.press('End');
  check('End selects Complete', await page.locator('#tab-finalization').getAttribute('aria-selected') === 'true');
  await page.keyboard.press('Home');
  await page.locator('.tripline').click();
  check('Trip quick detail opens Trip', await page.locator('#tab-trip').getAttribute('aria-selected') === 'true');
  for (const tab of ['maps', 'customer', 'driver', 'overview']) { await page.locator('#tab-' + tab).click(); check(tab + ' panel linked', await page.locator('#panel-' + tab).count() === 1); }
  await page.locator('.center [data-action=claim]').click();
  check('Overview claim shares busy state with case card', await page.locator('[data-claim="0"]').isDisabled());
  await page.waitForTimeout(700);
  check('Overview claim acquires shared ownership', await page.locator('.center [data-action=claim]').isDisabled() && await page.locator('[data-action=release]').count() === 1);
  await page.locator('[data-action=release]').click();
  check('Release restores Overview claim control', await page.locator('.center [data-action=claim]').isEnabled());
  check('Initial queue case cards have no Reject button', await page.locator('.cases [data-action=reject]').count() === 0);
  check('Initial queue case cards have no Dismiss button', await page.locator('.cases [data-action=rejectfinal]').count() === 0);
  await page.locator('#scenario').selectOption('error');
  await page.locator('[data-claim="0"]').click();
  check('Claim shows loading and disables duplicate clicks', await page.locator('[data-claim="0"]').isDisabled() && await page.locator('[data-claim="0"]').textContent() === 'Claiming…');
  await page.getByText('Claim failed. Check the connection and try again.').waitFor();
  check('Failure does not acquire lease', await page.evaluate(() => !preview.getState().claimed));
  await page.locator('#scenario').selectOption('conflict');
  await page.locator('[data-claim="0"]').click();
  await page.getByText('Another analyst claimed this case.', { exact: false }).waitFor();
  check('Conflict exposes refresh', await page.locator('[data-action=refresh]').isVisible());
  await page.locator('[data-action=refresh]').click();
  await page.locator('#scenario').selectOption('success');
  await page.locator('[data-claim="0"]').click();
  await page.locator('[data-action=release]').waitFor();
  check('Success exposes Release without card rejection', await page.locator('[data-action=release]').isVisible() && await page.locator('.case [data-action=reject]').count() === 0);
  check('Claimed case card exposes Release lease action only', await page.locator('.case.selected [data-action=release]').count() === 1 && await page.locator('.case.selected [data-action=reject]').count() === 0 && await page.locator('.case.selected [data-action=rejectfinal]').count() === 0);
  await page.locator('[data-action=release]').click();
  check('Release returns claim action', await page.locator('[data-claim="0"]').isVisible());
  await page.locator('[data-claim="0"]').click();
  await page.locator('#tab-finalization').click();
  check('Complete opens with independent judgment gate', await page.locator('#tab-finalization').getAttribute('aria-selected') === 'true' && await page.locator('[data-action=reveal]').isVisible() && await page.locator('#decision').count() === 0);
  await page.locator('[data-action=workflow]').click();
  await page.locator('#workflow-input').fill('Route review\nDriver follow-up');
  await page.locator('[data-action=save-workflow]').click();
  check('Workflow can be edited', await page.getByText('Route review → Driver follow-up').isVisible());
  await page.screenshot({ path: path.join(__dirname, 'finalization-gated-en.png'), fullPage: true });
  await page.locator('[data-action=reveal]').click();
  check('View AI opens independent judgment only', await page.getByText('Your independent judgment', { exact: true }).isVisible() && await page.getByText('Possible deliberate delay', { exact: true }).count() === 0);
  check('Unselected judgment cannot submit', await page.locator('[data-action=submit-judgment]').isDisabled());
  await page.locator('[name=judgment][value=uncertain]').check();
  await page.locator('#independent-note').fill('Traffic corroboration is missing; request driver evidence.');
  await page.locator('[data-action=submit-judgment]').click();
  check('Judgment submission reveals AI without another click', await page.getByText('Possible deliberate delay', { exact: true }).isVisible());
  await page.locator('[data-rationale=analystnotes]').fill('Check traffic evidence before closing the case.');
  check('Dismiss is an explicit Complete decision', await page.locator('#decision option[value=rejectfinal]').textContent() === 'Dismiss');
  check('Dismiss belongs only to Complete decision select', await page.locator('#decision option[value=rejectfinal]').count() === 1 && await page.locator('.cases [data-action=rejectfinal]').count() === 0 && await page.locator('.queue button:has-text("Dismiss"), .cases button:has-text("Dismiss")').count() === 0);
  await page.locator('#decision').selectOption('rejectfinal');
  check('Selecting Dismiss alone does not submit', await page.locator('[data-action=submit]').isVisible() && await page.getByText('Preview complete.', { exact: false }).count() === 0);
  await page.locator('#decision').selectOption('request');
  await page.locator('.submit-row [data-action=claim]').click();
  await page.waitForTimeout(700);
  check('Final submission enabled for claimed case', await page.locator('[data-action=submit]').isEnabled());
  await page.screenshot({ path: path.join(__dirname, 'finalization-en.png'), fullPage: true });
  await page.locator('[data-locale=vi]').click();
  check('Locale switch preserves analyst draft', await page.locator('[data-rationale=analystnotes]').inputValue() === 'Check traffic evidence before closing the case.');
  check('Locale switch preserves decision selection', await page.locator('#decision').inputValue() === 'request');
  check('Untouched rationale follows locale', await page.locator('[data-rationale=facts]').inputValue() === 'Di chuyển hạn chế; cần đối chiếu tình hình giao thông.');
  await page.locator('[data-rationale=analystnotes]').fill('Kiểm tra bằng chứng giao thông trước khi kết thúc hồ sơ.');
  await page.locator('[data-action=workflow]').click();
  await page.locator('#workflow-input').fill('Xem lộ trình\nYêu cầu tài xế bổ sung');
  await page.locator('[data-action=save-workflow]').click();
  await page.screenshot({ path: path.join(__dirname, 'finalization-vi.png'), fullPage: true });
  await page.locator('[data-action=submit]').click();
  check('Submission clearly states preview only', await page.getByText('Hoàn tất minh họa. Chưa gửi quyết định và không thay đổi hồ sơ.').isVisible());
  await page.setViewportSize({ width: 1600, height: 1000 });
  check('1600px desktop viewport has no horizontal page overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.setViewportSize({ width: 1280, height: 900 });
  check('1280px desktop viewport has no horizontal page overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.setViewportSize({ width: 390, height: 844 });
  check('390px mobile viewport has no horizontal page overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  check('Reduced motion can be requested', await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches));
  check('No browser runtime errors', errors.length === 0);
  const report = { checkedAt: new Date().toISOString(), scope: 'Design specimen only; not application/API/hosted/persistence evidence.', viewport: '1600x1000 screenshots; 1600px, 1280px, and 390px overflow checks', passed: checks.length, checks, browserErrors: errors };
  fs.writeFileSync(path.join(__dirname, 'validation.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
