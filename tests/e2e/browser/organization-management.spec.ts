import { test, expect, type Page, type Locator, type TestInfo } from './support/playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

// Explicit synthetic API records. This suite exercises the actual Next route;
// it provides no evidence about Clerk, persistent storage, or email delivery.
const MEMBERS = [
  { id: 'member-z', display_name: 'Zoe Synthetic', roles: ['driver'], status: 'active' },
  { id: 'member-a', display_name: 'Ava Synthetic', roles: ['admin'], status: 'active' },
  { id: 'member-m', display_name: 'Mina Synthetic', roles: ['fraud_analyst'], status: 'active' },
];
const INVITATIONS = [
  { id: 'invite-z', email: 'zoe@example.test', role: 'driver', status: 'pending' },
  { id: 'invite-a', email: 'ava@example.test', role: 'admin', status: 'revoked' },
  { id: 'invite-m', email: 'mina@example.test', role: 'analyst', status: 'pending' },
];

type ApiCall = { method: string; pathname: string; body: unknown; offset?: number };
type FixtureOptions = {
  membersStatus?: number;
  invitationsStatus?: number;
  empty?: boolean;
  inviteStatus?: number;
  beforeInviteResponse?: () => Promise<void>;
  memberPages?: Array<typeof MEMBERS>;
  invitationPages?: Array<typeof INVITATIONS>;
};

const browserDiagnostics = new WeakMap<Page, { pageErrors: string[]; consoleErrors: string[] }>();

async function installOrganizationFixtures(page: Page, options: FixtureOptions = {}) {
  const calls: ApiCall[] = [];
  const members = structuredClone(options.empty ? [] : MEMBERS);
  const invitations = structuredClone(options.empty ? [] : INVITATIONS);
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const pathname = url.pathname;
    const body = request.postData() ? request.postDataJSON() : null;
    calls.push({
      method,
      pathname,
      body,
      ...(method === 'GET' ? { offset: Number(url.searchParams.get('offset') ?? '0') } : {}),
    });
    if (method === 'GET' && pathname === '/api/v1/account/settings') {
      return route.fulfill({ json: { id: 'synthetic-admin', organization_id: 'synthetic-org', roles: ['admin'] } });
    }
    if (method === 'GET' && pathname === '/api/v1/me') {
      return route.fulfill({ json: { id: 'synthetic-admin', display_name: 'Synthetic Admin', roles: ['admin'] } });
    }
    if (method === 'GET' && pathname === '/api/v1/account/users') {
      const offset = Number(url.searchParams.get('offset') ?? '0');
      const page = options.memberPages?.[offset / 50] ?? members;
      return route.fulfill({ status: options.membersStatus ?? 200, json: page });
    }
    if (method === 'GET' && pathname === '/api/v1/admin/invitations') {
      const offset = Number(url.searchParams.get('offset') ?? '0');
      const page = options.invitationPages?.[offset / 50] ?? invitations;
      const total = options.invitationPages
        ? options.invitationPages.reduce((count, items) => count + items.length, 0)
        : invitations.length;
      return route.fulfill({ status: options.invitationsStatus ?? 200, json: { items: page, total } });
    }
    if (method === 'POST' && pathname === '/api/v1/admin/invitations') {
      await options.beforeInviteResponse?.();
      if ((options.inviteStatus ?? 201) >= 400) {
        return route.fulfill({ status: options.inviteStatus, json: { detail: 'Synthetic provider rejected invitation.' } });
      }
      const invitation = { id: `new-invite-${invitations.length}`, ...body, status: 'pending' };
      invitations.push(invitation);
      return route.fulfill({ status: 201, json: invitation });
    }
    const member = members.find(item => pathname === `/api/v1/account/users/${item.id}/role`);
    if (method === 'PATCH' && member) {
      member.roles = [body.role];
      return route.fulfill({ json: member });
    }
    const allInvitations = options.invitationPages?.flat() ?? invitations;
    const invitation = allInvitations.find(item => pathname.startsWith(`/api/v1/admin/invitations/${item.id}/`));
    if (method === 'POST' && invitation && /\/(resend|revoke)$/.test(pathname)) {
      if (pathname.endsWith('/revoke')) invitation.status = 'revoked';
      return route.fulfill({ json: invitation });
    }
    // Never forward an unexpected fixture API request to a real service.
    return route.fulfill({ status: 404, json: { detail: 'Unexpected organization fixture endpoint.' } });
  });
  return calls;
}

async function openOrganization(page: Page) {
  await page.goto('/organization');
  await expect(page.getByRole('heading', { name: 'Organization', exact: true })).toBeVisible();
  await expect(page.getByRole('status', { name: 'Loading members', exact: true })).toHaveCount(0);
  await expect(page.getByRole('status', { name: 'Loading invitations', exact: true })).toHaveCount(0);
}

async function chooseOption(page: Page, label: string, option: string) {
  await page.getByRole('combobox', { name: label, exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

function firstCells(table: Locator) {
  return table.locator('tbody tr td:first-child');
}

async function capture(page: Page, testInfo: TestInfo, filename: string) {
  const directory = process.env.GREENSENTINEL_ORGANIZATION_EVIDENCE_DIR;
  if (directory) await mkdir(directory, { recursive: true });
  const target = directory ? path.join(directory, filename) : testInfo.outputPath(filename);
  await page.screenshot({ path: target, fullPage: true });
  await testInfo.attach(filename, { path: target, contentType: 'image/png' });
}

test.beforeEach(async ({ page, baseURL }) => {
  // The test auth fixture is an existing development-only application path.
  // Refuse external targets; this suite must never bypass hosted auth.
  expect(baseURL, 'Local fixture baseURL is required').toBeTruthy();
  expect(['localhost', '127.0.0.1', '[::1]']).toContain(new URL(baseURL!).hostname);
  const diagnostics = { pageErrors: [] as string[], consoleErrors: [] as string[] };
  browserDiagnostics.set(page, diagnostics);
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') diagnostics.consoleErrors.push(message.text());
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const diagnostics = browserDiagnostics.get(page)!;
  await testInfo.attach('local-browser-diagnostics', {
    body: JSON.stringify({ url: page.url(), viewport: page.viewportSize(), ...diagnostics }, null, 2),
    contentType: 'application/json',
  });
  expect(diagnostics.pageErrors, 'Uncaught browser exceptions').toEqual([]);
});

test('invite dialog starts at email, traps keyboard focus, and returns focus on Escape', async ({ page }, testInfo) => {
  await installOrganizationFixtures(page);
  await openOrganization(page);
  const trigger = page.getByRole('button', { name: 'Invite user', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Invite user to organization', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: 'Email address', exact: true })).toBeFocused();
  await expect(dialog.getByRole('combobox', { name: 'Role', exact: true })).toHaveText('Analyst');
  for (const key of ['Tab', 'Shift+Tab']) {
    for (let step = 0; step < 7; step += 1) {
      await page.keyboard.press(key);
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
  }
  await capture(page, testInfo, 'actual-app-invite-dialog.png');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test('keyboard Driver selection and repeated Enter create exactly one invitation', async ({ page }) => {
  let release!: () => void;
  const responseGate = new Promise<void>(resolve => { release = resolve; });
  const calls = await installOrganizationFixtures(page, { beforeInviteResponse: () => responseGate });
  await openOrganization(page);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Invite user to organization' });
  const email = dialog.getByRole('textbox', { name: 'Email address' });
  await email.fill('keyboard-driver@example.test');
  const role = dialog.getByRole('combobox', { name: 'Role', exact: true });
  await role.focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('listbox')).toBeVisible();
  await expect(page.getByRole('option', { name: 'Analyst', exact: true })).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.getByRole('option', { name: 'Driver', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(role).toHaveText('Driver');
  await email.focus();
  try {
    await page.keyboard.press('Enter');
    await expect(dialog.getByRole('button', { name: 'Inviting...', exact: true })).toBeDisabled();
    await page.keyboard.press('Enter');
    expect(calls.filter(call => call.method === 'POST')).toEqual([
      { method: 'POST', pathname: '/api/v1/admin/invitations', body: { email: 'keyboard-driver@example.test', role: 'driver' } },
    ]);
  } finally {
    release();
  }
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('cell', { name: 'keyboard-driver@example.test', exact: true })).toBeVisible();
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
});

test('click submits one Analyst invitation with the correct payload', async ({ page }) => {
  const calls = await installOrganizationFixtures(page);
  await openOrganization(page);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('textbox', { name: 'Email address' }).fill('click-analyst@example.test');
  await dialog.getByRole('button', { name: 'Invite user', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('cell', { name: 'click-analyst@example.test', exact: true })).toBeVisible();
  expect(calls.filter(call => call.method === 'POST')).toEqual([
    { method: 'POST', pathname: '/api/v1/admin/invitations', body: { email: 'click-analyst@example.test', role: 'analyst' } },
  ]);
});

test('earlier invitation success preserves the reopened dialog draft', async ({ page }) => {
  let release!: () => void;
  const responseGate = new Promise<void>(resolve => { release = resolve; });
  const calls = await installOrganizationFixtures(page, { beforeInviteResponse: () => responseGate });
  await openOrganization(page);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Invite user to organization', exact: true });
  const email = dialog.getByRole('textbox', { name: 'Email address', exact: true });
  await email.fill('earlier-session@example.test');
  try {
    await email.press('Enter');
    await expect(dialog.getByRole('button', { name: 'Inviting...', exact: true })).toBeDisabled();
    await expect.poll(() => calls.filter(call => call.method === 'POST').length).toBe(1);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await page.getByRole('button', { name: 'Invite user', exact: true }).click();
    await email.fill('reopened-session@example.test');
    await chooseOption(page, 'Role', 'Driver');

    const succeeded = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/v1/admin/invitations' &&
      response.request().method() === 'POST' && response.status() === 201
    );
    release();
    expect(await (await succeeded).finished()).toBeNull();
    // Allow the completed response to render before checking preservation;
    // an assertion against the draft before the response arrives is vacuous.
    await page.evaluate(() => new Promise<void>(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));
    await expect(dialog).toBeVisible();
    await expect(email).toHaveValue('reopened-session@example.test');
    await expect(dialog.getByRole('combobox', { name: 'Role', exact: true })).toHaveText('Driver');
    await expect(dialog.getByRole('button', { name: 'Invite user', exact: true })).toBeEnabled();
    expect(calls.filter(call => call.method === 'POST')).toEqual([
      { method: 'POST', pathname: '/api/v1/admin/invitations', body: { email: 'earlier-session@example.test', role: 'analyst' } },
    ]);
  } finally {
    release();
  }
});

test('invalid email prevents POST and a failed POST preserves email and Driver choice', async ({ page }) => {
  const calls = await installOrganizationFixtures(page, { inviteStatus: 503 });
  await openOrganization(page);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const email = dialog.getByRole('textbox', { name: 'Email address' });
  await email.fill('invalid-address');
  await dialog.getByRole('button', { name: 'Invite user', exact: true }).click();
  await expect(email).toBeFocused();
  expect(await email.evaluate(element => !(element as HTMLInputElement).validity.valid)).toBe(true);
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(0);
  await email.fill('retained-driver@example.test');
  await chooseOption(page, 'Role', 'Driver');
  await dialog.getByRole('button', { name: 'Invite user', exact: true }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Synthetic provider rejected invitation.');
  await expect(email).toHaveValue('retained-driver@example.test');
  await expect(dialog.getByRole('combobox', { name: 'Role', exact: true })).toHaveText('Driver');
  await expect(dialog.getByRole('button', { name: 'Invite user', exact: true })).toBeEnabled();
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
});

test('member and invitation search, filters, reset and sorting change actual row order', async ({ page }) => {
  await installOrganizationFixtures(page);
  await openOrganization(page);
  const members = page.getByRole('table', { name: 'Organization members', exact: true });
  const invitations = page.getByRole('table', { name: 'Organization invitations', exact: true });
  await expect(firstCells(members)).toHaveText(['Zoe Synthetic', 'Ava Synthetic', 'Mina Synthetic']);
  await page.getByRole('textbox', { name: 'Search members' }).fill('zoe');
  await chooseOption(page, 'Filter members by role', 'Driver');
  await chooseOption(page, 'Filter members by status', 'Active');
  await expect(firstCells(members)).toHaveText(['Zoe Synthetic']);
  await page.getByRole('button', { name: 'Reset member filters' }).click();
  await expect(page.getByRole('textbox', { name: 'Search members' })).toHaveValue('');
  await expect(firstCells(members)).toHaveCount(3);
  await members.getByRole('button', { name: 'Member', exact: true }).click();
  await expect(firstCells(members)).toHaveText(['Ava Synthetic', 'Mina Synthetic', 'Zoe Synthetic']);
  await members.getByRole('button', { name: 'Member', exact: true }).click();
  await expect(firstCells(members)).toHaveText(['Zoe Synthetic', 'Mina Synthetic', 'Ava Synthetic']);
  await page.getByRole('textbox', { name: 'Search invitations' }).fill('ava');
  await chooseOption(page, 'Filter invitations by role', 'Admin');
  await chooseOption(page, 'Filter invitations by status', 'Revoked');
  await expect(firstCells(invitations)).toHaveText(['ava@example.test']);
  await page.getByRole('button', { name: 'Reset invitation filters' }).click();
  await expect(page.getByRole('textbox', { name: 'Search invitations' })).toHaveValue('');
  await expect(firstCells(invitations)).toHaveCount(3);
  await invitations.getByRole('button', { name: 'Email', exact: true }).click();
  await expect(firstCells(invitations)).toHaveText(['ava@example.test', 'mina@example.test', 'zoe@example.test']);
  await invitations.getByRole('button', { name: 'Email', exact: true }).click();
  await expect(firstCells(invitations)).toHaveText(['zoe@example.test', 'mina@example.test', 'ava@example.test']);
  await expect(page.getByText('Search and filters apply to this page.', { exact: true })).toHaveCount(2);
});

test('paginates both lists, scopes filters to each page, and refreshes actions on page two', async ({ page }) => {
  const membersPageOne = Array.from({ length: 50 }, (_, index) => ({
    id: `member-page-one-${index}`,
    display_name: `Page One ${index}`,
    roles: ['driver'],
    status: 'active',
  }));
  const membersPageTwo = [{ id: 'member-page-two', display_name: 'Page Two Analyst', roles: ['analyst'], status: 'active' }];
  const invitationsPageOne = Array.from({ length: 50 }, (_, index) => ({
    id: `invite-page-one-${index}`,
    email: `page-one-${index}@example.test`,
    role: 'driver',
    status: 'pending',
  }));
  const invitationsPageTwo = [{ id: 'invite-page-two', email: 'page-two@example.test', role: 'analyst', status: 'pending' }];
  const calls = await installOrganizationFixtures(page, {
    memberPages: [membersPageOne, membersPageTwo],
    invitationPages: [invitationsPageOne, invitationsPageTwo],
  });
  await openOrganization(page);
  await expect(firstCells(page.getByRole('table', { name: 'Organization members', exact: true }))).toHaveCount(50);
  await expect(firstCells(page.getByRole('table', { name: 'Organization invitations', exact: true }))).toHaveCount(50);

  await page.getByRole('button', { name: 'Next members page', exact: true }).click();
  await page.getByRole('button', { name: 'Next invitations page', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'Page Two Analyst', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'page-two@example.test', exact: true })).toBeVisible();
  expect(calls.filter(call => call.method === 'GET' && call.pathname === '/api/v1/account/users').map(call => call.offset)).toEqual([0, 50]);
  expect(calls.filter(call => call.method === 'GET' && call.pathname === '/api/v1/admin/invitations').map(call => call.offset)).toEqual([0, 50]);
  await expect(page.getByRole('button', { name: 'Next members page', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Next invitations page', exact: true })).toBeDisabled();

  await page.getByRole('textbox', { name: 'Search members', exact: true }).fill('page one');
  await expect(page.getByText('No members match your filter', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search invitations', exact: true }).fill('page-one');
  await expect(page.getByText('No invitations match your filter', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reset member filters', exact: true }).click();
  await page.getByRole('button', { name: 'Reset invitation filters', exact: true }).click();

  await page.getByRole('button', { name: 'Resend', exact: true }).click();
  await expect(page.getByText('Invitation record refreshed. No email was sent.', { exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'page-two@example.test', exact: true })).toBeVisible();
  expect(calls.filter(call => call.method === 'GET' && call.pathname === '/api/v1/admin/invitations').map(call => call.offset)).toEqual([0, 50, 50]);

  await page.getByRole('button', { name: 'Previous members page', exact: true }).click();
  await page.getByRole('button', { name: 'Previous invitations page', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'Page One 0', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'page-one-0@example.test', exact: true })).toBeVisible();
  expect(calls.filter(call => call.method === 'GET' && call.pathname === '/api/v1/account/users').map(call => call.offset)).toEqual([0, 50, 0]);
  expect(calls.filter(call => call.method === 'GET' && call.pathname === '/api/v1/admin/invitations').map(call => call.offset)).toEqual([0, 50, 50, 0]);
});

test('Driver remains assignable and invitation actions use their own row IDs', async ({ page }) => {
  const calls = await installOrganizationFixtures(page);
  await openOrganization(page);
  await chooseOption(page, 'Change role for Mina Synthetic', 'Driver');
  await expect(page.getByRole('combobox', { name: 'Change role for Mina Synthetic' })).toHaveText('Driver');
  expect(calls.filter(call => call.method === 'PATCH')).toEqual([
    { method: 'PATCH', pathname: '/api/v1/account/users/member-m/role', body: { role: 'driver' } },
  ]);
  const revoked = page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'ava@example.test', exact: true }) });
  await expect(revoked.getByRole('button', { name: 'Resend', exact: true })).toBeDisabled();
  await expect(revoked.getByRole('button', { name: 'Revoke', exact: true })).toBeDisabled();
  const pending = page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'zoe@example.test', exact: true }) });
  await pending.getByRole('button', { name: 'Resend', exact: true }).click();
  await expect(page.getByText('Invitation record refreshed. No email was sent.', { exact: true })).toBeVisible();
  await expect(pending.getByRole('button', { name: 'Revoke', exact: true })).toBeEnabled();
  await pending.getByRole('button', { name: 'Revoke', exact: true }).click();
  await expect(pending.getByRole('cell', { name: /^revoked$/i })).toBeVisible();
  await expect(pending.getByRole('button', { name: 'Revoke', exact: true })).toBeDisabled();
  expect(calls.filter(call => call.method === 'POST').map(call => call.pathname)).toEqual([
    '/api/v1/admin/invitations/invite-z/resend', '/api/v1/admin/invitations/invite-z/revoke',
  ]);
  await expect(page.getByText(/Population bootstrap|Link driver entity/i)).toHaveCount(0);
  expect(calls.some(call => /bootstrap|driver.*link|link.*driver/.test(call.pathname))).toBe(false);
});

for (const status of [403, 500, 501]) {
  test(`API ${status} shows unavailable state instead of empty organization`, async ({ page }) => {
    await installOrganizationFixtures(page, { membersStatus: status, invitationsStatus: status });
    await openOrganization(page);
    await expect(page.getByText('Members unavailable', { exact: true })).toBeVisible();
    await expect(page.getByText('Invitations unavailable', { exact: true })).toBeVisible();
    await expect(page.getByText('No members yet', { exact: true })).toHaveCount(0);
    await expect(page.getByText('No invitations yet', { exact: true })).toHaveCount(0);
    if (status === 403) await expect(page.getByRole('alert').filter({ hasText: 'Access denied: admin access is required' })).toBeVisible();
  });
}

test('successful empty responses have explicit empty states', async ({ page }) => {
  await installOrganizationFixtures(page, { empty: true });
  await openOrganization(page);
  await expect(page.getByText('No members yet', { exact: true })).toBeVisible();
  await expect(page.getByText('No invitations yet', { exact: true })).toBeVisible();
  await expect(page.getByText('Members unavailable', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Invitations unavailable', { exact: true })).toHaveCount(0);
});

test('desktop content is centered and capped at 1120px with the cyan primary action', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  await installOrganizationFixtures(page);
  await openOrganization(page);
  const container = page.getByRole('region', { name: 'Members', exact: true }).locator('..');
  const box = await container.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeLessThanOrEqual(1120);
  expect(Math.abs(box!.x - (1600 - box!.width) / 2)).toBeLessThanOrEqual(1);
  await expect(page.getByRole('button', { name: 'Invite user', exact: true })).toHaveCSS('background-color', 'rgb(15, 179, 193)'); // Button bg-primary -> --color-primary #0fb3c1 (globals.css @theme, cyan portal theme 0303331)
  await capture(page, testInfo, 'actual-app-desktop-1600.png');
});

for (const width of [320, 390]) {
  test(`mobile ${width}px contains table scrolling and uses 16px editable controls`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await installOrganizationFixtures(page);
    await openOrganization(page);
    const documentFits = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
    expect(await documentFits()).toBe(true);
    for (const name of ['Search members', 'Search invitations']) {
      await expect(page.getByRole('textbox', { name, exact: true })).toHaveCSS('font-size', '16px');
    }
    for (const name of ['Members table; scroll horizontally for more columns', 'Invitations table; scroll horizontally for more columns']) {
      const region = page.getByRole('region', { name, exact: true });
      const dimensions = await region.evaluate(element => ({
        clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
        width: element.getBoundingClientRect().width, overflowX: getComputedStyle(element).overflowX,
      }));
      expect(dimensions.width).toBeLessThanOrEqual(width);
      expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.clientWidth);
      expect(dimensions.overflowX).toBe('auto');
      await region.evaluate(element => { element.scrollLeft = 100; });
      expect(await region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
      await region.evaluate(element => { element.scrollLeft = 0; });
    }
    await page.getByRole('button', { name: 'Reset member filters' }).focus();
    await page.keyboard.press('Tab');
    const membersRegion = page.getByRole('region', { name: 'Members table; scroll horizontally for more columns', exact: true });
    await expect(membersRegion).toBeFocused();
    await expect(membersRegion).toHaveCSS('outline-width', '2px');
    await expect(membersRegion).toHaveCSS('outline-style', 'solid');
    await capture(page, testInfo, `actual-app-mobile-${width}.png`);
    await page.getByRole('button', { name: 'Invite user', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('textbox', { name: 'Email address' })).toHaveCSS('font-size', '16px');
    const dialogBox = await dialog.boundingBox();
    expect(dialogBox!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.x + dialogBox!.width).toBeLessThanOrEqual(width);
    expect(await documentFits()).toBe(true);
    const titleBox = await dialog.getByRole('heading', { name: 'Invite user to organization', exact: true }).boundingBox();
    const closeBox = await dialog.getByRole('button', { name: 'Close', exact: true }).boundingBox();
    expect(titleBox).not.toBeNull();
    expect(closeBox).not.toBeNull();
    expect(titleBox!.x + titleBox!.width, 'Dialog title must not overlap the Close button').toBeLessThanOrEqual(closeBox!.x);
    await expect(dialog.getByRole('button', { name: 'Invite user', exact: true })).toBeInViewport();
    await capture(page, testInfo, `actual-app-mobile-dialog-${width}.png`);
  });
}

test('200% CSS layout zoom and reduced desktop viewport keep invitation controls usable', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  await installOrganizationFixtures(page);
  await openOrganization(page);
  // CSS zoom causes layout reflow, unlike deviceScaleFactor or pinch zoom.
  // Native browser zoom remains a separate manual runbook check.
  await page.evaluate(() => { document.body.style.zoom = '2'; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole('textbox', { name: 'Search members' }).fill('zoe');
  await expect(firstCells(page.getByRole('table', { name: 'Organization members', exact: true }))).toHaveText(['Zoe Synthetic']);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('textbox', { name: 'Email address' })).toBeFocused();
  await expect(dialog.getByRole('button', { name: 'Invite user', exact: true })).toBeInViewport();
  await capture(page, testInfo, 'actual-app-css-zoom-200.png');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Invite user', exact: true })).toBeFocused();
  await page.evaluate(() => { document.body.style.zoom = ''; });
  // A 1600x900 desktop at 200% browser zoom has about 800x450 layout pixels.
  await page.setViewportSize({ width: 800, height: 450 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.getByRole('button', { name: 'Invite user', exact: true }).click();
  await expect(dialog.getByRole('textbox', { name: 'Email address' })).toBeInViewport();
  await expect(dialog.getByRole('button', { name: 'Invite user', exact: true })).toBeInViewport();
  await capture(page, testInfo, 'actual-app-reduced-viewport-800x450.png');
});
