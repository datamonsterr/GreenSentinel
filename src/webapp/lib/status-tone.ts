/** GSM tone chip classes (defined in globals.css). Use: <span className={`gs-tone ${statusTone('amber')}`}>. */
export type Tone = 'amber' | 'cyan' | 'purple' | 'green' | 'orange' | 'brown' | 'grey' | 'red' | 'blue';

export const statusTone = (tone: Tone): string => `t-${tone}`;

/** Case status → tone (analyst-facing statuses; unknown → grey). */
const CASE_STATUS_TONE: Record<string, Tone> = {
  pending: 'amber', open: 'amber', new: 'amber',
  in_review: 'cyan', reviewing: 'cyan', assigned: 'cyan',
  awaiting_driver: 'purple', awaiting_response: 'purple', escalated: 'orange',
  resolved: 'green', closed: 'green', confirmed: 'red', rejected: 'grey', dismissed: 'grey',
};
export const caseStatusTone = (status?: string | null): string =>
  statusTone(CASE_STATUS_TONE[(status ?? '').toLowerCase()] ?? 'grey');
