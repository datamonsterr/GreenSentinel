import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import * as api from '@/lib/api-client';

vi.mock('@/lib/api-client', () => ({
  fetchCases: vi.fn(),
  fetchCaseHistory: vi.fn(),
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

const mockActiveCase = {
  id: 'case-active-01',
  driver_name: 'Nguyễn Văn Active',
  driver_id: 'drv-active-01',
  vehicle_plate: '29A-111.11',
  priority: 'P1',
  priority_score: 90,
  status: 'ready',
  version: 1,
};

const mockHistoryCase1 = {
  id: 'case-hist-01',
  driver_name: 'Trần Văn History',
  driver_id: 'drv-hist-01',
  vehicle_plate: '30E-999.99',
  priority: 'P2',
  priority_score: 50,
  status: 'resolved',
  version: 3,
  assigned_analyst_name: 'Analyst Pro',
};

const mockHistoryCase2 = {
  id: 'case-hist-02',
  driver_name: 'Lê Văn Dismissed',
  driver_id: 'drv-hist-02',
  vehicle_plate: '51F-888.88',
  priority: 'P1',
  priority_score: 80,
  status: 'dismissed',
  version: 2,
  assigned_analyst_name: 'Senior Analyst',
};

const mockDetailResolved = {
  case: mockHistoryCase1,
  trip: {
    pickup_address: 'Hanoi Opera House',
    dropoff_address: 'Vincom Center',
    status: 'completed',
  },
  conversation: [{ role: 'driver' as const, text: 'Trip was completed normally', occurred_at: '2026-10-01T00:00:00Z' }],
  telemetry_samples: [],
};

describe('Processed Case History in Cockpit Workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [mockActiveCase],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseHistory).mockResolvedValue({
      items: [mockHistoryCase1, mockHistoryCase2],
      total: 2,
      limit: 20,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetailResolved as any);
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({
      id: 'analyst-real',
      name: 'Analyst',
      role: 'analyst', roles: ["analyst"],
    });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({
      session_id: 'session-hist',
      messages: [],
    });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any);
  });

  it('renders Active Queue and Case History tabs and switches between them', async () => {
    render(<CockpitWorkspaceView />);

    const activeTab = await screen.findByRole('tab', { name: /active queue/i });
    const historyTab = screen.getByRole('tab', { name: /case history/i });
    expect(activeTab).toBeInTheDocument();
    expect(historyTab).toBeInTheDocument();

    // Initially loads active queue
    expect(api.fetchCases).toHaveBeenCalled();
    expect(api.fetchCaseHistory).not.toHaveBeenCalled();

    // Click Case History tab
    fireEvent.click(historyTab);

    await waitFor(() => {
      expect(api.fetchCaseHistory).toHaveBeenCalledWith(
        expect.objectContaining({
          limit: 20,
          offset: 0,
        })
      );
    });

    // History cases are displayed in the queue
    const historyElements = await screen.findAllByText('Trần Văn History');
    expect(historyElements.length).toBeGreaterThan(0);
    expect(screen.getByText('Lê Văn Dismissed')).toBeInTheDocument();
  });

  it('filters history cases by search query (driver name/plate/id)', async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: /case history/i }));

    const searchInput = screen.getByRole('textbox', {
      name: /search cases by driver identity or vehicle plate/i,
    });

    fireEvent.change(searchInput, { target: { value: '30E-999' } });

    await waitFor(() => {
      expect(api.fetchCaseHistory).toHaveBeenCalledWith(
        expect.objectContaining({
          search: '30E-999',
        })
      );
    });
  });

  it('filters history cases by status dropdown in history mode', async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: /case history/i }));

    const statusFilter = await screen.findByRole('combobox', {
      name: /case history status filter/i,
    });
    expect(statusFilter).toBeInTheDocument();

    fireEvent.change(statusFilter, { target: { value: 'dismissed' } });

    await waitFor(() => {
      expect(api.fetchCaseHistory).toHaveBeenCalledWith(
        expect.objectContaining({
          status: 'dismissed',
        })
      );
    });
  });

  it('displays read-only terminal status badge and decision banner without claim buttons', async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: /case history/i }));

    // Select the resolved history case from the queue row.
    const queue = screen.getByRole('region', { name: /triage queue/i });
    const historyItems = await within(queue).findAllByText('Trần Văn History');
    fireEvent.click(historyItems[0]);

    // Terminal status badge is shown
    const resolvedCard = historyItems[0].closest('article')!;
    const badge = within(resolvedCard).getByTestId('terminal-status-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/archived · (reviewed|đã thẩm định)/i);

    // Claim button is not rendered
    expect(screen.queryByRole('button', { name: /claim case/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /release case/i })).not.toBeInTheDocument();

    // Read-only decision banner is displayed instead of the decision rationale input
    const banner = await screen.findByTestId('terminal-decision-banner');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/case finalized · version 3/i);
    expect(banner).toHaveTextContent(/preserved archive · read-only/i);
    expect(screen.queryByRole('textbox', { name: 'Decision rationale' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Complete' }));
    expect(screen.getByRole('textbox', { name: 'Decision rationale' })).toBeDisabled();

    // Viewing history does not trigger any claim or action mutation API calls
    expect(api.claimCase).not.toHaveBeenCalled();
    expect(api.adjudicateCase).not.toHaveBeenCalled();
    expect(api.recordCaseAction).not.toHaveBeenCalled();
  }, 10_000);

  it('supports pagination in history mode when total records exceed limit', async () => {
    vi.mocked(api.fetchCaseHistory).mockResolvedValueOnce({
      items: [mockHistoryCase1],
      total: 45,
      limit: 20,
      offset: 0,
    });

    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: /case history/i }));

    expect(await screen.findByText('1-20 of 45')).toBeInTheDocument();
    const nextButton = screen.getByRole('button', { name: /next history page/i });
    expect(nextButton).toBeEnabled();

    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(api.fetchCaseHistory).toHaveBeenCalledWith(
        expect.objectContaining({
          offset: 20,
        })
      );
    });
  });
});
