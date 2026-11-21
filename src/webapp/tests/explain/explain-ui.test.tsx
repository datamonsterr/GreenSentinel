import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/api-client', () => ({
  ApiError: class extends Error {},
  getApiBaseUrl: () => 'http://api',
  requestJson: vi.fn(),
}));
import { requestJson } from '@/lib/api-client';
import { ExplainSection } from '@/components/adjudication/explain-section';
import { HelpQueuePanel } from '@/components/explain/help-queue-panel';

const mock = vi.mocked(requestJson);
const view = (over: Record<string, unknown> = {}) => ({
  session: { id: 's1', case_id: 'c1', reason: 'RealTrip', state: 'submitted', mode: 'agent', scenario_code: 'SC-1', scenario_version: 2,
    workflow_code: 'WF-1', workflow_version: 1, turns_used: 2, n_max: 5, summary: null, submitted_at: null },
  flags: { novel_scenario: true, statement_changed: true, ai_inconclusive: false, session_interrupted: false, asked_for_help: true, asked_for_help_skipped: false },
  form: {}, transcript: [], similar_scenarios: [], plan: null, open_points: null,
  statement_versions: [
    { version: 1, source: 'form', reason: null, text: 'Kẹt xe.\nĐợi 10 phút.', content: {}, created_at: '2026-01-01T00:00:00Z' },
    { version: 2, source: 'chat', reason: 'edit', text: 'Kẹt xe.\nĐợi 25 phút.', content: {}, created_at: '2026-01-01T01:00:00Z' },
  ],
  rounds: [
    { round: 1, source: 'submit', state: 'needs_driver', confidence: 0.4, turns_used: 1, n_max: 5, llm_used: false, created_at: '2026-01-01T00:00:00Z' },
    { round: 2, source: 'confirm', state: 'eligible', confidence: 0.9, turns_used: 2, n_max: 5, llm_used: true, created_at: '2026-01-01T01:00:00Z' },
  ],
  provenance: [{ type: 'scenario', code: 'SC-1', version: 2 }, { type: 'workflow', code: 'WF-1', version: 1, tool: 'get_trip' }],
  suggestion: { round: 2, state: 'eligible', reason_code: 'RealTrip', confidence: 0.9, motive: 'm', suggested_questions: ['Anh chờ ở đâu?'], turns_used: 2, n_max: 5 },
  help_requests: [{ id: 'h1', status: 'replied', summary: 'Cần xác nhận', reply: 'Đã xác nhận', created_at: '2026-01-01T00:00:00Z' }],
  feedback: [
    { id: 'f1', verdict: 'agree', error_types: [], comment: null, author_name: 'Ha', created_at: '2026-01-01T00:00:00Z' },
    { id: 'f2', verdict: 'disagree', error_types: ['wrong_facts'], comment: 'sai', author_name: 'Ha', created_at: '2026-01-02T00:00:00Z' },
  ],
  ...over,
});

beforeEach(() => { mock.mockReset(); });

describe('ExplainSection', () => {
  it('renders nothing when the case has no session (404)', async () => {
    const rejected = Object.assign(new Error('API Error 404'), { status: 404 });
    mock.mockRejectedValue(rejected);
    const { container } = render(<ExplainSection caseId="c1" locale="vi" roles={['analyst']} />);
    try { await new Promise((r) => setTimeout(r, 30)); } catch (e) { console.log('CAUGHT', e); }

    expect(container.querySelector('[data-testid="explain-section"]')).toBeNull();
  });

  it('shows rounds, flags, provenance, suggestion, help history and latest feedback only', async () => {
    mock.mockResolvedValue(view());
    render(<ExplainSection caseId="c1" locale="vi" roles={['analyst']} />);
    await screen.findByTestId('explain-section');
    expect(screen.getByTestId('round-1')).toHaveAttribute('data-state', 'needs_driver');
    expect(screen.getByTestId('round-2')).toHaveAttribute('data-state', 'eligible');
    expect(screen.getByTestId('flag-novel_scenario').className).toContain('t-purple');
    expect(screen.queryByTestId('flag-ai_inconclusive')).toBeNull();
    expect(screen.getByTestId('provenance')).toHaveTextContent('SC-1');
    expect(screen.getByTestId('provenance')).toHaveTextContent('get_trip');
    expect(screen.getByTestId('suggestion')).toHaveTextContent('Anh chờ ở đâu?');
    expect(screen.getByTestId('suggestion')).toHaveTextContent('2 / 5');
    expect(screen.getByTestId('help-history')).toHaveTextContent('Đã xác nhận');
    expect(screen.getAllByTestId('feedback-entry')).toHaveLength(1);
  });

  it('expands a statement version with a diff against the previous one', async () => {
    mock.mockResolvedValue(view());
    render(<ExplainSection caseId="c1" locale="en" roles={['analyst']} />);
    await screen.findByTestId('explain-section');
    fireEvent.click(screen.getByTestId('version-toggle-2'));
    expect(screen.getByTestId('diff-add')).toHaveTextContent('Đợi 25 phút.');
    expect(screen.getByTestId('diff-del')).toHaveTextContent('Đợi 10 phút.');
  });

  it('requires an error type for disagree, then posts feedback', async () => {
    mock.mockResolvedValue(view({ feedback: [] }));
    render(<ExplainSection caseId="c1" locale="en" roles={['analyst']} />);
    await screen.findByTestId('explain-section');
    fireEvent.click(screen.getByTestId('feedback-disagree'));
    const submit = screen.getByTestId('feedback-submit');
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Wrong facts'));
    expect(submit).not.toBeDisabled();
    fireEvent.change(screen.getByTestId('feedback-comment'), { target: { value: 'sai' } });
    mock.mockResolvedValueOnce({});
    mock.mockResolvedValue(view());
    fireEvent.click(submit);
    await waitFor(() => {
      const post = mock.mock.calls.find(([u]) => String(u).endsWith('/explain/feedback'));
      expect(post).toBeTruthy();
      expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ verdict: 'disagree', error_types: ['wrong_facts'], comment: 'sai' });
    });
  });

  it('is read-only for reviewer / ops_director', async () => {
    mock.mockResolvedValue(view());
    render(<ExplainSection caseId="c1" locale="en" roles={['reviewer']} />);
    await screen.findByTestId('explain-section');
    expect(screen.queryByTestId('feedback-form')).toBeNull();
    expect(screen.getByTestId('round-1')).toBeInTheDocument();
  });
});

describe('HelpQueuePanel', () => {
  const item = (o: Record<string, unknown> = {}) => ({ id: 'h1', session_id: 's1', case_id: 'c1', status: 'open', trigger: 'low_confidence', summary: 'Tài xế nói kẹt xe',
    stuck_point: 'Không rõ giờ', facts: ['a'], options: null, claimed_by_name: null, reply: null, reply_facts: [], created_at: '2026-01-01T00:00:00Z', expires_at: null, ...o });

  it('claims then replies with text and facts', async () => {
    mock.mockImplementation(async (url: string) => {
      if (String(url).includes('/claim')) return item({ status: 'claimed', claimed_by_name: 'Ha' });
      if (String(url).includes('/reply')) return item({ status: 'replied' });
      if (String(url).includes('help-requests/h1')) return { ...item(), transcript: [{ seq: 1, kind: 'agent_question', text: 'Anh kẹt ở đâu?' }], statement_text: 'x', reason: 'RealTrip' };
      return { items: [item()], counts: { open: 1, claimed: 0, total: 1 } };
    });
    const onChanged = vi.fn();
    render(<HelpQueuePanel locale="en" open onClose={() => {}} onChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId('help-claim-h1'));
    const reply = await screen.findByTestId('help-reply-text');
    fireEvent.change(reply, { target: { value: 'Đã xác nhận' } });
    fireEvent.change(screen.getByTestId('help-reply-facts'), { target: { value: 'fact 1\n\nfact 2' } });
    fireEvent.click(screen.getByTestId('help-reply-send'));
    await waitFor(() => {
      const post = mock.mock.calls.find(([u]) => String(u).endsWith('/reply'));
      expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ text: 'Đã xác nhận', facts: ['fact 1', 'fact 2'] });
    });
    expect(onChanged).toHaveBeenCalled();
  });
});
