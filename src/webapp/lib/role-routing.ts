/** Canonical role routing mirror (S4-ENTRY #296, ADR-025). Keep in sync with src/services/role_routing.py. */
export const ORGANIZATION_ROUTE = '/organization';
export const WORKSPACE_ROUTE = '/workspace';
export const DRIVER_ROUTE = '/driver';

const ANALYST_ROLES = new Set(['analyst', 'fraud_analyst', 'senior_analyst']);

export function resolveInitialRoute(roles: readonly string[] | null | undefined): string {
  const normalized = new Set(
    (roles ?? []).map((r) => String(r).trim().toLowerCase()).filter(Boolean),
  );
  if (normalized.has('admin')) return ORGANIZATION_ROUTE;
  if (normalized.has('driver') && ![...normalized].some((r) => ANALYST_ROLES.has(r))) {
    return DRIVER_ROUTE;
  }
  return WORKSPACE_ROUTE;
}

export function primaryRoleFor(roles: readonly string[] | null | undefined): string {
  const normalized = new Set(
    (roles ?? []).map((r) => String(r).trim().toLowerCase()).filter(Boolean),
  );
  if (normalized.has('admin')) return 'admin';
  if (normalized.has('driver') && ![...normalized].some((r) => ANALYST_ROLES.has(r))) {
    return 'driver';
  }
  return 'analyst';
}
