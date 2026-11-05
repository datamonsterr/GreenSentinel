// @vitest-environment node
import { afterEach, expect, test, vi } from 'vitest';
import { NextRequest } from 'next/server';

const session = vi.hoisted(() => ({ userId: 'user', getToken: vi.fn(async () => 'signed') }));
vi.mock('@clerk/nextjs/server', () => ({
  createRouteMatcher: () => (request: NextRequest) => /^\/(driver|workplace)(\/|$)/.test(request.nextUrl.pathname),
  clerkMiddleware: (handler: (auth: () => Promise<typeof session>, request: NextRequest) => any) => (request: NextRequest) => handler(async () => session, request),
}));
import middleware from '../middleware';
import { isolatedGisBuild } from '../lib/isolated-gis-build';
import { localTestAuthentication } from '../lib/route-authorization';

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); session.userId = 'user'; });

test.each([
  ['http://127.0.0.1:18662', true],
  ['https://127.0.0.1:18662', false],
  ['https://backend.example', false],
  ['http://127.0.0.1.backend.example', false],
  ['', false],
])('optimized GIS build only accepts loopback API %s', (backend, expected) => {
  vi.stubEnv('NEXT_PUBLIC_GIS_OPTIMIZED_TEST', 'true');
  vi.stubEnv('NEXT_PUBLIC_E2E_TEST', 'true');
  vi.stubEnv('NEXT_PUBLIC_API_URL', backend);
  expect(isolatedGisBuild()).toBe(expected);
});

test.each([
  ['http://127.0.0.1:3162/workplace', '127.0.0.1:3162', 200],
  ['https://preview.example/workplace', 'preview.example', 403],
  ['http://127.0.0.1:3162/workplace', 'preview.example', 403],
])('optimized GIS authentication is restricted to loopback requests %s with Host %s', async (url, host, expected) => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('APP_ENV', 'test');
  vi.stubEnv('TEST_AUTH_ENABLED', 'true');
  vi.stubEnv('NEXT_PUBLIC_GIS_OPTIMIZED_TEST', 'true');
  vi.stubEnv('NEXT_PUBLIC_E2E_TEST', 'true');
  vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://127.0.0.1:18662');
  session.userId = '';
  expect(isolatedGisBuild()).toBe(true);
  expect(localTestAuthentication()).toBe(true);
  expect((await middleware(new NextRequest(url, { headers: { host } }), {} as never))?.status).toBe(expected);
});

test('production E2E flags never expose Driver pages without a session', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('E2E_TEST', 'true');
  vi.stubEnv('NEXT_PUBLIC_E2E_TEST', 'true');
  session.userId = '';
  const response = await middleware(new NextRequest('https://preview.example/driver'), {} as never);
  expect(response?.status).toBe(307);
  expect(response?.headers.get('location')).toContain('/sign-in');
});

test('Driver cannot navigate directly to workplace even with authenticated Clerk session', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: ['driver'], organization_id: 'org', driver_id: 'driver' })));
  const response = await middleware(new NextRequest('https://preview.example/workplace?view=analytics'), {} as never);
  expect(response?.status).toBe(403);
});

test.each([
  ['driver', 'driver', 200], ['analyst', 'workplace', 200],
  ['fraud_analyst', 'workplace', 200],
  ['admin', 'workplace', 200], ['admin', 'driver', 200],
  ['analyst', 'driver', 403],
  ['unknown', 'workplace', 403], ['driver', 'analytics', 403],
])('persisted %s role gates /%s', async (role, area, expected) => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: [role], organization_id: 'org', driver_id: role === 'driver' ? 'driver' : null })));
  const response = await middleware(new NextRequest(`https://preview.example/${area}`), {} as never);
  expect(response?.status).toBe(expected);
});

test.each([401, 403, 503])('backend denial %s cannot expose protected page', async (status) => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('denied', { status })));
  expect((await middleware(new NextRequest('https://preview.example/driver'), {} as never))?.status).toBe(403);
});

test('backend failure denies protected page', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('unavailable'); }));
  expect((await middleware(new NextRequest('https://preview.example/workplace'), {} as never))?.status).toBe(503);
});

test('keyless public root bypasses Clerk instead of 503 (Refs #181)', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  delete process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const response = await middleware(new NextRequest('https://preview.example/'), {} as never);
  expect(response?.status).toBe(200);
});

test('keyed public root passes through Clerk handler (Refs #181)', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  const response = await middleware(new NextRequest('https://preview.example/'), {} as never);
  expect(response?.status).toBe(200);
});

test('unprovisioned signed-in user is guided to onboarding, not bare 403', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: 'Clerk user has no active assigned role' }, { status: 403 })));
  const response = await middleware(new NextRequest('https://preview.example/workplace'), {} as never);
  expect(response?.status).toBe(307);
  expect(response?.headers.get('location')).toContain('/onboarding');
});

test.each([
  ['driver', 'workplace', 'driver'],
  ['analyst', 'driver', 'analyst'],
])('wrong-role signed-in %s on /%s is rewritten to access-denied?role=%s', async (role, area, expectedRole) => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: [role], organization_id: 'org', driver_id: role === 'driver' ? 'driver' : null })));
  const response = await middleware(new NextRequest(`https://preview.example/${area}`), {} as never);
  expect(response?.status).toBe(403);
  const rewrite = response?.headers.get('x-middleware-rewrite');
  expect(rewrite).toContain('/access-denied');
  expect(new URL(rewrite!).searchParams.get('role')).toBe(expectedRole);
});

test('driver signed-in user on /organization is rewritten to access-denied?role=driver', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: ['driver'], organization_id: 'org', driver_id: 'driver' })));
  const response = await middleware(new NextRequest('https://preview.example/organization'), {} as never);
  expect(response?.status).toBe(403);
  const rewrite = response?.headers.get('x-middleware-rewrite');
  expect(rewrite).toContain('/access-denied');
  expect(new URL(rewrite!).searchParams.get('role')).toBe('driver');
});

test('backend denial still receives bare 403 text, no rewrite', async () => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY', 'pk_test');
  vi.stubGlobal('fetch', vi.fn(async () => new Response('denied', { status: 401 })));
  const response = await middleware(new NextRequest('https://preview.example/driver'), {} as never);
  expect(response?.status).toBe(403);
  expect(response?.headers.get('x-middleware-rewrite')).toBeNull();
  expect(await response?.text()).toBe('Access denied');
});
