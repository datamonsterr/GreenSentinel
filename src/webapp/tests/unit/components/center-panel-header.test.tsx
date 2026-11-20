import React from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { CockpitWorkspaceView } from '@/components/views/cockpit-view';
import * as api from '@/lib/api-client';

vi.mock('@/lib/api-client', () => ({
  fetchCases: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  fetchCaseDriverScorecard: vi.fn().mockResolvedValue({ driver_id: 'driver-1', past_incidents: [] }),
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

const mockCaseItem = {
  id: 'case-test-123',
  driver_name: 'Nguyễn Văn Hùng',
  vehicle_plate: '29E-999.88',
  priority: 'P1',
  priority_score: 95,
  status: 'ready',
  version: 2,
};

const mockDetailEnriched = {
  case: mockCaseItem,
  trip: {
    id: 'trip-abc',
    driver_name: 'Nguyễn Văn Hùng',
    driver_avatar_url: 'https://api.dicebear.com/7.x/bottts/svg?seed=drv_test_1',
    vehicle_plate: '29E-999.88',
    vehicle_type: 'GreenCar (VF e34)',
    rating: 4.92,
    acceptance_rate: 96.5,
    cancellation_rate: 1.2,
    total_trips: 1840,
    driver_status: 'active',
    pickup_address: 'Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm',
    dropoff_address: 'Sân bay Quốc tế Nội Bài, Sóc Sơn',
    fare_amount_vnd: 245000,
    status: 'picking_up',
    match_type: 'now',
  },
  conversation: [],
  telemetry_samples: [{ position: { coordinates: [105.8, 21.0] }, recorded_at: '2026-10-01T08:00:00Z' }],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [mockCaseItem], total: 1, limit: 50, offset: 0 });
  vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: 'analyst-1', name: 'Analyst Test', role: 'analyst', roles: ["analyst"] });
  vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: 'session-1', messages: [] });
});
afterEach(() => cleanup());

describe('Workspace detail placement without the duplicated center header', () => {
  it('keeps driver identity and plate in the queue while removing the center header', async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetailEnriched);
    render(<CockpitWorkspaceView />);

    const queue = await screen.findByRole('region', { name: 'Triage queue' });
    expect(await within(queue).findByText('Nguyễn Văn Hùng')).toBeVisible();
    expect(within(queue).getByText('29E-999.88')).toBeVisible();
    expect(screen.queryByRole('group', { name: 'Case header' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Nguyễn Văn Hùng' })).not.toBeInTheDocument();
    const overview = await screen.findByRole('tabpanel', { name: 'Overview' });
    expect(within(overview).queryByText('4.92')).not.toBeInTheDocument();
    expect(within(overview).queryByText('GreenCar (VF e34)')).not.toBeInTheDocument();
  });

  it('opens Maps from the factual quickline and shows route, fare, and copyable trip id', async () => {
    const user = userEvent.setup();
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetailEnriched);
    render(<CockpitWorkspaceView />);

    const overview = await screen.findByRole('tabpanel', { name: 'Overview' });
    await user.click(within(overview).getByRole('button', { name: /Hồ Hoàn Kiếm.*Nội Bài/ }));
    const maps = await screen.findByRole('tabpanel', { name: 'Maps' });
    expect(within(maps).getByText('Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm')).toBeVisible();
    expect(within(maps).getByText('Sân bay Quốc tế Nội Bài, Sóc Sơn')).toBeVisible();
    expect(within(maps).getByText('245,000 ₫')).toBeVisible();
    expect(within(maps).getByRole('button', { name: 'Trip ID: trip-abc' })).toBeVisible();
  });

  it('uses current trip values and confines driver operational metrics to Driver', async () => {
    const user = userEvent.setup();
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...mockDetailEnriched,
      trip: { ...mockDetailEnriched.trip, status: 'coming', match_type: 'auto', fare_amount_vnd: 120000 },
    });
    render(<CockpitWorkspaceView />);

    await user.click(await screen.findByRole('tab', { name: 'Maps' }));
    const maps = await screen.findByRole('tabpanel', { name: 'Maps' });
    expect(within(maps).getByText('Active')).toBeVisible();
    expect(within(maps).getByText('Automatic')).toBeVisible();
    expect(within(maps).getByText('120,000 ₫')).toBeVisible();
    await user.click(within(screen.getByRole('tablist', { name: 'Case views' })).getByRole('tab', { name: 'Driver' }));
    const driver = screen.getByRole('tabpanel', { name: 'Driver' });
    expect(within(driver).getByText('4.92')).toBeVisible();
    expect(within(driver).getByText('96.5%')).toBeVisible();
    expect(within(driver).getByText('1.2%')).toBeVisible();
    expect(within(driver).getByText('1,840')).toBeVisible();
    expect(within(driver).getByText(/Nguyễn Văn Hùng/)).toBeVisible();
    expect(within(driver).getByText(/29E-999.88/)).toBeVisible();
  });
});
