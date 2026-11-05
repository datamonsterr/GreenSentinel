/** Authoritative HTTP inputs only; the production cockpit owns mask/reveal/delta rendering. */
import type { Page } from './support/playwright';
import type { PrecedentSimilarityMatch } from '../../../src/webapp/types/schemas';

export const STAGED_CASE_ID = '23600000-0000-4000-8000-000000000003';
export const STAGED_ANALYST_ID = 'analyst-e2e';
export const STAGED_JUDGMENT_ID = '23600000-0000-4000-8000-000000000001';
export const STAGED_SUMMARY = 'Observed stationary duration is 240s; passenger cancelled.';
export const STAGED_PRECEDENT = 'Traffic corroboration precedent 236';
export const STAGED_CONVERSATION = 'Traffic is slowing the trip; please check the road.';

interface JudgmentRecord {
  id: string;
  case_id: string;
  analyst_id: string;
  judgment: string;
  note: string | null;
  created_at: string;
}

export async function installStagedAdjudicationFixture(page: Page, initiallyCommitted = false) {
  const state = {
    claimed: false,
    judgment: initiallyCommitted ? {
      id: STAGED_JUDGMENT_ID, case_id: STAGED_CASE_ID, analyst_id: STAGED_ANALYST_ID,
      judgment: 'Nghi oan-bất khả kháng', note: null, created_at: '2026-10-14T01:00:00Z',
    } as JudgmentRecord : null,
    finalDecision: null as Record<string, unknown> | null,
    preliminaryRequests: [] as Record<string, unknown>[],
    adjudicationRequests: [] as Record<string, unknown>[],
  };
  const item = () => ({
    id: STAGED_CASE_ID, status: state.finalDecision ? 'resolved' : 'ready',
    version: state.finalDecision ? 4 : 3, priority: 'P1', priority_score: 80,
    category: 'intentional_dic', confidence: 0.92,
    driver_name: 'Analyst gate fixture driver', vehicle_plate: '29A-23600',
  });
  const brief = {
    case_id: STAGED_CASE_ID, generated_at: '2026-10-14T01:00:00Z',
    abnormalities: [], abnormality_count: 1, evidence_sources: ['feature_sets.stationary_duration_s'],
    telemetry_summary: { sample_count: 2, stationary_duration_s: 240 }, summary_text: STAGED_SUMMARY,
  };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postDataJSON() as Record<string, unknown> | null;
    if (path === '/api/v1/me') return route.fulfill({ json: {
      id: STAGED_ANALYST_ID, display_name: 'Independent analyst', roles: ['analyst'],
    } });
    if (path === '/api/v1/cases' || path === '/api/v1/cases/history') {
      const items = path.endsWith('/history') ? (state.finalDecision ? [item()] : [])
        : (state.finalDecision ? [] : [item()]);
      return route.fulfill({ json: { items, total: items.length, limit: 50, offset: 0 } });
    }
    if (path === `/api/v1/cases/${STAGED_CASE_ID}`) return route.fulfill({ json: {
      case: item(), trip: {
        pickup_address: 'Pickup source 236', dropoff_address: 'Destination source 236',
        pickup: { coordinates: [105.82, 21.03] }, dropoff: { coordinates: [105.8, 21.01] },
      },
      telemetry_samples: [
        { recorded_at: '2026-10-14T01:00:00Z', position: { coordinates: [105.82, 21.03] }, speed_mps: 0 },
        { recorded_at: '2026-10-14T01:04:00Z', position: { coordinates: [105.82, 21.03] }, speed_mps: 0 },
      ],
      features: { stationary_duration_s: 240, davi_score: 0.85 },
      assessment: { category: 'intentional_dic', confidence: 0.92, reason_codes: ['STATIONARY_STALL'],
        detection_reason: 'AI finding 236', recommended_action: 'APPROVE' },
      conversation: [{ role: 'driver', text: STAGED_CONVERSATION, occurred_at: '2026-10-14T01:02:00Z' }],
      forensic_brief: brief, guardrails: { is_blocking: false, blocking_guardrail: false },
      route_geometry: null, candidate_routes: [], timeline_milestones: [], missingness_alerts: [],
      active_lease: state.claimed ? { analyst_id: STAGED_ANALYST_ID, expires_at: '2099-10-14T01:10:00Z' } : null,
      preliminary_judgment: state.judgment, adjudication: state.finalDecision,
    } });
    if (path.endsWith('/claim')) {
      state.claimed = true;
      return route.fulfill({ json: { case_id: STAGED_CASE_ID, analyst_id: STAGED_ANALYST_ID,
        lease_expires_at: '2099-10-14T01:10:00Z', status: 'claimed' } });
    }
    if (path.endsWith('/preliminary-assessment')) {
      state.preliminaryRequests.push(body!);
      if (state.judgment) return route.fulfill({ status: 409, json: { detail: 'Judgment already committed' } });
      state.judgment = {
        id: STAGED_JUDGMENT_ID, case_id: STAGED_CASE_ID, analyst_id: STAGED_ANALYST_ID,
        judgment: body?.judgment as string, note: (body?.note ?? null) as string | null,
        created_at: '2026-10-14T01:00:00Z',
      };
      return route.fulfill({ json: state.judgment });
    }
    if (path.endsWith('/adjudicate')) {
      state.adjudicationRequests.push(body!);
      state.finalDecision = {
        case_id: STAGED_CASE_ID, outcome: 'DISAGREE', analyst_id: STAGED_ANALYST_ID,
        rationale: body?.rationale, preliminary_judgment_id: STAGED_JUDGMENT_ID,
        preliminary_judgment: state.judgment,
        ai_suggestion: { category: 'intentional_dic', confidence: 0.92, recommended_action: 'AGREE' },
        delta: 'mismatch',
      };
      return route.fulfill({ json: { ...state.finalDecision, status: 'adjudicated', new_version: 4,
        adjudicated_at: '2026-10-14T01:05:00Z' } });
    }
    if (path.endsWith('/forensic-brief')) return route.fulfill({ json: brief });
    if (path.endsWith('/agent-session')) return route.fulfill({ json: { session_id: 'session-236', messages: [] } });
    if (path.endsWith('/dispute-dossier')) return route.fulfill({ json: {
      case_id: STAGED_CASE_ID, dispute_status: 'open', driver_id: 'driver-236',
      transcripts: [], recommended_action: 'AGREE',
      matched_precedent: { precedent_id: 'precedent-236', title: STAGED_PRECEDENT,
        similarity_score: 0.94, model_used: 'jev', precedent_verdict: 'exonerated',
        matching_factors: ['Traffic corroboration'], recommended_procedure: [],
        confidence_rationale: 'Independent traffic corroboration required.' } satisfies PrecedentSimilarityMatch,
    } });
    if (path.endsWith('/workflow-trace')) return route.fulfill({ json: null });
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: ': offline fixture\n\n' });
    return route.fulfill({ status: 404, json: { detail: `Unconfigured test transport: ${path}` } });
  });
  return state;
}
