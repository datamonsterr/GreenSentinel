import { afterEach, expect, it, vi } from 'vitest';
import type { Page } from '../../../../../tests/e2e/browser/support/playwright';
vi.mock('../../../../../tests/e2e/browser/support/playwright', () => ({ expect: vi.fn() }));
import { realApiStatus } from '../../../../../tests/e2e/browser/auth/role-accounts';
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); Reflect.deleteProperty(window, 'Clerk'); });
it.each([200, 403])('awaits delayed token and preserves status %s', async (status) => {
  const fetch = vi.fn().mockResolvedValue({ status });
  vi.stubGlobal('fetch', fetch);
  vi.stubEnv('AUTH_E2E_BACKEND_URL', 'https://backend.example');
  const getToken = vi.fn().mockResolvedValueOnce(null).mockResolvedValue('test-session-token');
  let now = 0;
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  const page = {
    waitForFunction: vi.fn(async () => ({ jsonValue: async () => null, dispose: vi.fn() })),
    evaluate: async <T, A>(callback: (arg: A) => T, arg: A) => callback(arg),
    waitForTimeout: vi.fn(async (ms: number) => {
      now += ms;
      expect(fetch).not.toHaveBeenCalled();
      Object.assign(window, { Clerk: { loaded: true, session: { getToken } } });
    }),
  };
  expect(await realApiStatus(page as unknown as Page, '/api/v1/me')).toBe(status);
  expect(page.waitForTimeout).toHaveBeenCalledTimes(2);
  expect(getToken).toHaveBeenCalledTimes(2);
  expect(page.waitForFunction).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledWith('https://backend.example/api/v1/me', { headers: { Authorization: 'Bearer test-session-token' } });
});
it('times out without sending an unauthenticated request', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  let now = 0; vi.spyOn(Date, 'now').mockImplementation(() => now);
  const page = {
    evaluate: async <T, A>(callback: (arg: A) => T, arg: A) => callback(arg),
    waitForTimeout: vi.fn(async (ms: number) => { now += ms; }),
  };
  await expect(realApiStatus(page as unknown as Page, '/api/v1/me')).rejects.toThrow('Clerk session readiness timeout');
  expect(page.waitForTimeout).toHaveBeenCalledTimes(300);
  expect(fetch).not.toHaveBeenCalled();
});
