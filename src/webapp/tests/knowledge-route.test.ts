// @vitest-environment node
import { afterEach, expect, test, vi } from 'vitest';
import { unstable_doesMiddlewareMatch } from 'next/experimental/testing/server';

vi.mock('@clerk/nextjs/server', () => ({ clerkMiddleware: vi.fn(() => vi.fn()) }));

import { config } from '../middleware';
import { decideArea, protectedArea } from '../lib/route-authorization';

afterEach(() => { vi.unstubAllGlobals(); });

test('knowledge is a protected area covered by the middleware matcher', () => {
  expect(protectedArea('/knowledge')).toBe('knowledge');
  expect(protectedArea('/knowledge/anything')).toBe('knowledge');
  expect(unstable_doesMiddlewareMatch({ config, url: '/knowledge' })).toBe(true);
});

test.each([
  ['analyst', 'allow'],
  ['fraud_analyst', 'allow'],
  ['senior_analyst', 'allow'],
  ['admin', 'allow'],
])('role %s may open /knowledge', async (role, expected) => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: [role], organization_id: 'org' })));
  expect(await decideArea('tok', 'knowledge')).toBe(expected);
});

test.each(['driver', 'reviewer', 'ops_director', 'marketplace_director'])('role %s is refused /knowledge', async (role) => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ roles: [role], organization_id: 'org' })));
  expect(await decideArea('tok', 'knowledge')).toMatchObject({ kind: 'wrong_role' });
});
