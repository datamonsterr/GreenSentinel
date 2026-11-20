import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@/lib/api-client', () => ({
  getApiBaseUrl: () => 'http://api',
  requestJson: vi.fn(async () => ({})),
}));
import { requestJson } from '@/lib/api-client';
import {
  canGiveFeedback, canUseHelpQueue, diffStatements, explainApi, flagTone, latestFeedbackPerAuthor, roundStateTone,
} from '@/lib/explain-client';

beforeEach(() => { vi.mocked(requestJson).mockClear(); });

describe('explain-client helpers', () => {
  it('keeps the latest feedback per author', () => {
    const fb = [
      { id: '1', verdict: 'agree', error_types: [], comment: null, author_name: 'A', created_at: '2026-01-01T00:00:00Z' },
      { id: '2', verdict: 'disagree', error_types: ['wrong_facts'], comment: 'x', author_name: 'A', created_at: '2026-01-02T00:00:00Z' },
      { id: '3', verdict: 'agree', error_types: [], comment: null, author_name: 'B', created_at: '2026-01-01T12:00:00Z' },
    ] as never;
    const out = latestFeedbackPerAuthor(fb);
    expect(out.map((f) => f.id).sort()).toEqual(['2', '3']);
  });

  it('maps states and flags to tones', () => {
    expect(roundStateTone('eligible')).toBe('t-green');
    expect(roundStateTone('not_eligible')).toBe('t-red');
    expect(roundStateTone('needs_driver')).toBe('t-amber');
    expect(roundStateTone('missing_internal')).toBe('t-grey');
    expect(flagTone('ai_inconclusive')).toBe('t-orange');
    expect(flagTone('unknown')).toBe('t-grey');
  });

  it('gates roles: reviewer/ops_director read-only', () => {
    expect(canGiveFeedback(['analyst'])).toBe(true);
    expect(canGiveFeedback(['admin'])).toBe(true);
    expect(canGiveFeedback(['reviewer'])).toBe(false);
    expect(canGiveFeedback(['ops_director'])).toBe(false);
    expect(canUseHelpQueue(['fraud_analyst'])).toBe(true);
    expect(canUseHelpQueue(['ops_director'])).toBe(false);
    expect(canUseHelpQueue([])).toBe(false);
  });

  it('diffs statement versions line by line', () => {
    const d = diffStatements('Tôi bị kẹt xe.\nĐợi 10 phút.', 'Tôi bị kẹt xe.\nĐợi 25 phút.\nCó ảnh.');
    expect(d.map((x) => x.op)).toEqual(['same', 'del', 'add', 'add']);
    expect(d[1].text).toBe('Đợi 10 phút.');
    expect(d[2].text).toBe('Đợi 25 phút.');
  });
});

describe('explainApi', () => {
  it('hits the analyst endpoints', async () => {
    await explainApi.get('c 1');
    await explainApi.feedback('c1', { verdict: 'disagree', error_types: ['wrong_facts'], comment: 'no' });
    await explainApi.helpCount();
    await explainApi.helpList('open,claimed');
    await explainApi.claim('h1');
    await explainApi.reply('h1', 'ok', ['f']);
    const calls = vi.mocked(requestJson).mock.calls.map(([u, o]) => `${(o as RequestInit)?.method} ${u}`);
    expect(calls).toEqual([
      'GET http://api/api/v1/cases/c%201/explain',
      'POST http://api/api/v1/cases/c1/explain/feedback',
      'GET http://api/api/v1/explain/help-requests/count',
      'GET http://api/api/v1/explain/help-requests?status=open%2Cclaimed',
      'POST http://api/api/v1/explain/help-requests/h1/claim',
      'POST http://api/api/v1/explain/help-requests/h1/reply',
    ]);
    expect(JSON.parse(String((vi.mocked(requestJson).mock.calls[5][1] as RequestInit).body))).toEqual({ text: 'ok', facts: ['f'] });
  });
});
