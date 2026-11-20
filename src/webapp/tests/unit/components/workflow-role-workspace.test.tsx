import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import { awaitingStatusFor } from '@/lib/workflow-roles';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const ids = ['36900000-0000-4000-8000-000000000001', '36900000-0000-4000-8000-000000000002'];
const statuses = ['report_issued', 'in_review'];
const items = ids.map((id, i) => ({ id, priority: 'P1', driver_name: `Driver ${i + 1}`, vehicle_plate: `Plate ${i + 1}`, version: 7, status: statuses[i], category: 'C', confidence: 0.9 }));
let roles: string[];
let posts: string[];

beforeEach(() => {
  roles = ['reviewer']; posts = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (init?.method === 'POST') posts.push(path);
    if (path === '/api/v1/me') return json({ id: 'p1', display_name: 'Reviewer', roles });
    if (path === '/api/v1/cases') return json({ items, total: 2 });
    if (path.endsWith('/workflow')) return json({ steps: [], actions: ['confirm-report'], next: { actor_role: 'KSCL', text: 'Depot (KSCL) xác nhận biên bản' }, closed: false });
    if (path.endsWith('/agent-session')) return json({ messages: [] });
    if (path.endsWith('/stream')) return new Response('', { headers: { 'Content-Type': 'text/event-stream' } });
    if (/\/(dispute-dossier|workflow-trace|workflow-draft)$/.test(path)) return json(null);
    const item = items.find(i => path.includes(i.id));
    return json({ case: item, active_lease: null, assessment: { category: 'C', confidence: 0.9 } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

it('maps workflow roles to their awaiting status; analysts/admins get none', () => {
  expect(awaitingStatusFor(['reviewer'])).toBe('report_issued');
  expect(awaitingStatusFor('ops_director')).toBe('need_ops_dir_approved');
  expect(awaitingStatusFor(['marketplace_director'])).toBe('need_mkp_dir_approved');
  expect(awaitingStatusFor(['analyst'])).toBeNull();
  expect(awaitingStatusFor(['admin', 'reviewer'])).toBeNull();
});

it('reviewer: queue defaults to awaiting cases, no Claim button, read-only hint, can switch to all', async () => {
  const user = userEvent.setup();
  render(<CockpitWorkspaceView />);
  const toggle = await screen.findByTestId('awaiting-toggle');
  await waitFor(() => expect(within(toggle).getByRole('button', { pressed: true })).toHaveTextContent(/Awaiting me|Chờ tôi/));
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(1));
  expect(screen.queryByRole('button', { name: /^(Claim|Nhận)$/ })).not.toBeInTheDocument();
  expect(screen.getByTestId('workflow-readonly-hint')).toBeVisible();
  await user.click(within(toggle).getAllByRole('button')[1]);
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2));
  expect(posts).toEqual([]);
});

it('analyst keeps Claim and sees no workflow toggle or hint', async () => {
  roles = ['analyst'];
  render(<CockpitWorkspaceView />);
  await waitFor(() => expect(screen.getAllByRole('button', { name: /^(Claim|Nhận)$/ }).length).toBeGreaterThan(0));
  expect(screen.queryByTestId('awaiting-toggle')).not.toBeInTheDocument();
  expect(screen.queryByTestId('workflow-readonly-hint')).not.toBeInTheDocument();
});
