import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import { setApiTokenProvider } from '@/lib/api-client';

vi.mock('next/dynamic', () => ({ default: () => () => null }));
vi.mock('@/components/map/maplibre-view', () => ({ MapLibreView: () => null }));
const item = { id: 'case-evidence', driver_name: 'Evidence Driver', priority: 'P1', status: 'ready', version: 1 };
const detail = {
  case: item, trip: { pickup_address: 'Hanoi', dropoff_address: 'VinUni' },
  active_lease: { analyst_id: 'analyst-me', expires_at: '2099-01-01T00:00:00Z' },
  forensic_brief: { summary_text: '' },
};
const rationale = 'Need additional pickup evidence';
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const never = () => new Promise<Response>(() => {});
let mutate: () => Promise<Response>;
let stallRefresh: boolean;
let saved: boolean;
let multipleCases: boolean;
let fetchMock: ReturnType<typeof vi.fn>;
const flush = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const posts = () => fetchMock.mock.calls.filter(([url, options]) => String(url).endsWith('/actions') && options?.method === 'POST');

beforeEach(() => {
  vi.useFakeTimers(); setApiTokenProvider(null); saved = false; stallRefresh = false; multipleCases = false;
  mutate = never;
  fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/actions') && options?.method === 'POST') return mutate();
    if (url.endsWith('/me')) return json({ id: 'analyst-me', display_name: 'Me', roles: ['analyst'] });
    if (url.includes('/cases?')) return saved && stallRefresh ? never() : json({ items: multipleCases ? [item, { ...item, id: 'case-other', driver_name: 'Other Driver' }] : [item], total: multipleCases ? 2 : 1 });
    if (url.endsWith('/cases/case-other')) return json({ ...detail, case: { ...item, id: 'case-other' } });
    if (url.endsWith('/cases/case-evidence')) return saved && stallRefresh ? never() : json(detail);
    if (url.includes('/stream')) return new Response(null, { status: 204 });
    if (url.endsWith('/agent/session')) return json({ session_id: 'session', messages: [] });
    return json(null);
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); setApiTokenProvider(null); vi.useRealTimers(); vi.unstubAllGlobals(); });

async function openComplete() {
  render(<CockpitWorkspaceView />);
  await flush();
  fireEvent.click(screen.getByRole('tab', { name: 'Complete' }));
  fireEvent.change(screen.getByLabelText('Decision rationale'), { target: { value: rationale } });
}

describe('Request evidence completion', () => {
  it('times out, retains rationale, and retries once after a stalled POST', async () => {
    await openComplete();
    const request = screen.getByRole('button', { name: 'Request evidence' });
    fireEvent.click(request);
    fireEvent.click(request);
    await flush();
    expect(posts()).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Saving…' }).every(button => button.hasAttribute('disabled'))).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(screen.getByRole('alert')).toHaveTextContent(/timed out/i);
    expect(screen.getByLabelText('Decision rationale')).toHaveValue(rationale);
    expect(screen.getByRole('button', { name: 'Request evidence' })).toBeEnabled();
    mutate = async () => json({ id: 'action-saved' });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await flush();
    expect(posts()).toHaveLength(2);
    expect(JSON.parse(posts()[1][1].body)).toMatchObject({ action_type: 'REQUEST_EVIDENCE', notes: rationale });
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument();
  });

  it('finishes saving when POST commits even if subsequent reads stall', async () => {
    mutate = async () => { saved = true; return json({ id: 'action-saved' }); };
    stallRefresh = true;
    await openComplete();
    fireEvent.click(screen.getByRole('button', { name: 'Request evidence' }));
    await flush();
    expect(posts()).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Decision rationale')).toHaveValue('');
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it('ignores a late POST response after timeout', async () => {
    let resolvePost!: (response: Response) => void;
    mutate = () => new Promise(resolve => { resolvePost = resolve; });
    await openComplete();
    fireEvent.click(screen.getByRole('button', { name: 'Request evidence' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    resolvePost(json({ id: 'late-action' }));
    await flush();
    expect(screen.getByRole('alert')).toHaveTextContent(/timed out/i);
    expect(screen.getByLabelText('Decision rationale')).toHaveValue(rationale);
    expect(posts()).toHaveLength(1);
  });

  it('does not carry a failed request retry into another selection', async () => {
    multipleCases = true;
    mutate = async () => json({ detail: 'Service unavailable' }, 503);
    await openComplete();
    fireEvent.click(screen.getByRole('button', { name: 'Request evidence' }));
    await flush();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: /Other Driver/ }));
    await flush();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Evidence Driver/ }));
    await flush();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it('shows an endpoint error with retry instead of hanging', async () => {
    mutate = async () => json({ detail: 'Action endpoint unavailable' }, 404);
    await openComplete();
    fireEvent.click(screen.getByRole('button', { name: 'Request evidence' }));
    await flush();
    expect(screen.getByRole('alert')).toHaveTextContent('API Error 404: Action endpoint unavailable');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Request evidence' })).toBeEnabled();
  });
});
