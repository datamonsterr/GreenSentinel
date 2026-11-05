import { describe, it, expect, vi } from 'vitest';
import DriverRootPage from '@/app/driver/page';
import DriverDisputeRedirect from '@/app/driver/dispute/[caseId]/page';

const mockRedirect = vi.fn();
vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    mockRedirect(url);
    throw new Error(`NEXT_REDIRECT:${url}`);
  },
}));

describe('Driver Route Redirects', () => {
  it('redirects /driver to /driver/cases', () => {
    expect(() => DriverRootPage()).toThrow('NEXT_REDIRECT:/driver/cases');
    expect(mockRedirect).toHaveBeenCalledWith('/driver/cases');
  });

  it('redirects /driver/dispute/[caseId] to /driver/chat/[caseId]', async () => {
    await expect(
      DriverDisputeRedirect({ params: Promise.resolve({ caseId: 'CASE-8842' }) })
    ).rejects.toThrow('NEXT_REDIRECT:/driver/chat/CASE-8842');
    expect(mockRedirect).toHaveBeenCalledWith('/driver/chat/CASE-8842');
  });
});
