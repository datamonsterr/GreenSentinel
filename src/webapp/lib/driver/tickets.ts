import { isResolvedCase, type ResolvableCase } from './case-segments';

export type TicketPhase = 'open' | 'pending' | 'closed';
export type TicketFilter = 'all' | TicketPhase;

/** Steps shown on the ticket progress bar (0-based index of the current one). */
export const TICKET_STEP_COUNT = 4; // notified → explain → review → result

const PENDING_DISPUTE = new Set([
  'escalated',
  'in_dispute',
  'driver_disputed',
  'pending_review',
  'pending_analyst_review',
]);

export function getTicketPhase(item: ResolvableCase): TicketPhase {
  if (isResolvedCase(item)) return 'closed';
  if (
    (item.dispute_status && PENDING_DISPUTE.has(item.dispute_status)) ||
    item.status === 'investigating' ||
    item.status === 'in_review'
  ) {
    return 'pending';
  }
  return 'open';
}

/** 1-based current step: 2 = needs explanation, 3 = analyst reviewing, 4 = done. */
export function getTicketStep(item: ResolvableCase): number {
  const phase = getTicketPhase(item);
  return phase === 'closed' ? 4 : phase === 'pending' ? 3 : 2;
}

export function countByPhase(items: ResolvableCase[]): Record<TicketFilter, number> {
  const out: Record<TicketFilter, number> = { all: items.length, open: 0, pending: 0, closed: 0 };
  for (const it of items) out[getTicketPhase(it)] += 1;
  return out;
}
