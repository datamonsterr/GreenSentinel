import React from 'react';
import { act, fireEvent, render, screen, waitFor, within, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { LocaleProvider, useLocale } from '@/lib/locale';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const first = '36800000-0000-4000-8000-000000000001';
const second = '36800000-0000-4000-8000-000000000002';
const analyst = '36800000-0000-4000-8000-000000000003';
const items = [first, second].map((id, i) => ({ id, priority: 'P1', driver_name: `Driver ${i + 1}`, vehicle_plate: `Plate ${i + 1}`, version: 7, status: 'in_review', category: 'SECRET-CATEGORY', confidence: .93 }));
let leases: Record<string, string>;
let judgments: Record<string, unknown>;
let posts: Array<{ path: string; body: Record<string, unknown> }>;
let claimResponse: (() => Promise<Response>) | undefined;
let judgmentResponse: (() => Promise<Response>) | undefined;
let delayedDossier: Promise<Response> | undefined;
let dossierRequestCount = 0;
let decisionResponse: (() => Promise<Response>) | undefined;
let roles: string[];
beforeEach(() => {
  leases = {}; judgments = {}; posts = []; claimResponse = undefined; judgmentResponse = undefined; delayedDossier = undefined; dossierRequestCount = 0; decisionResponse = undefined; roles = ['analyst'];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    const id = path.split('/')[4];
    if (init?.method === 'POST') {
      posts.push({ path, body: JSON.parse(String(init.body)) });
      if (path.endsWith('/claim')) { if (claimResponse) return claimResponse(); leases[id] = analyst; return json({ case_id: id }); }
      if (path.endsWith('/release')) { delete leases[id]; return json({ case_id: id }); }
      if (path.endsWith('/preliminary-assessment')) { if (judgmentResponse) return judgmentResponse(); const judgment = { id: 'judgment-368', case_id: id, analyst_id: analyst, judgment: posts.at(-1)!.body.judgment, created_at: '2026-10-15' }; judgments[id] = judgment; return json(judgment); }
      if (path.endsWith('/adjudicate')) { if (decisionResponse) return decisionResponse(); return json({ case_id: id, status: 'resolved', version: 8 }); }
      if (path.endsWith('/actions')) return json({ case_id: id });
    }
    if (path === '/api/v1/me') return json({ id: analyst, display_name: 'Analyst', roles });
    if (path === '/api/v1/cases') return json({ items, total: 2 });
    if (path.endsWith('/agent-session')) return json({ messages: [{ id: 'assistant', role: 'assistant', content: 'SECRET-CATEGORY 93%', created_at: '2026-10-15' }] });
    if (path.endsWith('/agent-context')) return json({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, context_window: 10000, breakdown: { system: 0, dossier: 0, history: 0, tool_results: 0, query: 0 }, turn_count: 0 });
    if (path.endsWith('/dispute-dossier')) { dossierRequestCount += 1; if (delayedDossier && dossierRequestCount >= 2) return delayedDossier; return json(null); }
    if (path.endsWith('/workflow-trace')) return json(null);
    if (path.endsWith('/stream')) return new Response('', { headers: { 'Content-Type': 'text/event-stream' } });
    const item = items.find(item => item.id === id);
    return json({ case: item, active_lease: leases[id] ? { analyst_id: leases[id], expires_at: '2099-01-01' } : null, preliminary_judgment: judgments[id], assessment: { category: 'SECRET-CATEGORY', confidence: .93, reason_codes: ['SECRET-REASON'] }, forensic_brief: { case_id: id, summary_text: 'Observed vehicle stopped.' } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });
async function open() { const view = render(<CockpitWorkspaceView />); await screen.findByRole('tab', { name: 'Complete' }); return view; }
it('removes duplicate center header/footer; AI banner opens judgment only in Complete', async () => {
  const user = userEvent.setup(); await open();
  expect(screen.queryByRole('group', { name: 'Case header' })).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox', { name: 'Decision rationale' })).not.toBeInTheDocument();
  // The copilot panel renders prior chat history; the masking gate applies to
  // the center workspace, so scope the AI-field assertion there.
  expect(within(screen.getByRole('region', { name: 'Case workspace' })).queryByText(/SECRET-CATEGORY|SECRET-REASON/)).not.toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  expect(screen.getByRole('radiogroup', { name: 'Independent judgment' })).toBeVisible();
});
it('does not retain duplicate Driver panels across Driver → Complete → Driver', async () => {
  const errors: unknown[][] = [];
  const errorSpy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => { errors.push(args); });
  try {
    const user = userEvent.setup(); await open();
    const centerTabs = within(screen.getByRole('tablist', { name: 'Case views' }));
    await user.click(centerTabs.getByRole('tab', { name: 'Driver' }));
    expect(screen.getAllByRole('tabpanel', { name: 'Driver' })).toHaveLength(1);
    await user.click(screen.getByRole('tab', { name: 'Complete' }));
    await user.click(centerTabs.getByRole('tab', { name: 'Driver' }));
    expect(screen.getAllByRole('tabpanel', { name: 'Driver' })).toHaveLength(1);
    expect(errors.filter(args => args.some(arg => String(arg).includes('same key')))).toHaveLength(0);
  } finally {
    errorSpy.mockRestore();
  }
});
it('claims exact nonselected card once while busy, without replacing selected detail', async () => {
  const user = userEvent.setup(); await open();
  let finish!: (response: Response) => void;
  claimResponse = () => new Promise<Response>(resolve => { finish = resolve; });
  const card = screen.getAllByRole('article').find(card => within(card).queryByText('Driver 2'))!;
  await user.click(within(card).getByRole('button', { name: 'Claim' }));
  expect(within(card).getByRole('button', { name: 'Claiming…' })).toBeDisabled();
  expect(posts).toHaveLength(1);
  expect(posts[0].path).toBe(`/api/v1/cases/${second}/claim`);
  await act(async () => { leases[second] = analyst; finish(json({ case_id: second })); });
  await waitFor(() => expect(within(card).getByRole('button', { name: 'Release' })).toBeEnabled());
  expect(screen.getByRole('button', { name: /No data yet → No data yet/ })).toBeVisible();
});
it('queue card has top click-to-copy ID, removes bottom duplicate copy ID, and has no nested buttons', async () => {
  await open();
  const card = screen.getAllByRole('article').find(card => within(card).queryByText('Driver 1'))!;
  // Top click-to-copy element exists with accessible name
  const copyBtn = within(card).getByRole('button', { name: `Case ID: ${first}` });
  expect(copyBtn).toBeInTheDocument();
  expect(copyBtn).toHaveTextContent(`#${first.slice(-8)}`);

  // Claim button exists
  const claimBtn = within(card).getByRole('button', { name: 'Claim' });
  expect(claimBtn).toBeInTheDocument();

  // No duplicate CopyId next to claim: only one CopyId button in the card
  const copyButtons = within(card).getAllByRole('button', { name: new RegExp(`Case ID: ${first}`) });
  expect(copyButtons).toHaveLength(1);

  // No nested buttons in the card
  expect(card.querySelectorAll('button button')).toHaveLength(0);
});
it('claim conflict refreshes exact card ownership and shows a retryable card error', async () => {
  const user = userEvent.setup(); await open();
  claimResponse = async () => { leases[second] = 'other-analyst'; return json({ detail: 'Claim conflict' }, 409); };
  const card = screen.getAllByRole('article').find(card => within(card).queryByText('Driver 2'))!;
  await user.click(within(card).getByRole('button', { name: 'Claim' }));
  expect(await within(card).findByRole('alert')).toHaveTextContent('Ownership changed');
  expect(within(card).getByRole('button', { name: 'Claimed by another analyst' })).toBeDisabled();
  expect(screen.getByRole('button', { name: /No data yet → No data yet/ })).toBeVisible();
});
it('keeps Driver Relay request state isolated across A→B→A and ignores stale dossier response', async () => {
  leases[first] = analyst; leases[second] = analyst;
  let finish!: (response: Response) => void;
  delayedDossier = new Promise<Response>(resolve => { finish = resolve; });
  const user = userEvent.setup(); await open();
  // Wait for dynamic AnalystCopilotPanel to render before accessing tablist
  const relayTablist = within(await screen.findByRole('tablist', { name: 'Agent panels' }));
  await user.click(relayTablist.getByRole('tab', { name: 'Driver' }));
  const relayA = within(screen.getByRole('tabpanel', { name: 'Driver' }));
  await user.type(relayA.getByRole('textbox'), 'Check traffic evidence');
  await user.click(relayA.getByRole('button', { name: /Gửi|Send/i }));
  expect(relayA.getByRole('textbox')).toBeDisabled();
  await user.click(screen.getByRole('button', { name: /Driver 2/ }));
  expect(relayTablist.getByRole('tab', { name: 'Driver' })).toHaveAttribute('aria-selected', 'true');
  const relayB = within(screen.getByRole('tabpanel', { name: 'Driver' }));
  expect(relayB.getByRole('textbox')).toBeEnabled();
  expect(relayB.getByRole('textbox')).toHaveValue('');
  await user.click(screen.getByRole('button', { name: /Driver 1/ }));
  expect(relayTablist.getByRole('tab', { name: 'Driver' })).toHaveAttribute('aria-selected', 'true');
  await act(async () => finish(json({ transcript: [{ id: 'stale', content: 'STALE-A-RESPONSE' }] })));
  expect(screen.queryByText('STALE-A-RESPONSE')).not.toBeInTheDocument();
});
it('keeps the new case rationale when an earlier decision response arrives late', async () => {
  leases[first] = analyst; leases[second] = analyst;
  judgments[first] = { id: 'saved-first', case_id: first, analyst_id: analyst, judgment: 'Nghi ngờ vi phạm' };
  let finish!: (response: Response) => void;
  decisionResponse = () => new Promise<Response>(resolve => { finish = resolve; });
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  const rationale = screen.getByRole('textbox', { name: 'Decision rationale' });
  await user.type(rationale, 'First case decision rationale');
  await user.click(screen.getByRole('button', { name: 'Approve conclusion' }));
  await user.click(screen.getByRole('button', { name: /Driver 2/ }));
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  const secondRationale = screen.getByRole('textbox', { name: 'Decision rationale' });
  await waitFor(() => expect(secondRationale).toHaveValue('Observed vehicle stopped.'));
  fireEvent.change(secondRationale, { target: { value: 'Second case draft rationale' } });
  expect(secondRationale).toHaveValue('Second case draft rationale');
  await act(async () => finish(json({ case_id: first, status: 'resolved', version: 8 })));
  expect(secondRationale).toHaveValue('Second case draft rationale');
  expect(screen.queryByText('Decision saved')).not.toBeInTheDocument();
});
it('owned card has no Reject; Release uses the selected card lease API', async () => {
  leases[first] = analyst;
  const user = userEvent.setup(); await open();
  expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
  expect(posts).toHaveLength(0);
  await user.click(screen.getByRole('button', { name: 'Release' }));
  await waitFor(() => expect(posts.some(post => post.path.endsWith('/release'))).toBe(true));
  expect(posts[0]).toMatchObject({ path: `/api/v1/cases/${first}/release`, body: { analyst_id: analyst } });
});
it('ignores acknowledged judgment for a case left while save was pending', async () => {
  leases[first] = analyst; leases[second] = analyst;
  let finish!: (response: Response) => void;
  judgmentResponse = () => new Promise(resolve => { finish = resolve; });
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  await user.click(screen.getByRole('radio', { name: 'Suspected fraud' }));
  await user.click(screen.getByRole('button', { name: 'Save judgment & view AI' }));
  await user.click(screen.getByRole('button', { name: /Driver 2/ }));
  await screen.findByRole('button', { name: 'View AI results' });
  await act(async () => finish(json({ id: 'old-judgment', case_id: first, analyst_id: analyst, judgment: 'Nghi ngờ vi phạm' })));
  expect(screen.queryByLabelText(/^AI advice:/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'View AI results' })).toBeEnabled();
});
it('ignores a deferred preliminary save after A→B→A returns to the original case', async () => {
  leases[first] = analyst; leases[second] = analyst;
  let finish!: (response: Response) => void;
  judgmentResponse = () => new Promise(resolve => { finish = resolve; });
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  await user.click(screen.getByRole('radio', { name: 'Suspected fraud' }));
  await user.click(screen.getByRole('button', { name: 'Save judgment & view AI' }));
  await user.click(screen.getByRole('button', { name: /Driver 2/ }));
  await user.click(screen.getByRole('button', { name: /Driver 1/ }));
  await screen.findByRole('button', { name: 'View AI results' });
  await act(async () => finish(json({ id: 'stale-return', case_id: first, analyst_id: analyst, judgment: 'Nghi ngờ vi phạm' })));
  expect(screen.getByRole('button', { name: 'View AI results' })).toBeEnabled();
  expect(screen.queryByLabelText(/^AI advice:/)).not.toBeInTheDocument();
});
it('releases preliminary busy state for B after a deferred A response settles', async () => {
  leases[first] = analyst; leases[second] = analyst;
  let finish!: (response: Response) => void;
  judgmentResponse = () => new Promise(resolve => { finish = resolve; });
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  await user.click(screen.getByRole('radio', { name: 'Suspected fraud' }));
  await user.click(screen.getByRole('button', { name: 'Save judgment & view AI' }));
  await user.click(screen.getByRole('button', { name: /Driver 2/ }));
  await act(async () => finish(json({ id: 'stale-A', case_id: first, analyst_id: analyst, judgment: 'Nghi ngờ vi phạm' })));
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  await user.click(screen.getByRole('radio', { name: 'Suspected fraud' }));
  expect(screen.getByRole('button', { name: 'Save judgment & view AI' })).toBeEnabled();
});
it.each(['Approve conclusion', 'Dismiss'])('signed %s sends current case version and persisted judgment, with human rationale', async label => {
  leases[first] = analyst;
  judgments[first] = { id: 'saved-judgment', case_id: first, analyst_id: analyst, judgment: 'Nghi ngờ vi phạm' };
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  const rationale = screen.getByRole('textbox', { name: 'Decision rationale' });
  await user.clear(rationale); await user.type(rationale, '123456789');
  expect(screen.getByRole('button', { name: label })).toBeDisabled();
  await user.type(rationale, '0');
  await user.click(screen.getByRole('button', { name: label }));
  await waitFor(() => expect(posts.some(post => post.path.endsWith('/adjudicate'))).toBe(true));
  expect(posts.find(post => post.path.endsWith('/adjudicate'))!.body).toMatchObject({ analyst_id: analyst, expected_case_version: 7, preliminary_judgment_id: 'saved-judgment', rationale: '1234567890', outcome: label.startsWith('Approve') ? 'AGREE' : 'DISAGREE' });
});
it('Request evidence uses existing action contract and only includes analyst-entered fields', async () => {
  leases[first] = analyst;
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  const rationale = screen.getByRole('textbox', { name: 'Decision rationale' });
  await user.clear(rationale); await user.type(rationale, 'Need traffic corroboration');
  await user.click(screen.getByRole('button', { name: 'Request evidence' }));
  await waitFor(() => expect(posts.some(post => post.path.endsWith('/actions'))).toBe(true));
  expect(posts.find(post => post.path.endsWith('/actions'))!.body).toEqual({ action_type: 'REQUEST_EVIDENCE', analyst_id: analyst, notes: 'Need traffic corroboration' });
  expect(posts.some(post => post.path.endsWith('/adjudicate'))).toBe(false);
});
it('a viewer with a lease cannot record judgment or submit an adjudication', async () => {
  leases[first] = analyst; roles = ['viewer'];
  const user = userEvent.setup(); await open();
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  expect(screen.getByRole('radio', { name: 'Suspected fraud' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Save judgment & view AI' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Request evidence' })).toBeDisabled();
  expect(posts).toHaveLength(0);
});
it('switches EN/VI without losing selected tab, judgment choice, note or source evidence', async () => {
  leases[first] = analyst;
  function Harness() { const { setLocale } = useLocale(); return <><button onClick={() => setLocale('vi')}>Switch to Vietnamese</button><CockpitWorkspaceView /></>; }
  const user = userEvent.setup(); render(<LocaleProvider><Harness /></LocaleProvider>);
  await screen.findByRole('tab', { name: 'Complete' });
  await user.click(screen.getByRole('tab', { name: 'Complete' }));
  await user.click(screen.getByRole('button', { name: 'View AI results' }));
  await user.click(screen.getByRole('radio', { name: 'Suspected fraud' }));
  await user.type(screen.getByRole('textbox', { name: 'Judgment note (optional)' }), 'Original evidence note');
  await user.click(screen.getByRole('button', { name: 'Switch to Vietnamese' }));
  expect(screen.getByRole('tab', { name: 'Hoàn tất' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('radio', { name: 'Nghi ngờ vi phạm' })).toBeChecked();
  expect(screen.getByRole('textbox', { name: 'Ghi chú phán đoán (tuỳ chọn)' })).toHaveValue('Original evidence note');
  expect(screen.getByRole('button', { name: 'Lưu phán đoán và xem AI' })).toBeEnabled();
  expect(screen.getByRole('textbox', { name: 'Lý do thẩm định' })).toHaveValue('Observed vehicle stopped.');
});
