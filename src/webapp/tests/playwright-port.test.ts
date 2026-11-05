import { describe, expect, it } from 'vitest';
import net from 'net';
import { resolvePort } from '../playwright.config';

describe('Playwright port isolation', () => {
  it('respects explicit PORT env var', () => {
    expect(resolvePort({ PORT: '4500' })).toBe('4500');
  });

  it('extracts port from PLAYWRIGHT_TEST_BASE_URL if PORT is omitted', () => {
    expect(resolvePort({ PLAYWRIGHT_TEST_BASE_URL: 'http://localhost:4600' })).toBe('4600');
  });

  it('defaults to 3000 in local dev environment when CI is not set', () => {
    expect(resolvePort({})).toBe('3000');
  });

  it('dynamically allocates an available isolated port in CI when PORT is not passed', () => {
    const portStr = resolvePort({ CI: 'true' });
    const port = parseInt(portStr, 10);
    expect(port).toBeGreaterThan(1024);
    expect(port).toBeLessThan(65536);
  });

  it('does not select occupied port 3000 in CI even if port 3000 has a listener', async () => {
    // Start a listener on 3000
    const server = net.createServer();
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(3000, () => resolve());
    }).catch(() => {
      // If 3000 is already in use by another process, server won't bind, which is fine
    });

    try {
      const portStr = resolvePort({ CI: 'true' });
      expect(portStr).not.toBe('3000');
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
