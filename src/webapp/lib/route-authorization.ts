/** Server-side route policy. Application roles come exclusively from the API database. */
import { isolatedGisBuild } from './isolated-gis-build';
export type ProtectedArea = 'driver' | 'workplace' | 'workspace' | 'organization' | 'test';

export function localTestAuthentication(): boolean {
  return (process.env.NODE_ENV !== 'production' || isolatedGisBuild())
    && process.env.APP_ENV === 'test'
    && process.env.TEST_AUTH_ENABLED === 'true';
}

export function protectedArea(pathname: string): ProtectedArea | null {
  if (/^\/test(?:\/|$)/.test(pathname)) return 'test';
  if (/^\/driver(?:\/|$)/.test(pathname)) return 'driver';
  if (/^\/organization(?:\/|$)/.test(pathname)) return 'organization';
  if (/^\/workspace(?:\/|$)/.test(pathname)) return 'workspace';
  if (/^\/(?:workplace|dashboard|analytics|profile)(?:\/|$)/.test(pathname)) return 'workplace';
  return null;
}

export function resolveBackendUrl(requestUrlOrHost?: string): string {
  const envUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL;
  if (envUrl && !envUrl.includes('[SENSITIVE]') && !envUrl.includes('placeholder')) {
    if (envUrl.startsWith('http://') || envUrl.startsWith('https://')) {
      return envUrl.replace(/\/+$/, '');
    }
  }
  const host = requestUrlOrHost
    ? (requestUrlOrHost.includes('://') ? new URL(requestUrlOrHost).hostname : requestUrlOrHost)
    : '';
  if (host) {
    if (host.includes('localhost') || host.includes('127.0.0.1')) {
      return 'http://localhost:8000';
    }
    if (host.includes('staging')) {
      return 'https://p063-backend-staging.up.railway.app';
    }
    if (
      host.includes('p-063-dev')
      || host.includes('dev.p-063')
      || host.includes('dev-p-063')
      || host.includes('.vercel.app')
    ) {
      return 'https://p063-backend-dev.up.railway.app';
    }
  }
  if (process.env.VERCEL_ENV === 'production') {
    return 'https://p063-backend-production.up.railway.app';
  }
  return 'https://p063-backend-dev.up.railway.app';
}

export async function authorizedDriverCase(token: string, caseId: string, requestUrlOrHost?: string): Promise<boolean> {
  return (await principalRequest(token, `/api/v1/driver/cases/${encodeURIComponent(caseId)}/dispute`, requestUrlOrHost)).ok;
}

async function principalRequest(token: string, path: string, requestUrlOrHost?: string): Promise<Response> {
  const backend = resolveBackendUrl(requestUrlOrHost);
  return fetch(`${backend}${path}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
    signal: AbortSignal.timeout(10_000),
  });
}

/** Backend denial for unknown identities: no principal row and no usable
 * Clerk org claim (S4-CONTRACT #291). Safe to match: it names no user. */
export const UNPROVISIONED_DETAIL = 'Clerk user has no active assigned role';

export type AreaDecision =
  | 'allow'
  | 'unprovisioned'
  | 'forbidden'
  | 'unreachable'
  | { kind: 'wrong_role'; roles: string[] };

function roleAllows(principal: { organization_id?: unknown; roles?: unknown }, area: ProtectedArea): boolean {
  if (area === 'test') {
    return typeof principal.organization_id === 'string' && principal.organization_id.trim().length > 0;
  }
  if (!principal.organization_id || !Array.isArray(principal.roles)) {
    return false;
  }
  if (area === 'driver') {
    return principal.roles.includes('admin') || principal.roles.includes('driver');
  }
  if (area === 'organization') {
    return principal.roles.includes('admin');
  }
  return principal.roles.some((role: string) => ['analyst', 'fraud_analyst', 'admin'].includes(role));
}

export async function decideArea(token: string, area: ProtectedArea, requestUrlOrHost?: string): Promise<AreaDecision> {
  let response: Response;
  try {
    response = await principalRequest(token, '/api/v1/account/settings', requestUrlOrHost);
  } catch {
    return 'unreachable';
  }
  if (!response.ok) {
    if (response.status === 403) {
      try {
        const body = await response.json();
        if (body?.detail === UNPROVISIONED_DETAIL) return 'unprovisioned';
      } catch {
        // A non-JSON denial still reports its HTTP status below.
      }
    }
    return 'forbidden';
  }
  const principal = await response.json();
  if (roleAllows(principal, area)) return 'allow';
  // Role mismatch (vs. backend denial / malformed principal): the identity
  // is known and provisioned, just lacks the role for this area. `test`
  // mismatches (missing org) stay a bare 'forbidden' (no role to report).
  if (area !== 'test' && principal?.organization_id && Array.isArray(principal.roles)) {
    return { kind: 'wrong_role', roles: principal.roles };
  }
  return 'forbidden';
}

export async function authorizedArea(token: string, area: ProtectedArea, requestUrlOrHost?: string): Promise<boolean> {
  const response = await principalRequest(token, '/api/v1/account/settings', requestUrlOrHost);
  if (!response.ok) {
    // Log only known public failure reasons; never echo arbitrary response data
    // or credentials from the authentication provider.
    const safeReasons = new Set([
      'Clerk verification is not configured',
      'Clerk verification unavailable',
      'Principal database unavailable',
      'Authorization database unavailable',
      UNPROVISIONED_DETAIL,
    ]);
    let reason = '';
    try {
      const body = await response.json();
      if (safeReasons.has(body?.detail)) reason = `: ${body.detail}`;
    } catch {
      // A non-JSON error still reports its HTTP status.
    }
    console.warn(`[route-authorization] Principal request failed with status ${response.status}${reason} from ${resolveBackendUrl(requestUrlOrHost)}`);
    return false;
  }
  const principal = await response.json();
  if (area === 'test') {
    return typeof principal?.organization_id === 'string' && principal.organization_id.trim().length > 0;
  }
  if (!principal.organization_id || !Array.isArray(principal.roles)) {
    console.warn('[route-authorization] Principal response missing organization_id or roles array', principal);
    return false;
  }
  return roleAllows(principal, area);
}
