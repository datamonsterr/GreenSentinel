import React from 'react';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { afterEach, describe, it, expect, vi } from 'vitest';
import { CenterPanelTabs, type CenterTabType } from '@/components/adjudication/center-panel-tabs';
import { CopyId, OverviewTab, TripFacts } from '@/components/adjudication/overview-tab';
afterEach(cleanup);
const detail = {
  case: { id: 'case-368', version: 5, category: 'SECRET-CLASSIFICATION', confidence: .98 },
  trip: { pickup_address: 'Pickup A', dropoff_address: 'Destination B', fare_amount_vnd: 120000, status: 'picking_up', match_type: 'now' },
  forensic_brief: { case_id: 'case-368', summary_text: 'Vehicle stopped for 210 seconds.', abnormalities: [], evidence_sources: ['telemetry'] },
  telemetry_samples: [{ recorded_at: '2026-10-14T02:00:00Z', position: { coordinates: [105.81, 21.01] } }],
} as any;
describe('#368 five-tab workspace boundary', () => {
  it('routes all five tabs with arrow keys, Home and End', () => {
    function Tabs() { const [tab, setTab] = React.useState<CenterTabType>('overview'); return <CenterPanelTabs activeTab={tab} onTabChange={setTab} />; }
    render(<Tabs />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map(t => t.textContent?.trim())).toEqual(['dashboardOverview', 'mapMaps', 'forumCustomer', 'badgeDriver', 'fact_checkComplete']);
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: 'End' });
    expect(tabs[4]).toHaveFocus();
    expect(tabs[4]).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(tabs[4], { key: 'ArrowRight' });
    expect(tabs[0]).toHaveFocus();
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' });
    expect(tabs[1]).toHaveFocus();
  });
  it('starts Overview with clickable trip facts then behavior, motivation and willingness, without decision inputs', () => {
    const navigate = vi.fn();
    render(<OverviewTab caseDetail={detail} selectedCaseId='case-368' onTabChange={navigate} />);
    const trip = screen.getByRole('button', { name: 'Pickup A → Destination B' });
    fireEvent.click(trip);
    expect(navigate).toHaveBeenCalledWith('maps');
    expect(within(screen.getByTestId('trip-status-row')).getByText('120,000 ₫')).toBeVisible();
    expect(screen.getByText('Vehicle stopped for 210 seconds.')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Motivation' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Willingness' })).toBeVisible();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByText(/SECRET-CLASSIFICATION|98%/)).not.toBeInTheDocument();
  });
  it('missing data shows the designed empty state without a fabricated fare, match or guilt', () => {
    render(<OverviewTab caseDetail={{ case: { id: 'empty' } } as any} selectedCaseId='empty' />);
    expect(screen.getAllByText('No data yet').length).toBeGreaterThan(2);
    expect(screen.queryByText(/Unavailable|undefined|NaN/)).not.toBeInTheDocument();
    expect(screen.queryByText(/85.000|92.5|4.85|ERR-01/)).not.toBeInTheDocument();
  });

  it('keeps the trip copy control outside the route button and copies long IDs only on success', async () => {
    const longTripId = 'TRIP-1234567890ABCDEF';
    const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { container, unmount } = render(<TripFacts caseDetail={{ ...detail, trip: { ...detail.trip, id: longTripId } } as any} onOpen={vi.fn()} />);
    const route = screen.getByRole('button', { name: 'Pickup A → Destination B' });
    const copy = screen.getByRole('button', { name: `Trip ID: ${longTripId}` });
    expect(route.querySelector('button')).toBeNull();
    expect(copy).not.toHaveTextContent(longTripId);
    expect(container.querySelector('button button')).toBeNull();

    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(longTripId));
    await waitFor(() => expect(copy).toHaveTextContent('✓'));
    unmount();
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor);
    else Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('does not show copy success when both clipboard methods fail', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const execDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand');
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn(() => false) });
    render(<CopyId id="CASE-LONG-1234567890" label="Case ID" />);
    const copy = screen.getByRole('button', { name: 'Case ID: CASE-LONG-1234567890' });
    fireEvent.click(copy);
    await waitFor(() => expect(document.execCommand).toHaveBeenCalledWith('copy'));
    expect(copy).not.toHaveTextContent('✓');
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor);
    else Reflect.deleteProperty(navigator, 'clipboard');
    if (execDescriptor) Object.defineProperty(document, 'execCommand', execDescriptor);
    else Reflect.deleteProperty(document, 'execCommand');
  });

  it('Overview tab does not contain a Claim button', () => {
    render(<OverviewTab caseDetail={detail} selectedCaseId="case-368" />);
    expect(screen.queryByRole('button', { name: /Claim/i })).not.toBeInTheDocument();
  });

  it('CopyId renders displayId when provided and copies full underlying id', async () => {
    const fullId = '11111111-2222-3333-4444-555555555555';
    const displayCode = '#11111111';
    const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    render(<CopyId id={fullId} label="Case ID" displayId={displayCode} />);
    const button = screen.getByRole('button', { name: `Case ID: ${fullId}` });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent(displayCode);

    fireEvent.click(button);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(fullId));
    await waitFor(() => expect(button).toHaveTextContent('✓'));

    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor);
    else Reflect.deleteProperty(navigator, 'clipboard');
  });
});
