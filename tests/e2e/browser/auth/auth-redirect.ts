import type { Page } from '../support/playwright';

export async function waitForCredentialRedirect(page: Page, timeout = 60_000): Promise<void> {
  try {
    await page.waitForURL((url: URL) => !url.pathname.startsWith('/sign-in'), {
      timeout,
      waitUntil: 'domcontentloaded',
    });
  } catch {
    // Only allowlisted states and booleans: never log credentials, tokens,
    // user identifiers, query strings or the credential page's HTML.
    const state = await page.evaluate(() => {
      const clerk = (window as unknown as { Clerk?: {
        loaded?: boolean;
        session?: unknown;
        client?: { signIn?: { status?: string } };
      } }).Clerk;
      const status = clerk?.client?.signIn?.status;
      const knownStatuses = ['complete', 'needs_identifier', 'needs_first_factor',
        'needs_second_factor', 'needs_new_password'];
      return {
        onSignInPage: window.location.pathname.startsWith('/sign-in'),
        clerkLoaded: Boolean(clerk?.loaded),
        sessionActive: Boolean(clerk?.session),
        signInStatus: status && knownStatuses.includes(status) ? status : 'unknown',
        formErrorPresent: Boolean(document.querySelector(
          '.cl-formFieldErrorText, .cl-alertText, [role="alert"]',
        )),
      };
    }).catch(() => ({ diagnosticUnavailable: true }));
    throw new Error(`Credential redirect did not complete: ${JSON.stringify(state)}`);
  }
}
