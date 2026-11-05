// @vitest-environment node
import { expect, test, vi } from 'vitest';
import { unstable_doesMiddlewareMatch } from 'next/experimental/testing/server';

vi.mock('@clerk/nextjs/server', () => ({
  clerkMiddleware: vi.fn(() => vi.fn()),
}));

import { config } from '../middleware';

// `/` must receive Clerk middleware context: RootPage calls auth(), which
// throws without it (Refs #181). Public access is preserved because the
// handler returns next() when there is no protected area, and keyless envs
// bypass Clerk before it runs.
test.each(['/', '/?redirect_url=%2Fworkplace'])('root route receives middleware context: %s', (url) => {
  expect(unstable_doesMiddlewareMatch({ config, url })).toBe(true);
});

test.each(['/workplace', '/driver', '/sign-in', '/onboarding'])('existing authentication routes remain covered: %s', (url) => {
  expect(unstable_doesMiddlewareMatch({ config, url })).toBe(true);
});

test.each(['/_next/static/chunk.js', '/favicon.ico'])('static assets remain outside authentication middleware: %s', (url) => {
  expect(unstable_doesMiddlewareMatch({ config, url })).toBe(false);
});
