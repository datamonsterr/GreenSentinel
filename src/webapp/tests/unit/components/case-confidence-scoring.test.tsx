import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import { FinalizationTab } from '@/components/adjudication/finalization-tab';
import * as api from '@/lib/api-client';
import { committedJudgment } from '../../fixtures/staged-adjudication';

vi.mock('@/lib/api-client', () => ({
  fetchCases: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  claimCase: vi.fn(),
  releaseCase: vi.fn(),
  adjudicateCase: vi.fn(),
  recordCaseAction: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
  streamPolicyChat: vi.fn(),
  getDisputeDossier: vi.fn().mockResolvedValue(null),
  getPrecedentRecommendations: vi.fn().mockResolvedValue([]),
  getCaseWorkflowTrace: vi.fn().mockResolvedValue(null),
  applyPrecedentProcedure: vi.fn().mockResolvedValue({}),
}));

const mockCaseItemWithConfidence = {
  preliminary_judgment: committedJudgment('case-jev-001', 'analyst-1'),
  id: 'case-jev-001',
  driver_name: 'Trần Văn Mạnh',
  vehicle_plate: '30F-123.45',
  priority: 'P1',
  priority_score: 92,
  status: 'ready',
  category: 'ERR-02',
  confidence: 0.92,
  version: 1,
  district: 'Ba Đình',
  sla_countdown_s: 180,
};

const mockDetailWithAssessment = {
  preliminary_judgment: mockCaseItemWithConfidence.preliminary_judgment,
  case: mockCaseItemWithConfidence,
  assessment: {
    id: 'assess-001',
    category: 'ERR-02',
    confidence: 0.92,
    score_semantics: 'high_anomaly',
    reason_codes: ['stationary_duration_over_180s', 'passenger_forced_cancellation'],
    forensic_brief: 'Forensic Brief — Ghi nhận thời gian dừng đỗ câu giờ 210s >= 180s.',
  },
  trip: {
    id: 'trip-jev-001',
    driver_name: 'Trần Văn Mạnh',
    vehicle_plate: '30F-123.45',
    vehicle_type: 'GreenCar (VF 8)',
    rating: 4.88,
    acceptance_rate: 94.0,
    cancellation_rate: 2.5,
    total_trips: 1200,
    driver_status: 'active',
    pickup_address: '54 Liễu Giai, Ba Đình',
    dropoff_address: 'Vincom Bà Triệu, Hai Bà Trưng',
    fare_amount_vnd: 85000,
    status: 'cancelled',
    match_type: 'auto',
  },
  conversation: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchCases).mockResolvedValue({
    items: [mockCaseItemWithConfidence],
    total: 1,
    limit: 50,
    offset: 0,
  });
  vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetailWithAssessment);
  vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: 'analyst-1', name: 'Analyst Test', role: 'analyst' });
  vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: 'session-1', messages: [] });
});
afterEach(() => cleanup());

describe('AI Anomaly Scoring & Error Type UI Display', () => {
  it('keeps AI score absent from the sidebar and overview before Finalization is opened', async () => {
    const { preliminary_judgment: _judgment, ...unjudged } = mockCaseItemWithConfidence;
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [unjudged], total: 1, limit: 50, offset: 0 } as any);
    render(<CockpitWorkspaceView />);
    await screen.findByText('Trần Văn Mạnh');
    expect(screen.queryByText(/ERR-02 \(92%\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI advice|classification|confidence/i)).not.toBeInTheDocument();
  });

  it('keeps AI category and confidence off the queue card after judgment', async () => {
    render(<CockpitWorkspaceView />);
    await screen.findByText('Trần Văn Mạnh');
    expect(screen.queryByText(/ERR-02 \(92%\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence|classification|ERR-02/i)).not.toBeInTheDocument();
  });

  it('reveals persisted classification and confidence only in Finalization', async () => {
    render(<FinalizationTab caseDetail={{ ...mockDetailWithAssessment, preliminary_judgment: committedJudgment('case-jev-001', 'analyst-1') } as any} isActive canWrite={false} busy={false} choice="" onChoice={() => {}} note="" onNote={() => {}} savingJudgment={false} onSaveJudgment={() => {}} rationale="" onRationale={() => {}} onDecision={() => {}} delta="mismatch" />);
    expect(screen.getByRole('region', { name: 'AI results' })).toBeInTheDocument();
    expect(screen.getByLabelText('AI advice: ERR-02, 92% confidence')).toHaveTextContent('ERR-02 (92%)');
    expect(screen.getByText(/stationary_duration_over_180s/)).toBeInTheDocument();
  });
  it.each([
    ['assessment fraction', 'ERR-ASSESS', 0.876, 'ERR-CASE', 71, 'ERR-ASSESS (88%)', 'bg-gs-amber-soft'],
    ['assessment percentage', 'ERR-ASSESS', 94, 'ERR-CASE', 71, 'ERR-ASSESS (94%)', 'bg-gs-green-soft'],
    ['assessment zero', 'ERR-ASSESS', 0, 'ERR-CASE', 71, 'ERR-ASSESS (0%)', 'bg-white'],
    ['case fallback', null, null, 'ERR-CASE', 0.73, 'ERR-CASE (73%)', 'bg-gs-amber-soft'],
    ['queue fallback', null, null, null, null, 'Unavailable', ''],
  ] as const)('preserves %s in gated Finalization', async (_name, category, confidence, caseCategory, caseConfidence, expected, color) => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...mockDetailWithAssessment,
      case: { ...mockCaseItemWithConfidence, category: caseCategory, confidence: caseConfidence },
      assessment: { ...mockDetailWithAssessment.assessment, category, confidence },
    });
    const detail = {
      ...mockDetailWithAssessment,
      preliminary_judgment: committedJudgment('case-jev-001', 'analyst-1'),
      case: { ...mockDetailWithAssessment.case, category: caseCategory, confidence: caseConfidence },
      assessment: { ...mockDetailWithAssessment.assessment, category, confidence },
    };
    render(<FinalizationTab caseDetail={detail as any} isActive canWrite={false} busy={false} choice="" onChoice={() => {}} note="" onNote={() => {}} savingJudgment={false} onSaveJudgment={() => {}} rationale="" onRationale={() => {}} onDecision={() => {}} delta="mismatch" />);
    const advice = screen.getByLabelText(/^AI advice:/);
    expect(advice).toHaveTextContent(expected);
    if (color) expect(advice).toBeInTheDocument();
  });

  it('omits absent confidence and signals without fabricating either', async () => {
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [{ ...mockCaseItemWithConfidence, confidence: null }], total: 1, limit: 50, offset: 0 });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...mockDetailWithAssessment,
      case: { ...mockCaseItemWithConfidence, confidence: null },
      assessment: { category: 'ERR-02', confidence: null, reason_codes: null },
    });
    render(<FinalizationTab caseDetail={{ ...mockDetailWithAssessment, preliminary_judgment: committedJudgment('case-jev-001', 'analyst-1'), case: { ...mockDetailWithAssessment.case, confidence: null }, assessment: { category: 'ERR-02', confidence: null, reason_codes: null } } as any} isActive canWrite={false} busy={false} choice="" onChoice={() => {}} note="" onNote={() => {}} savingJudgment={false} onSaveJudgment={() => {}} rationale="" onRationale={() => {}} onDecision={() => {}} delta="mismatch" />);
    const advice = screen.getByLabelText('AI advice: ERR-02');
    expect(advice).toHaveTextContent(/Classification: ERR-02/);
    expect(advice).toHaveAttribute('title', 'Classification');
    expect(screen.queryByRole('group', { name: 'Assessment signals' })).not.toBeInTheDocument();
  });

  it('retains only the first three complete reason codes in the header', async () => {
    const codes = ['stationary_duration_over_180s', 'passenger_forced_cancellation', 'exceptionally_long_assessment_signal_that_must_remain_available_in_full', 'fourth_hidden_signal'];
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...mockDetailWithAssessment,
      assessment: { ...mockDetailWithAssessment.assessment, reason_codes: codes },
    });
    render(<FinalizationTab caseDetail={{ ...mockDetailWithAssessment, preliminary_judgment: committedJudgment('case-jev-001', 'analyst-1'), assessment: { ...mockDetailWithAssessment.assessment, reason_codes: codes } } as any} isActive canWrite={false} busy={false} choice="" onChoice={() => {}} note="" onNote={() => {}} savingJudgment={false} onSaveJudgment={() => {}} rationale="" onRationale={() => {}} onDecision={() => {}} delta="mismatch" />);
    const signals = screen.getByText(/stationary_duration_over_180s/);
    for (const code of codes.slice(0, 3)) {
      expect(screen.getByText(new RegExp(code))).toBeInTheDocument();
    }
    expect(signals).toBeInTheDocument();
    expect(screen.queryByText(codes[3])).not.toBeInTheDocument();
  });

});
