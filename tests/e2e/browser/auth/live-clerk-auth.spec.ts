import { expect, test, type APIRequestContext } from '../support/playwright';

const clerkApi = 'https://api.clerk.com/v1';

declare global {
  interface Window {
    Clerk?: {
      loaded: boolean;
      client: { signIn: { create(options: { strategy: string; ticket: string }): Promise<{ createdSessionId: string }> } };
      setActive(options: { session: string; organization?: string }): Promise<void>;
      session?: { getToken(): Promise<string | null> };
    };
  }
}

async function createSignInToken(request: APIRequestContext) {
  const secret = process.env.CLERK_SECRET_KEY;
  const userId = process.env.CLERK_TEST_USER_ID;
  if (!secret || !userId) throw new Error('CLERK_SECRET_KEY and CLERK_TEST_USER_ID are required');
  const response = await request.post(`${clerkApi}/sign_in_tokens`, {
    headers: { Authorization: `Bearer ${secret}` },
    data: { user_id: userId, expires_in_seconds: 120 },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).token as string;
}

test('real Clerk login keeps workplace API access through detail and refresh', async ({ page, request, baseURL }) => {
  test.skip(process.env.RUN_LIVE_AUTH_E2E !== 'true', 'opt in with RUN_LIVE_AUTH_E2E=true');
  const backend = process.env.AUTH_E2E_BACKEND_URL || 'https://p063-backend-production.up.railway.app';
  const ticket = await createSignInToken(request);
  let sessionId: string | undefined;
  const automaticResponses: Array<{ path: string; status: number; bearer: boolean }> = [];
  await page.route('**/api/v1/**', async (route) => {
    const requestInfo = route.request();
    const target = `${backend}${new URL(requestInfo.url()).pathname}${new URL(requestInfo.url()).search}`;
    const response = await route.fetch({ url: target });
    automaticResponses.push({ path: new URL(requestInfo.url()).pathname, status: response.status(), bearer: Boolean(requestInfo.headers().authorization) });
    await route.fulfill({ response });
  });

  try {
    await page.goto('/sign-in', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => Boolean(window.Clerk?.loaded));
    sessionId = await page.evaluate(async (value) => {
      const signIn = await window.Clerk!.client.signIn.create({ strategy: 'ticket', ticket: value });
      return signIn.createdSessionId;
    }, ticket);
    await page.evaluate(async ({ createdSessionId, organization }) => {
      await window.Clerk!.setActive({ session: createdSessionId, organization });
    }, { createdSessionId: sessionId, organization: process.env.CLERK_TEST_ORGANIZATION_ID });
    await page.goto(`${baseURL}/workplace`, { waitUntil: 'domcontentloaded' });
    await expect.poll(() => automaticResponses.some((item) => item.path === '/api/v1/me'),
      { timeout: 30_000, message: 'signed-in workplace must request /me' }).toBe(true);
    for (const path of ['/api/v1/me', '/api/v1/cases']) {
      const response = automaticResponses.find((item) => item.path === path);
      expect(response, `automatic ${path} response missing`).toBeTruthy();
      expect(response?.status, `automatic ${path} status`).toBe(200);
      expect(response?.bearer, `automatic ${path} bearer`).toBeTruthy();
    }

    const result = await page.evaluate(async (url) => {
      const token = await window.Clerk!.session!.getToken();
      if (!token) throw new Error('Clerk did not create a session token');
      const headers = { Authorization: `Bearer ${token}` };
      const [me, cases] = await Promise.all([
        fetch(`${url}/api/v1/me`, { headers }),
        fetch(`${url}/api/v1/cases?availability=available`, { headers }),
      ]);
      return { me: me.status, cases: cases.status };
    }, backend);

    expect(result.me).toBe(200);
    expect(result.cases).toBe(200);
    const caseId = await page.evaluate(async (url) => {
      const token = await window.Clerk!.session!.getToken();
      const response = await fetch(`${url}/api/v1/cases?availability=available`, { headers: { Authorization: `Bearer ${token}` } });
      const body = await response.json() as { items?: Array<{ id: string }> };
      return body.items?.[0]?.id;
    }, backend);
    if (caseId) {
      const detail = await page.evaluate(async ({ url, id }) => {
        const token = await window.Clerk!.session!.getToken();
        return (await fetch(`${url}/api/v1/cases/${id}`, { headers: { Authorization: `Bearer ${token}` } })).status;
      }, { url: backend, id: caseId });
      expect(detail).toBe(200);
    }
    await page.reload({ waitUntil: 'domcontentloaded' });
    const waitSeconds = Number(process.env.AUTH_E2E_WAIT_SECONDS || '60');
    await page.waitForTimeout(waitSeconds * 1000);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(5_000);
    expect(automaticResponses.filter((item) => item.path === '/api/v1/me').at(-1)?.status).toBe(200);
  } finally {
    if (sessionId) {
      const secret = process.env.CLERK_SECRET_KEY;
      const revoked = await request.post(`${clerkApi}/sessions/${sessionId}/revoke`, {
        headers: { Authorization: `Bearer ${secret}` },
      });
      expect(revoked.ok()).toBeTruthy();
    }
  }
});
