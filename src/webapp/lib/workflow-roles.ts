/** GSM workflow roles (ADR-031). Mirrors src/services/case_workflow.py. Admin acts as the MKP director (last step). */
export const WORKFLOW_AWAITING_STATUS: Record<string, string> = {
  reviewer: 'report_issued',
  ops_director: 'need_ops_dir_approved',
  marketplace_director: 'need_mkp_dir_approved',
};
export const ADMIN_AWAITING_STATUS = 'need_mkp_dir_approved';

const ANALYST_ROLES = ['analyst', 'fraud_analyst', 'senior_analyst'];
const norm = (roles: readonly string[] | string | null | undefined) =>
  new Set((typeof roles === 'string' ? [roles] : roles ?? []).map(r => String(r).trim().toLowerCase()));

/** Step the caller's "Awaiting me" queue shows; null for analysts / unknown roles. */
export function awaitingStatusFor(roles: readonly string[] | string | null | undefined): string | null {
  const set = norm(roles);
  if (set.has('admin')) return ADMIN_AWAITING_STATUS;
  if (ANALYST_ROLES.some(r => set.has(r))) return null;
  for (const [role, status] of Object.entries(WORKFLOW_AWAITING_STATUS)) if (set.has(role)) return status;
  return null;
}

/** Workflow role without analyst/admin powers: read-only workspace (no claim, judgment, relay, copilot). */
export function isWorkflowOnly(roles: readonly string[] | string | null | undefined): boolean {
  const set = norm(roles);
  return !set.has('admin') && !ANALYST_ROLES.some(r => set.has(r)) && Object.keys(WORKFLOW_AWAITING_STATUS).some(r => set.has(r));
}
