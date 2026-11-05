import { describe, expect, it, vi } from 'vitest';
import type { Page } from '../../../../../tests/e2e/browser/support/playwright';
import { waitForCredentialRedirect } from '../../../../../tests/e2e/browser/auth/auth-redirect';

describe('credential redirect readiness', () => {
  it('requires navigation away from sign-in without waiting for all external resources', async () => {
    const waitForURL = vi.fn().mockResolvedValue(undefined);
    await waitForCredentialRedirect({ waitForURL } as unknown as Page);
    const [predicate, options] = waitForURL.mock.calls[0];
    expect(options).toEqual({ timeout: 60_000, waitUntil: 'domcontentloaded' });
    expect(predicate(new URL('https://preview.example/sign-in/factor-one'))).toBe(false);
    expect(predicate(new URL('https://preview.example/workplace'))).toBe(true);
  });

  it('reports only credential state instead of forwarding an unsafe navigation error', async () => {
    const page = {
      waitForURL: vi.fn().mockRejectedValue(new Error('unsafe query token=private')),
      evaluate: vi.fn().mockResolvedValue({ sessionActive: false, signInStatus: 'needs_second_factor' }),
    };
    await expect(waitForCredentialRedirect(page as unknown as Page)).rejects.toThrow(
      'Credential redirect did not complete: {"sessionActive":false,"signInStatus":"needs_second_factor"}',
    );
  });

  it('accepts a bounded timeout for a retryable credential submission', async () => {
    const waitForURL = vi.fn().mockResolvedValue(undefined);
    await waitForCredentialRedirect({ waitForURL } as unknown as Page, 30_000);
    expect(waitForURL.mock.calls[0][1]).toEqual({ timeout: 30_000, waitUntil: 'domcontentloaded' });
  });
});
