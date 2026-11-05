export interface ResolvableCase {
  status?: string | null;
  dispute_status?: string | null;
}

const RESOLVED_DISPUTE_STATUSES = new Set(['resolved', 'upheld', 'auto_dismissed', 'dismissed']);

/**
 * Single source of truth for "is this case resolved / closed out" across
 * card styling (pill color, deadline hint suppression) and the Cases tab
 * Open / Resolved segmentation. Keep both call sites on this predicate so
 * they never silently drift.
 */
export function isResolvedCase(item: ResolvableCase): boolean {
  if (item.status === 'closed') return true;
  if (item.dispute_status && RESOLVED_DISPUTE_STATUSES.has(item.dispute_status)) return true;
  return false;
}
