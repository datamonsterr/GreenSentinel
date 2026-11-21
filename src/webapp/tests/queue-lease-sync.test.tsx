import React from 'react';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import * as api from '@/lib/api-client';

vi.mock('@/lib/api-client', () => ({
  fetchCases: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchForensicBrief: vi.fn(),
  fetchCasePolicy: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  claimCase: vi.fn(),
  releaseCase: vi.fn(),
  adjudicateCase: vi.fn(),
  recordCaseAction: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
  streamPolicyChat: vi.fn(),
  getDisputeDossier: vi.fn(),
  delegateAnalystInquiry: vi.fn(),
  getCaseWorkflowTrace: vi.fn(),
  applyPrecedentProcedure: vi.fn(),
}));

const item = {
  id: 'case-sync-1',
  driver_name: 'Trần Văn Sync',
  vehicle_plate: '29A-12345',
  priority: 'P1',
  priority_score: 95,
  status: 'ready',
  version: 1,
};

const detailLockedByOther = {
  case: item,
  trip: { pickup_address: 'Hanoi', dropoff_address: 'VinUni' },
  conversation: [{ role: 'driver' as const, text: 'Arrived at pickup', occurred_at: '2026-10-05T01:00:00Z' }],
  active_lease: {
    analyst_id: 'analyst-holder',
    expires_at: new Date(Date.now() + 300000).toISOString(),
  },
};

const detailUnclaimed = {
  case: item,
  trip: { pickup_address: 'Hanoi', dropoff_address: 'VinUni' },
  conversation: [{ role: 'driver' as const, text: 'Arrived at pickup', occurred_at: '2026-10-05T01:00:00Z' }],
  active_lease: null,
};

describe('Queue Lease Sync & Concurrency UI (Issue #144)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [item], total: 1, limit: 50, offset: 0 });
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: 'analyst-me', name: 'Analyst Me', role: 'analyst', roles: ["analyst"] });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: 'sess-1', messages: [] });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders read-only review lock notice banner and disables claim and decision buttons when case is locked by another analyst', async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(detailLockedByOther as any);

    render(<CockpitWorkspaceView />);

    // Wait for case to load
    fireEvent.click(await screen.findByRole('tab', { name: 'Customer' }));
    expect(await screen.findByText('Arrived at pickup')).toBeInTheDocument();

    // 1. Claim button shows "Locked by another analyst" and is disabled
    const lockBtn = screen.getByRole('button', { name: 'Claimed by another analyst' });
    expect(lockBtn).toBeInTheDocument();
    expect(lockBtn).toBeDisabled();

    // 2. Read-only banner is rendered with analyst holder ID
    const banner = screen.getByRole('status', { name: 'Read-only: another analyst owns this case.' });
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/read-only: another analyst owns this case/i);

    // 3. Send decision button is disabled
    fireEvent.click(screen.getByRole('tab', { name: 'Complete' }));
    const sendBtn = screen.getByRole('button', { name: 'Request evidence' });
    expect(sendBtn).toBeDisabled();
  });

  it('recovers from 409 conflict on stale claim attempt by removing stale row and refetching', async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(detailUnclaimed as any);
    vi.mocked(api.claimCase).mockRejectedValueOnce(
      new Error('409: Case case-sync-1 is currently claimed by analyst analyst-other')
    );

    render(<CockpitWorkspaceView />);

    // Initially unclaimed
    const claimButtons = await screen.findAllByRole('button', { name: 'Claim' });
    const claimBtn = claimButtons[0];
    expect(claimBtn).not.toBeDisabled();

    // Attempt claim
    fireEvent.click(claimBtn);

    // Stale 409 error is shown
    expect(await screen.findByRole('alert')).toHaveTextContent(/ownership changed/i);

    // Stale case is filtered out and loadCases is called again
    await waitFor(() => {
      expect(api.fetchCases).toHaveBeenCalledTimes(2);
    });
  });

  it('recovers from 409 conflict on stale decision submit by refetching detail and queue', async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...detailUnclaimed,
      active_lease: { analyst_id: 'analyst-me', expires_at: '2099-01-01T00:00:00Z' },
      preliminary_judgment: { id: 'judgment-sync', case_id: item.id, analyst_id: 'analyst-me', judgment: 'Nghi ngờ vi phạm', note: null, created_at: '2026-10-15T00:00:00Z' },
    } as any);
    vi.mocked(api.adjudicateCase).mockRejectedValueOnce(
      new Error('409: Case case-sync-1 is currently claimed by analyst analyst-other')
    );

    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Complete' }));

    // Enter rationale
    fireEvent.change(screen.getByLabelText('Decision rationale'), {
      target: { value: 'Approving case based on evidence' },
    });

    // Submit decision
    fireEvent.click(screen.getByRole('button', { name: 'Approve conclusion' }));

    // 409 error displayed
    expect(await screen.findByText(/currently claimed by analyst analyst-other/)).toBeInTheDocument();

    // Refetches detail and queue to transition into locked state
    await waitFor(() => {
      expect(api.fetchCaseDetail).toHaveBeenCalledTimes(2);
      expect(api.fetchCases).toHaveBeenCalledTimes(2);
    });
  });

  it('runs periodic background queue sync at 10s interval', async () => {
    vi.useFakeTimers();
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(detailUnclaimed as any);

    render(<CockpitWorkspaceView />);

    // Initial mount calls fetchCases once
    expect(api.fetchCases).toHaveBeenCalledTimes(1);

    // Resolve mount effects before advancing the installed queue-sync timer.
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    // Fast forward 10 seconds
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });

    // Background sync triggered
    expect(api.fetchCases).toHaveBeenCalledTimes(2);

    // Fast forward another 10 seconds
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(api.fetchCases).toHaveBeenCalledTimes(3);
  });

  it('renders Claim when queue card has stale assigned_analyst_id but no active lease', async () => {
    const staleItem = {
      ...item,
      id: 'case-sync-stale',
      driver_name: 'Nguyễn Văn Stale',
      assigned_analyst_id: 'analyst-me',
      active_lease_analyst_id: null,
      active_lease_expires_at: null,
    };
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [item, staleItem],
      total: 2,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(detailUnclaimed as any);

    render(<CockpitWorkspaceView />);

    // Wait for cases to render
    expect(await screen.findByText('Nguyễn Văn Stale')).toBeInTheDocument();

    // Stale item queue card must show Claim, never Release
    expect(screen.queryByRole('button', { name: 'Release' })).not.toBeInTheDocument();
    const claimButtons = screen.getAllByRole('button', { name: 'Claim' });
    expect(claimButtons.length).toBe(2);
  });

  it('renders Release when active_lease_analyst_id is me and stays Release after select', async () => {
    const myLeasedItem = {
      ...item,
      id: 'case-sync-mine',
      assigned_analyst_id: null,
      active_lease_analyst_id: 'analyst-me',
      active_lease_expires_at: new Date(Date.now() + 600000).toISOString(),
    };
    const myDetail = {
      ...detailUnclaimed,
      case: myLeasedItem,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
    };
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [myLeasedItem],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(myDetail as any);

    render(<CockpitWorkspaceView />);

    const releaseButtons = await screen.findAllByRole('button', { name: 'Release' });
    expect(releaseButtons.length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Claim' })).not.toBeInTheDocument();

    const selectBtn = screen.getByRole('button', { name: new RegExp(myLeasedItem.driver_name, 'i') });
    fireEvent.click(selectBtn);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Release' })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Claim' })).not.toBeInTheDocument();
  });

  it('claims case with lease_duration_seconds 1800 in request body', async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(detailUnclaimed as any);
    vi.mocked(api.claimCase).mockResolvedValue({
      case_id: item.id,
      analyst_id: 'analyst-me',
      lease_duration_seconds: 1800,
    } as any);

    render(<CockpitWorkspaceView />);

    const claimButtons = await screen.findAllByRole('button', { name: 'Claim' });
    fireEvent.click(claimButtons[0]);

    await waitFor(() => {
      expect(api.claimCase).toHaveBeenCalledWith(item.id, {
        analyst_id: 'analyst-me',
        lease_duration_seconds: 1800,
      });
    });
  });

  it('renews claim with fake timers when lease remaining is less than 50% of 1800s', async () => {
    vi.useFakeTimers();
    const myDetailExpiring = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
    };
    const renewedDetail = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      },
    };

    vi.mocked(api.fetchCaseDetail).mockResolvedValue(myDetailExpiring as any);
    vi.mocked(api.claimCase).mockResolvedValue({
      case_id: item.id,
      analyst_id: 'analyst-me',
      lease_duration_seconds: 1800,
    } as any);

    render(<CockpitWorkspaceView />);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(api.claimCase).not.toHaveBeenCalled();
    const detailCallsBefore = vi.mocked(api.fetchCaseDetail).mock.calls.length;

    vi.mocked(api.fetchCaseDetail).mockResolvedValue(renewedDetail as any);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });

    expect(api.claimCase).toHaveBeenCalledTimes(1);
    expect(api.claimCase).toHaveBeenCalledWith(item.id, {
      analyst_id: 'analyst-me',
      lease_duration_seconds: 1800,
    });
    expect(vi.mocked(api.fetchCaseDetail).mock.calls.length).toBeGreaterThan(detailCallsBefore);
  });

  it('heartbeat only refreshes detail on renewal error', async () => {
    vi.useFakeTimers();
    const myDetailExpiring = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
    };

    vi.mocked(api.fetchCaseDetail).mockResolvedValue(myDetailExpiring as any);
    vi.mocked(api.claimCase).mockRejectedValueOnce(new Error('Network error'));

    render(<CockpitWorkspaceView />);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(api.claimCase).not.toHaveBeenCalled();
    const detailCallsBefore = vi.mocked(api.fetchCaseDetail).mock.calls.length;

    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });

    expect(api.claimCase).toHaveBeenCalledTimes(1);
    expect(api.claimCase).toHaveBeenCalledWith(item.id, {
      analyst_id: 'analyst-me',
      lease_duration_seconds: 1800,
    });
    expect(vi.mocked(api.fetchCaseDetail).mock.calls.length).toBeGreaterThan(detailCallsBefore);
  });

  it('does not renew lease when remaining time is >= 50% of 1800s', async () => {
    vi.useFakeTimers();
    // 1500s remaining >= 900s
    const myDetailFresh = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 1500000).toISOString(),
      },
    };

    vi.mocked(api.fetchCaseDetail).mockResolvedValue(myDetailFresh as any);

    render(<CockpitWorkspaceView />);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(api.claimCase).not.toHaveBeenCalled();

    // Advance 60s
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });

    // Should not call claimCase because remaining (1440s) >= 900s
    expect(api.claimCase).not.toHaveBeenCalled();
  });

  it('clears heartbeat interval on unmount', async () => {
    vi.useFakeTimers();
    const myDetailExpiring = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
    };

    vi.mocked(api.fetchCaseDetail).mockResolvedValue(myDetailExpiring as any);

    const { unmount } = render(<CockpitWorkspaceView />);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(api.claimCase).not.toHaveBeenCalled();

    unmount();

    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(api.claimCase).not.toHaveBeenCalled();
  });

  it('clears heartbeat interval on case change', async () => {
    vi.useFakeTimers();
    const item2 = { ...item, id: 'case-sync-2', driver_name: 'Driver 2' };
    const myDetailExpiring = {
      ...detailUnclaimed,
      active_lease: {
        analyst_id: 'analyst-me',
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
    };
    const otherDetail = {
      case: item2,
      trip: { pickup_address: 'Hanoi', dropoff_address: 'VinUni' },
      active_lease: null,
    };

    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [item, item2],
      total: 2,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockImplementation(async (id: string) => {
      if (id === item.id) return myDetailExpiring as any;
      return otherDetail as any;
    });

    render(<CockpitWorkspaceView />);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    // Switch case to item2
    const case2Button = screen.getByRole('button', { name: new RegExp(item2.driver_name, 'i') });
    fireEvent.click(case2Button);

    await act(async () => { await vi.advanceTimersByTimeAsync(0); });

    // Advance 60s
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });

    // Since case2 has no active lease by me, claimCase should not be called
    expect(api.claimCase).not.toHaveBeenCalled();
  });
});
