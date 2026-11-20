import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MotivationCard } from '@/components/adjudication/motivation-card';
import type { CaseMotivationResponse } from '@/types/schemas';

const api = vi.hoisted(() => ({
  getCaseMotivation: vi.fn(), generateCaseMotivation: vi.fn(), saveCaseMotivation: vi.fn(), confirmCaseMotivation: vi.fn(),
}));
vi.mock('@/lib/api-client', () => api);

const base = {
  id: null, version: 0, motive_category: 'subsidy_surge' as const, amount_at_stake_vnd: 15000, confidence: 0.65,
  rationale: 'Có lợi ích tăng thêm; cần đối chiếu.', source: 'rule' as const, status: 'draft' as const,
  signals: [{ code: 'mock_location', value: 2, unit: 'samples' }, { code: 'surge_capture', value: 5000, unit: 'VND' }],
};
const unsaved: CaseMotivationResponse = { assessment: base, persisted: false };
const saved = (patch: object = {}): CaseMotivationResponse => ({ assessment: { ...base, id: 'a1', version: 1, ...patch }, persisted: true });

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe('MotivationCard', () => {
  it('shows structured assessment instead of "Not assessed"', async () => {
    api.getCaseMotivation.mockResolvedValue(unsaved);
    render(<MotivationCard caseId="c1" canWrite locale="en" />);
    expect(await screen.findByText('Subsidy / surge')).toBeInTheDocument();
    expect(screen.getByText('Not saved')).toBeInTheDocument();
    expect(screen.getByText(/Mock GPS samples/)).toBeInTheDocument();
    expect(screen.getByText(/15,000 ₫/)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '65');
    expect(screen.queryByText(/Not assessed/)).not.toBeInTheDocument();
  });

  it('renders Vietnamese labels', async () => {
    api.getCaseMotivation.mockResolvedValue(saved({ status: 'confirmed' }));
    render(<MotivationCard caseId="c1" canWrite locale="vi" />);
    expect(await screen.findByText('Trợ giá / giờ cao điểm')).toBeInTheDocument();
    expect(screen.getByText('Đã xác nhận')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Xác nhận' })).not.toBeInTheDocument();
  });

  it('hides write actions when read-only', async () => {
    api.getCaseMotivation.mockResolvedValue(saved());
    render(<MotivationCard caseId="c1" canWrite={false} locale="en" />);
    await screen.findByText('Subsidy / surge');
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument();
    expect(screen.getByText('Read-only')).toBeInTheDocument();
  });

  it('generates when not persisted', async () => {
    api.getCaseMotivation.mockResolvedValue(unsaved);
    api.generateCaseMotivation.mockResolvedValue(saved());
    render(<MotivationCard caseId="c1" canWrite locale="en" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Generate' }));
    expect(await screen.findByText('Draft')).toBeInTheDocument();
    expect(api.generateCaseMotivation).toHaveBeenCalledWith('c1');
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument();
  });

  it('edits then confirms', async () => {
    api.getCaseMotivation.mockResolvedValue(saved());
    api.saveCaseMotivation.mockResolvedValue(saved({ version: 2, source: 'analyst', motive_category: 'platform_fault', rationale: 'Sự cố' }));
    api.confirmCaseMotivation.mockResolvedValue(saved({ version: 2, source: 'analyst', status: 'confirmed', motive_category: 'platform_fault' }));
    render(<MotivationCard caseId="c1" canWrite locale="en" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Motive category'), { target: { value: 'platform_fault' } });
    fireEvent.change(screen.getByLabelText('Rationale'), { target: { value: 'Sự cố' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.saveCaseMotivation).toHaveBeenCalledWith('c1', expect.objectContaining({ motive_category: 'platform_fault', rationale: 'Sự cố', expected_version: 1 })));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText('Confirmed')).toBeInTheDocument();
    expect(api.confirmCaseMotivation).toHaveBeenCalledWith('c1', 2);
  });

  it('shows error when load fails', async () => {
    api.getCaseMotivation.mockRejectedValue(new Error('x'));
    render(<MotivationCard caseId="c1" canWrite locale="en" />);
    expect(await screen.findByText('Could not load the motivation assessment.')).toBeInTheDocument();
  });

  it('ignores malformed payloads instead of crashing', async () => {
    api.getCaseMotivation.mockResolvedValue({ foo: 'bar' });
    render(<MotivationCard caseId="c1" canWrite locale="en" />);
    expect(await screen.findByText('Could not load the motivation assessment.')).toBeInTheDocument();
  });
});
