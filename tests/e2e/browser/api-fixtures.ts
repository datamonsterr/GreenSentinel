import type { Page } from './support/playwright';

const CASE_ID = '11111111-1111-4111-8111-111111111111';

export interface ApiFixtureOptions {
  role?: string;
  isLockedByOther?: boolean;
  isUnclaimed?: boolean;
  missingTelemetry?: boolean;
  isBlockingGuardrail?: boolean;
  assessment?: { category: string; confidence: number; reason_codes: string[] };
  driverName?: string;
}

export async function installApiFixtures(page: Page, options: ApiFixtureOptions = {}) {
  const userRole = options.role ?? 'analyst';
  const preliminaryJudgment = {
    id: `judgment-${CASE_ID}`, case_id: CASE_ID, analyst_id: 'analyst-e2e',
    judgment: 'Nghi ngờ vi phạm', note: null, created_at: '2026-10-14T01:00:00Z',
  };
  let activeLease = options.isLockedByOther
    ? { analyst_id: 'other-analyst-id', expires_at: new Date(Date.now() + 86400000).toISOString() }
    : null;
  const telemetrySamples = options.missingTelemetry
    ? []
    : [{ recorded_at: '2026-09-25T08:00:00Z', position: { coordinates: [105.82, 21.03] } }];
  const features = options.missingTelemetry ? {} : { stall_duration_s: 240, davi_score: 0.85 };
  const guardrails = {
    is_blocking: Boolean(options.isBlockingGuardrail),
    blocking_reasons: options.isBlockingGuardrail ? ['Evidence incomplete: Telemetry gap > 180s'] : [],
  };
  const motivationAssessment = {
    economic_incentive_reward: 25000,
    intent_profile: 'possible_intentional_exploit',
    natural_vietnamese_narrative:
      'Dữ liệu cho thấy tài xế có thể kéo dài hành trình để hưởng thêm 25.000 đồng; cần đối chiếu thêm lời giải trình trước khi kết luận.',
  };
  const forensicBrief = {
    case_id: CASE_ID,
    generated_at: '2026-09-25T08:03:00Z',
    abnormality_count: 1,
    abnormalities: [{ code: 'STATIONARY_DURATION', category: 'feature', severity: 'warning', label: 'Stationary duration', observed_value: '240s', description: 'Observed stationary duration is 240s.', evidence_source: 'feature_sets.stationary_duration_s' }],
    summary_text: 'Forensic Brief (1 observed abnormality): [Stationary duration: 240s] Observed stationary duration is 240s.',
    evidence_sources: ['feature_sets.stationary_duration_s'],
    motivation_assessment: motivationAssessment,
  };

  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/me') return route.fulfill({ json: { id: 'analyst-e2e', display_name: 'E2E Analyst', roles: [userRole] } });
    if (path === '/api/v1/cases' && request.method() === 'GET') return route.fulfill({ json: { items: [{ id: CASE_ID, status: 'OPEN', priority: 'P1', priority_score: 0.8, category: 'route_integrity', confidence: 0.92, version: 3, driver_name: options.driverName ?? 'Nguyen Hung', vehicle_plate: '29A-12345', district: 'Ba Dinh', sla_countdown_s: 240, preliminary_judgment: preliminaryJudgment }], total: 1, limit: 50, offset: 0 } });
    if (path === `/api/v1/cases/${CASE_ID}`) return route.fulfill({ json: { case: { id: CASE_ID, status: 'OPEN', priority: 'P1', priority_score: 0.8, category: 'route_integrity', confidence: 0.92, version: 3, driver_name: options.driverName ?? 'Nguyen Hung', vehicle_plate: '29A-12345', district: 'Ba Dinh', sla_countdown_s: 240 }, trip: { pickup_address: '12 Le Loi, Ba Dinh', dropoff_address: '88 Tran Duy Hung, Cau Giay', pickup: { coordinates: [105.82, 21.03] }, dropoff: { coordinates: [105.8, 21.01] } }, telemetry_samples: telemetrySamples, features, assessment: options.assessment, conversation: [{ role: 'driver', text: 'Traffic is slowing the trip.', occurred_at: '2026-09-25T08:02:00Z' }], forensic_brief: forensicBrief, route_geometry: null, candidate_routes: [], timeline_milestones: [], missingness_alerts: [], guardrails, active_lease: activeLease, preliminary_judgment: preliminaryJudgment, adjudication: null } });
    // Without this the stepper's workflow fetch falls through to a non-existent backend, fails, and renders the workflow-error paragraph.
    if (path === `/api/v1/cases/${CASE_ID}/workflow` && request.method() === 'GET') return route.fulfill({ json: { status: 'OPEN', closed: false, steps: [
      { key: 'review', label: 'Analyst review', actor_role: 'ANALYST', state: 'current', completed_at: null },
      { key: 'approve-ops', label: 'Ops director approval', actor_role: 'OPS_DIR', state: 'pending', completed_at: null },
    ], next: null, actions: [] } });
    if (path === `/api/v1/cases/${CASE_ID}/motivation` && request.method() === 'GET') return route.fulfill({ json: { persisted: false, assessment: { id: null, version: 0, motive_category: 'subsidy_surge', amount_at_stake_vnd: 25000, confidence: 0.65, rationale: 'Có lợi ích tăng thêm; cần đối chiếu.', source: 'rule', status: 'draft', signals: [{ code: 'surge_capture', value: 25000, unit: 'VND' }] } } });
    if (path.endsWith('/forensic-brief')) return route.fulfill({ json: forensicBrief });
    if (path.endsWith('/policy')) return route.fulfill({ json: { case_id: CASE_ID, suspected_category: 'route_integrity', policy_version: '2026.1', action_matrix: {}, applicable_action_rule: {}, clauses: [], related_policies: [], source: 'in_memory_fallback' } });
    if (path.endsWith('/agent-session')) return route.fulfill({ json: { session_id: 'session-e2e', messages: [] } });
    if (path.endsWith('/claim')) {
      const leaseExpiry = new Date(Date.now() + 86400000).toISOString();
      activeLease = { analyst_id: 'analyst-e2e', expires_at: leaseExpiry };
      return route.fulfill({ json: { case_id: CASE_ID, analyst_id: 'analyst-e2e', lease_expires_at: leaseExpiry, status: 'claimed' } });
    }
    if (path.endsWith('/release')) {
      activeLease = null;
      return route.fulfill({ json: { case_id: CASE_ID, status: 'released' } });
    }
    if (path.endsWith('/stream') && request.method() === 'GET') return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (path.endsWith('/dispute-dossier') || path.endsWith('/workflow-trace')) return route.fulfill({ json: null });
    if (path.endsWith('/driver-scorecard')) return route.fulfill({ status: 503, json: { detail: 'Driver history unavailable in fixture' } });
    if (path.endsWith('/delegate-inquiry')) return route.fulfill({ json: { case_id: CASE_ID, status: 'queued' } });
    if (path.endsWith('/actions')) return route.fulfill({ json: { case_id: CASE_ID, action_type: 'REQUEST_EVIDENCE', status: 'recorded', recorded_at: '2026-09-25T08:05:00Z', new_case_status: 'OPEN' } });
    if (path.endsWith('/adjudicate')) {
      let body: any = {};
      try { body = JSON.parse(request.postData() || '{}'); } catch {}
      const outcome = body.outcome || 'AGREE';
      return route.fulfill({
        json: {
          case_id: CASE_ID,
          outcome,
          status: 'adjudicated',
          new_version: 4,
          adjudicated_at: '2026-09-25T08:10:00Z',
          analyst_id: body.analyst_id || 'analyst-e2e',
          rationale: body.rationale || 'Default valid rationale',
        },
      });
    }
    if (path.endsWith('/agent-context')) {
      if (request.method() === 'DELETE') {
        return route.fulfill({ json: { deleted_turns: 1, deleted_messages: 2 } });
      }
      return route.fulfill({
        json: {
          prompt_tokens: 1500,
          completion_tokens: 300,
          total_tokens: 1800,
          context_window: 10000,
          breakdown: {
            system: 400,
            dossier: 600,
            history: 300,
            tool_results: 300,
            query: 200,
          },
          turn_count: 2,
        },
      });
    }
    if (path === '/api/v1/policy/chat/stream') {
      let deltaText = 'Evidence reviewed.';
      let citations: Array<{ id: string; source: string; section: string; content: string; score: number }> = [];
      let toolEvents = [
        'event: tool.start\n',
        'data: {"tool_call_id":"c-1","tool_name":"get_case_detail"}\n\n',
        'event: tool.end\n',
        'data: {"tool_call_id":"c-1","status":"completed"}\n\n',
      ];
      const suggestions = [{ label: 'Kiểm tra quy định', prompt: 'Kiểm tra quy chế Điều 5.2' }];
      try {
        const postData = JSON.parse(request.postData() || '{}');
        if (postData.attachments && postData.attachments.length > 0) {
          deltaText = `Đã nhận ${postData.attachments.length} ảnh đính kèm: ${postData.attachments[0].name}.`;
        } else if (postData.query === 'Tóm tắt động cơ và hành vi của tài xế') {
          deltaText = `${motivationAssessment.natural_vietnamese_narrative} Lợi ích tăng thêm ước tính: 25.000 ₫. [1](policy://c1)`;
          citations = [{ id: 'c1', source: 'Quy chế dịch vụ 2026', section: 'Điều 5.2', content: 'Quy định về dừng đón trả khách và lộ trình tối ưu.', score: 0.95 }];
        } else if (postData.query === 'Kiểm tra tình trạng kẹt xe và sự cố giao thông trên đoạn đường này') {
          toolEvents = [
            'event: tool.start\n',
            'data: {"tool_call_id":"traffic-history","tool_name":"fetch_corridor_historical_traffic"}\n\n',
            'event: tool.start\n',
            'data: {"tool_call_id":"traffic-incidents","tool_name":"query_traffic_incident_feed"}\n\n',
            'event: tool.end\n',
            'data: {"tool_call_id":"traffic-history","status":"completed"}\n\n',
            'event: tool.end\n',
            'data: {"tool_call_id":"traffic-incidents","status":"completed"}\n\n',
          ];
          deltaText = 'Dữ liệu lịch sử cho thấy hành lang ùn tắc và có sự cố phù hợp với thời điểm lệch tuyến. Đây là tình huống có thể được xem xét theo Điều 12.2; thẩm định viên phải đối chiếu GPS và quyết định, không tự động kết luận gian lận.';
        } else if (postData.query && postData.query !== 'Review this case') {
          deltaText = `Reply to ${postData.query}`;
        }
      } catch {}

      const sseBody = [
        'event: status.thinking\n',
        'data: {"schema_version":"1.1","label":"Đang phân tích yêu cầu"}\n\n',
        ...toolEvents,
        citations.length > 0 ? `event: citation\ndata: ${JSON.stringify(citations[0])}\n\n` : '',
        'event: text.delta\n',
        `data: {"delta":${JSON.stringify(deltaText)}}\n\n`,
        'event: suggestions\n',
        `data: ${JSON.stringify({ items: suggestions })}\n\n`,
        'event: usage\n',
        'data: {"prompt_tokens":1500,"completion_tokens":300,"total_tokens":1800,"context_window":10000,"breakdown":{"system":400,"dossier":600,"history":300,"tool_results":300,"query":200}}\n\n',
        'event: run.completed\n',
        'data: {"status":"completed"}\n\n',
      ].join('');

      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sseBody,
      });
    }
    if (path.endsWith('/dispute-dossier')) {
      return route.fulfill({
        json: {
          case_id: CASE_ID,
          dispute_status: 'open',
          driver_id: 'driver-e2e',
          transcripts: [],
          recommended_action: 'AGREE',
        },
      });
    }
    if (path.includes('/scorecard') || path.endsWith('/driver-scorecard')) {
      return route.fulfill({
        json: {
          driver_id: 'drv-e2e',
          violation_ratio_90d: 4.2,
          fined_ratio: 50.0,
          repeat_offense_risk_score: 75,
          benchmark_violation_ratio: 5.0,
          tenure_months: 18,
          past_incidents: [],
        },
      });
    }
    return route.continue();
  });
}
