/** GSM workflow roles (ADR-031): read-only case access + one approval step each. Mirrors src/services/case_workflow.py. */
export const WORKFLOW_AWAITING_STATUS: Record<string, string> = {
  reviewer: 'report_issued',
  ops_director: 'need_ops_dir_approved',
  marketplace_director: 'need_mkp_dir_approved',
};

const ANALYST_ROLES = ['analyst', 'fraud_analyst', 'senior_analyst', 'admin'];

/** Status this principal's queue defaults to; null for analysts/admins (or unknown roles). */
export function awaitingStatusFor(roles: readonly string[] | string | null | undefined): string | null {
  const set = new Set((typeof roles === 'string' ? [roles] : roles ?? []).map(r => String(r).trim().toLowerCase()));
  if (ANALYST_ROLES.some(r => set.has(r))) return null;
  for (const [role, status] of Object.entries(WORKFLOW_AWAITING_STATUS)) if (set.has(role)) return status;
  return null;
}
