// @vitest-environment node
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NextRequest } from 'next/server';

const session = vi.hoisted(() => ({ userId: 'member', getToken: vi.fn(async () => 'signed') }));
vi.mock('@clerk/nextjs/server', () => ({
  clerkMiddleware: (handler: (auth: () => Promise<typeof session>, request: NextRequest) => unknown) =>
    (request: NextRequest) => handler(async () => session, request),
}));

import middleware, { config } from '../../middleware';
import { protectedArea } from '../../lib/route-authorization';

beforeEach(() => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  session.userId = 'member';
  session.getToken.mockReset().mockResolvedValue('signed');
});

test.each(['/test', '/test/workplace', '/test/history'])('anonymous navigation to %s requires sign-in', async (path) => {
  vi.stubEnv('NODE_ENV', 'production');
  session.userId = '';
  const url = `https://preview.example${path}`;
  const response = await middleware(new NextRequest(url), {} as never);
  expect(response?.status).toBe(307);
  const destination = new URL(response!.headers.get('location')!);
  expect(destination.pathname).toBe('/sign-in');
  expect(destination.searchParams.get('redirect_url')).toBe(url);
});

test.each([{ roles: ['driver'] }, { roles: ['analyst'] }, { roles: ['admin'] }, { roles: [] }])('organization member with %j can use the console', async ({ roles }) => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ organization_id: 'org-a', roles })));
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(200);
});

test('console access does not depend on a roles field when the principal has an organization', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ organization_id: 'org-a' })));
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(200);
});

test.each([{}, { roles: ['admin'] }, { organization_id: '', roles: ['driver'] }])('member without an organization is denied: %j', async (principal) => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(principal)));
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(403);
});

test.each([401, 403, 503])('backend denial %s cannot expose the console', async (status) => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('denied', { status })));
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(403);
});

test('authentication outage does not expose the console', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('unavailable'); }));
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(503);
});

test('expired or absent session token cannot expose the console', async () => {
  session.getToken.mockResolvedValue('');
  expect((await middleware(new NextRequest('https://preview.example/test'), {} as never))?.status).toBe(403);
});

test('console matcher covers descendants without protecting similarly named public paths', () => {
  expect(config.matcher).toContain('/test/:path*');
  expect(protectedArea('/test-history')).toBeNull();
});
