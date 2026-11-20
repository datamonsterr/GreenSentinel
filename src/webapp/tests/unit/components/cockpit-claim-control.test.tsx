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

describe('Analyst Claim Control & Visibility (#573 Item 1)', () => {
  const caseId = 'c2c8309b-2c1a-4500-81d7-f67ddba42d28';
  const signedInAnalystId = '8ca1823d-0000-4000-8000-000000000001';
  const autoAssignedAnalystId = '0b782846-0000-4000-8000-000000000002';

  const mockCaseItem = {
    id: caseId,
    driver_name: 'Driver 573',
    vehicle_plate: '29E-573.99',
    priority: 'P1',
    priority_score: 85,
    status: 'ready',
    version: 1,
    assigned_analyst_id: autoAssignedAnalystId,
    active_lease_analyst_id: null,
  };

  const mockCaseDetailUnleased = {
    case: mockCaseItem,
    trip: { id: 'trip-573', pickup_address: 'VinUni', dropoff_address: 'Hanoi Center' },
    active_lease: null,
    preliminary_judgment: null,
    assessment: { id: 'assessment-573', category: 'ERR-02', confidence: 0.88, reason_codes: ['stop_too_long'] },
    forensic_brief: { case_id: caseId, summary_text: 'Vehicle stopped for 240 seconds at pickup.' },
    conversation: [],
  };

  const mockCaseDetailClaimed = {
    ...mockCaseDetailUnleased,
    active_lease: { analyst_id: signedInAnalystId, expires_at: '2099-01-01T00:00:00Z' },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [mockCaseItem as any],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockCaseDetailUnleased as any);
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({
      id: signedInAnalystId,
      name: 'Signed-In Analyst',
      role: 'fraud_analyst', roles: ["fraud_analyst"],
    });
    vi.mocked(api.claimCase).mockResolvedValue({ case_id: caseId } as any);
    vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: 'session-573', messages: [] });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any);
  });

  it('allows signed-in fraud_analyst to claim an unleased case assigned to another principal in workload', async () => {
    render(<CockpitWorkspaceView />);

    // Wait for the case to be loaded in queue
    await screen.findByText('Driver 573');

    // 1. The left queue card Claim button must NOT be disabled by assigned_analyst_id
    const claimButtons = screen.getAllByRole('button', { name: /^Claim$|^Nhận$/i });
    expect(claimButtons.length).toBeGreaterThanOrEqual(1);
    expect(claimButtons[0]).toBeEnabled();

    // 2. Overview center panel must provide a visible Claim control banner and button
    const centerClaimButton = await screen.findByRole('button', { name: /Claim case|Nhận vụ việc/i });
    expect(centerClaimButton).toBeVisible();
    expect(centerClaimButton).toBeEnabled();

    // 3. Clicking Claim calls claimCase with the signed-in analyst ID
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockCaseDetailClaimed as any);
    fireEvent.click(centerClaimButton);

    await waitFor(() => {
      expect(api.claimCase).toHaveBeenCalledWith(
        caseId,
        expect.objectContaining({ analyst_id: signedInAnalystId })
      );
    });
  });
});
