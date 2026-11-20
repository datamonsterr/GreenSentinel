import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
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

const mockCase1 = {
  id: 'case-01',
  driver_name: 'Nguyễn Văn Bình',
  driver_id: 'drv-binh-01',
  vehicle_plate: '29E-123.45',
  priority: 'P1',
  priority_score: 90,
  status: 'ready',
  version: 1,
};

const mockDetail = {
  case: mockCase1,
  trip: {},
  conversation: [],
};

describe('Case Search in Cockpit Triage Queue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [mockCase1],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetail);
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({
      id: 'analyst-real',
      name: 'Analyst',
      role: 'analyst', roles: ["analyst"],
    });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({
      session_id: 'session-empty',
      messages: [],
    });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any);
  });

  it('renders search input in triage queue with appropriate placeholder and accessible label', async () => {
    render(<CockpitWorkspaceView />);
    const searchInput = await screen.findByRole('textbox', {
      name: /search cases by driver identity or vehicle plate/i,
    });
    expect(searchInput).toBeInTheDocument();
    expect(searchInput).toHaveAttribute('placeholder', 'Search driver, plate, ID…');
  });

  it('triggers fetchCases with search parameter when user inputs query', async () => {
    render(<CockpitWorkspaceView />);
    const searchInput = await screen.findByRole('textbox', {
      name: /search cases by driver identity or vehicle plate/i,
    });

    fireEvent.change(searchInput, { target: { value: '29E-123' } });

    await waitFor(() => {
      expect(api.fetchCases).toHaveBeenCalledWith(
        expect.objectContaining({
          availability: 'available',
          search: '29E-123',
        })
      );
    });
  });

  it('provides a clear button to reset search and re-fetch without search parameter', async () => {
    render(<CockpitWorkspaceView />);
    const searchInput = await screen.findByRole('textbox', {
      name: /search cases by driver identity or vehicle plate/i,
    });

    fireEvent.change(searchInput, { target: { value: 'Bình' } });
    const clearButton = await screen.findByRole('button', { name: /clear search/i });
    expect(clearButton).toBeInTheDocument();

    fireEvent.click(clearButton);
    expect(searchInput).toHaveValue('');

    await waitFor(() => {
      expect(api.fetchCases).toHaveBeenCalledWith(
        expect.objectContaining({
          availability: 'available',
          search: undefined,
        })
      );
    });
  });

  it('displays empty state message when no cases match search', async () => {
    vi.mocked(api.fetchCases).mockResolvedValueOnce({
      items: [mockCase1],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<CockpitWorkspaceView />);
    const searchInput = await screen.findByRole('textbox', {
      name: /search cases by driver identity or vehicle plate/i,
    });

    vi.mocked(api.fetchCases).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    fireEvent.change(searchInput, { target: { value: 'nonexistent-driver' } });

    expect(await screen.findByText('No cases match search')).toBeInTheDocument();
  });
});
