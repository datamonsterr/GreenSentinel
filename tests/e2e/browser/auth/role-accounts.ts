import type { Page } from '../support/playwright';
import { expect } from '../support/playwright';
import { waitForCredentialRedirect } from './auth-redirect';
import {
  CREDENTIAL_FORM_SELECTOR,
  IDENTIFIER_INPUT_SELECTOR,
  PASSWORD_INPUT_SELECTOR,
  PASSWORD_FORM_SELECTOR,
} from './auth-form-controls';

export type RoleAccount = 'analyst' | 'driver' | 'admin';
export type TargetEnv = 'preview' | 'dev' | 'staging' | 'prod';

const FRONTEND_DEFAULTS: Record<TargetEnv, string> = {
  preview: 'https://green-sentinel.vercel.app',
  dev: 'https://green-sentinel-dev.vercel.app',
  staging: 'https://green-sentinel-staging.vercel.app',
  prod: 'https://green-sentinel.vercel.app',
};

const BACKEND_DEFAULTS: Record<TargetEnv, string> = {
  preview: 'https://greensentinel-backend-production.up.railway.app',
  dev: 'https://greensentinel-backend-dev.up.railway.app',
  staging: 'https://greensentinel-backend-staging.up.railway.app',
  prod: 'https://greensentinel-backend-production.up.railway.app',
};

export function targetEnv(): TargetEnv {
  const raw = (process.env.E2E_TARGET_ENV || 'preview').toLowerCase();
  if (raw === 'production') return 'prod';
  if (raw === 'preview' || raw === 'dev' || raw === 'staging' || raw === 'prod') return raw;
  throw new Error(`E2E_TARGET_ENV must be preview|dev|staging|prod, got ${process.env.E2E_TARGET_ENV}`);
}

export function frontendURL(): string {
  return process.env.AUTH_E2E_FRONTEND_URL || FRONTEND_DEFAULTS[targetEnv()];
}

export function backendURL(): string {
  return process.env.AUTH_E2E_BACKEND_URL || BACKEND_DEFAULTS[targetEnv()];
}

/** Role home pages that every role is authorized to render (with Clerk session). */
export function roleHomePage(role: RoleAccount): string {
  return role === 'driver' ? '/driver' : '/workplace';
}

export function roleCredentials(role: RoleAccount): { email: string; password: string } {
  const prefix = `E2E_${role.toUpperCase()}`;
  const email = process.env[`${prefix}_EMAIL`];
  const password = process.env[`${prefix}_PASSWORD`];
  if (!email || !password) {
    throw new Error(`${prefix}_EMAIL and ${prefix}_PASSWORD are required for real-account E2E`);
  }
  return { email, password };
}

export function requireRealAccountE2E() {
  if (process.env.RUN_REAL_ACCOUNT_E2E !== 'true') {
    // eslint-disable-next-line playwright/no-skipped-test
    expect(true).toBe(true);
    throw new Error('skip: opt in with RUN_REAL_ACCOUNT_E2E=true');
  }
}

/** Real Clerk UI login with real clicks. No tickets, no fixtures, no page.route mocks. */
export async function signInWithRole(page: Page, role: RoleAccount): Promise<void> {
  const { email, password } = roleCredentials(role);
  await gotoWithNetworkRetry(page, '/sign-in');

  const identifier = page.locator(IDENTIFIER_INPUT_SELECTOR);
  try {
    await expect(identifier).toBeVisible({ timeout: 20_000 });
  } catch {
    // Clerk can finish navigation before its cold-start UI mounts on hosted
    // previews. Reload once; a persistent missing form still fails the test.
    await gotoWithNetworkRetry(page, '/sign-in');
    await expect(identifier).toBeVisible({ timeout: 30_000 });
  }
  await identifier.click();
  await identifier.fill(email);

  const passwordInput = page.locator(PASSWORD_INPUT_SELECTOR);
  const passwordReady = (await passwordInput.isVisible().catch(() => false))
    && (await passwordInput.isEnabled().catch(() => false));
  const identifierSubmit = page.locator(CREDENTIAL_FORM_SELECTOR).getByRole('button', { name: /^Continue$/i });
  if (!passwordReady) {
    await expect(identifierSubmit.first()).toBeVisible({ timeout: 30_000 });
    await expect(identifierSubmit.first()).toBeEnabled({ timeout: 30_000 });
    await identifierSubmit.first().click();
  }

  try {
    await expect(passwordInput).toBeVisible({ timeout: 15_000 });
  } catch {
    // The submit can land before Clerk hydrates the form handler (slow/cold
    // runners): retry the click once before giving up.
    await identifierSubmit.first().click().catch(() => undefined);
    try {
      await expect(passwordInput).toBeVisible({ timeout: 15_000 });
    } catch {
      const alerts = await page.getByRole('alert').allTextContents().catch(() => [] as string[]);
      const clipped = alerts.join(' | ').slice(0, 200);
      throw new Error(
        `Password form did not appear after identifier submit${clipped ? `: ${clipped}` : ''}`,
      );
    }
  }
  await expect(passwordInput).toBeEnabled({ timeout: 30_000 });
  await passwordInput.click();
  await passwordInput.fill(password);

  // Scope the click to the credential form. A broad /continue/i locator can
  // select Clerk's "Continue with Google" OAuth button and leave this test
  // waiting on a password form that will never appear.
  const passwordSubmit = page.locator(PASSWORD_FORM_SELECTOR).getByRole('button', { name: /^(Continue|Sign in)$/i });
  await expect(passwordSubmit.first()).toBeVisible({ timeout: 30_000 });
  await expect(passwordSubmit.first()).toBeEnabled({ timeout: 30_000 });
  await passwordSubmit.first().click();

  // Optional Clerk organization picker: take the first org when prompted.
  const orgPrompt = page.getByText(/select.*organization|choose.*organization/i);
  if (await orgPrompt.count().catch(() => 0)) {
    const firstOrg = page.getByRole('button').first();
    await firstOrg.click().catch(() => undefined);
  }

  try {
    await waitForCredentialRedirect(page, 30_000);
  } catch (error) {
    // Clerk occasionally accepts the click before its first-factor handler is
    // ready and leaves the password form active without showing an error.
    const retryable = /"signInStatus":"needs_first_factor"/.test(String(error))
      && await passwordInput.isVisible().catch(() => false)
      && await passwordInput.isEnabled().catch(() => false);
    if (!retryable) throw error;
    await passwordInput.fill(password);
    await expect(passwordSubmit.first()).toBeEnabled({ timeout: 30_000 });
    await passwordSubmit.first().click();
    await waitForCredentialRedirect(page, 30_000);
  }
  // Confirm Clerk has committed the new browser session before a protected
  // navigation. Reloading immediately after the redirect can race Clerk's
  // cookie/session hydration and make middleware return a bare auth error.
  await waitForSessionToken(page);
  // Land on a page this role is authorized to render. Post-login landing
  // (e.g. /workplace) returns a bare 403 for unauthorized roles, which has
  // no Clerk session to hydrate or read tokens from.
  await gotoWithNetworkRetry(page, roleHomePage(role));
  await waitForSessionToken(page);
}

/** Reload-tolerant navigation: self-hosted runners show transient egress
 * blips (ERR_NETWORK_CHANGED). Retries once; persistent failures throw. */
export async function gotoWithNetworkRetry(page: Page, url: string): Promise<void> {
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
  } catch (error) {
    if (!/ERR_NETWORK_CHANGED|failed to fetch|networkerror/i.test(String(error))) throw error;
    await page.waitForTimeout(2_000);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
  }
}

/** Redirects and reloads can finish before Clerk hydrates the active session. */
async function waitForSessionToken(page: Page): Promise<string> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const token = await page.evaluate(async () => {
      const clerk = (window as unknown as {
        Clerk?: { loaded?: boolean; session?: { getToken(): Promise<string | null> } | null };
      }).Clerk;
      if (!clerk?.loaded || !clerk.session) return null;
      return clerk.session.getToken();
    });
    if (typeof token === 'string' && token.length > 0) return token;
    await page.waitForTimeout(100);
  }
  const state = await page.evaluate(() => {
    const clerk = (window as unknown as {
      Clerk?: { loaded?: boolean; session?: unknown };
    }).Clerk;
    return {
      pathname: window.location.pathname,
      clerkLoaded: Boolean(clerk?.loaded),
      sessionActive: Boolean(clerk?.session),
    };
  }).catch(() => ({ diagnosticUnavailable: true }));
  throw new Error(`Clerk session readiness timeout: ${JSON.stringify(state)}`);
}

/** Authenticated GET against the real backend using the live Clerk session token. */
export async function realApiStatus(page: Page, path: string): Promise<number> {
  const token = await waitForSessionToken(page);
  // One retry on transport failure: self-hosted runners show transient
  // egress blips (ERR_NETWORK_CHANGED). A down backend fails twice identically.
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await page.evaluate(async ({ backend, apiPath, token }: { backend: string; apiPath: string; token: string }) => {
        const response = await fetch(`${backend}${apiPath}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        return response.status;
      }, { backend: backendURL(), apiPath: path, token });
    } catch (error) {
      lastError = error;
      // evaluate errors arrive serialized; match transport failures by text.
      if (!/failed to fetch|load failed|networkerror|ERR_NETWORK_CHANGED/i.test(String(error))) {
        throw error;
      }
      await page.waitForTimeout(2_000);
    }
  }
  throw lastError;
}

/** Resolve a real available case by backend category without depending on the
 * queue label, which intentionally hides AI classification before review. */
export async function realAvailableCaseIdByCategory(page: Page, categories: string[]): Promise<string | null> {
  const token = await waitForSessionToken(page);
  return page.evaluate(async ({ backend, categories, token }) => {
    const response = await fetch(`${backend}/api/v1/cases?availability=available&limit=200`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(`Available case lookup failed with HTTP ${response.status}`);
    const body = await response.json() as {
      items?: Array<{ id?: string; category?: string | null }>;
    };
    const accepted = new Set(categories.map(value => value.toLowerCase()));
    return body.items?.find(item => item.category && accepted.has(item.category.toLowerCase()))?.id ?? null;
  }, { backend: backendURL(), categories, token });
}
