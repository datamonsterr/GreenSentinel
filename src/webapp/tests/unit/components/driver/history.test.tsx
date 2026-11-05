import React from 'react';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DriverHistoryPage from '@/app/driver/(tabs)/history/page';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import * as api from '@/lib/api-client';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    fetchDriverTrips: vi.fn(),
    fetchDriverTripsSummary: vi.fn(),
  };
});

let observerInstances: Array<{
  elements: Element[];
  trigger: (isIntersecting?: boolean) => void;
}> = [];

class MockIntersectionObserver {
  elements: Element[] = [];
  constructor(private cb: (entries: Partial<IntersectionObserverEntry>[]) => void) {
    observerInstances.push({
      elements: this.elements,
      trigger: (isIntersecting = true) => {
        this.cb(this.elements.map((el) => ({ isIntersecting, target: el })));
      },
    });
  }
  observe(el: Element) {
    this.elements.push(el);
  }
  unobserve(el: Element) {
    this.elements = this.elements.filter((e) => e !== el);
  }
  disconnect() {
    this.elements = [];
  }
}

const mockSummary = {
  month: '2026-10',
  trip_count: 2,
  total_fare_vnd: 427000,
  total_distance_km: 46.5,
  avg_rating: 4.95,
};

const mockTrips = [
  {
    trip_id: '884aedff-b9d6-5e06-9ba1-f99ccce6d22e',
    pickup_label: 'Sảnh R1, Vinhomes Ocean Park 1',
    dropoff_label: 'Nhà ga T2, Sân bay Quốc tế Nội Bài',
    started_at: '2026-10-24T08:15:00Z',
    ended_at: '2026-10-24T09:02:00Z',
    distance_km: 32.0,
    duration_min: 47.0,
    fare_vnd: 285000,
    payment_method: 'wallet',
    payment_method_synthetic: true,
    rating: {
      stars: 5,
      comment: 'Tài xế lái xe êm, xe VF 8 sạch sẽ.',
      locale: 'vi',
      created_at: '2026-10-24T09:05:00Z',
    },
    status: 'completed',
    has_case: false,
    case_id: null,
  },
  {
    trip_id: '994aedff-c9d6-5e06-9ba1-f99ccce6d33f',
    pickup_label: 'Tòa Landmark 81, Vinhomes Central Park',
    dropoff_label: 'Bitexco Financial Tower, Q.1',
    started_at: '2026-10-24T11:30:00Z',
    ended_at: '2026-10-24T12:05:00Z',
    distance_km: 14.5,
    duration_min: 35.0,
    fare_vnd: 142000,
    payment_method: 'credit_card',
    payment_method_synthetic: true,
    rating: null,
    status: 'completed',
    has_case: true,
    case_id: '018f2f4e-case-7000-8000-000000000002',
  },
];

describe('Driver History Tab Page & Components', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    observerInstances = [];
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
    vi.mocked(api.fetchDriverTripsSummary).mockResolvedValue(mockSummary);
    vi.mocked(api.fetchDriverTrips).mockResolvedValue({
      trips: mockTrips,
      total: 2,
      next_cursor: null,
      counts: { all: 2, completed: 1, flagged: 1 },
    });
  });

  it('renders monthly summary card with formatted fare and stats', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText(/427\.000/)[0]).toBeInTheDocument();
    });

    expect(screen.getByText(/46[,.]5/)).toBeInTheDocument();
    expect(screen.getByText('4.95')).toBeInTheDocument();
  });

  it('renders segmented filter tabs and filters trips', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });

    // Verify segmented tab exists and can be clicked
    const completedTab = screen.getByRole('tab', { name: /Hoàn thành/i });
    expect(completedTab).toBeInTheDocument();

    fireEvent.click(completedTab);
    expect(api.fetchDriverTrips).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'completed' })
    );
  });

  it('renders route details, fare, rating stars and customer quote', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });

    expect(screen.getByText('Nhà ga T2, Sân bay Quốc tế Nội Bài')).toBeInTheDocument();
    expect(screen.getByText(/285\.000/)).toBeInTheDocument();
    expect(screen.getByText(/Tài xế lái xe êm/)).toBeInTheDocument();
  });

  it('renders unrated trips with "Not rated" copy and flagged banner linking to chat', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Tòa Landmark 81, Vinhomes Central Park')).toBeInTheDocument();
    });

    // Unrated trip displays "Chưa đánh giá"
    expect(screen.getByText(/Chưa đánh giá/i)).toBeInTheDocument();

    // Flagged trip has link/button that navigates to /driver/chat/[caseId].
    // The link text must be a neutral label, never the raw/short case id (case id is navigation-only).
    const disputeLink = screen.getByRole('link', { name: /Xem vụ việc/i });
    expect(disputeLink).toBeInTheDocument();
    expect(disputeLink).toHaveAttribute('href', '/driver/chat/018f2f4e-case-7000-8000-000000000002');
    expect(disputeLink.textContent).not.toMatch(/#/);
  });

  it('never renders raw UUIDs or internal codes', async () => {
    const { container } = render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });

    const html = container.innerHTML;
    expect(html).not.toContain('884aedff-b9d6-5e06-9ba1-f99ccce6d22e');
    expect(html).not.toContain('ERR-01');
    expect(html).not.toContain('AUTO_DISMISSED');
  });

  it('renders empty state when no trips exist', async () => {
    vi.mocked(api.fetchDriverTrips).mockResolvedValue({
      trips: [],
      total: 0,
      next_cursor: null,
      counts: { all: 0, completed: 0, flagged: 0 },
    });

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Chưa có chuyến đi/i)).toBeInTheDocument();
    });
  });

  it('flagged card click navigates to /driver/chat/<caseId>', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Tòa Landmark 81, Vinhomes Central Park')).toBeInTheDocument();
    });

    const flaggedCard = screen.getByText('Tòa Landmark 81, Vinhomes Central Park').closest('article');
    expect(flaggedCard).not.toBeNull();
    fireEvent.click(flaggedCard as HTMLElement);

    expect(mockPush).toHaveBeenCalledWith('/driver/chat/018f2f4e-case-7000-8000-000000000002');
  });

  it('shows tab badges sourced from backend counts, not the current page', async () => {
    vi.mocked(api.fetchDriverTrips).mockResolvedValue({
      trips: mockTrips,
      total: 2,
      next_cursor: null,
      counts: { all: 11, completed: 7, flagged: 4 },
    });

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Tất cả/i })).toHaveTextContent('11');
    });
    expect(screen.getByRole('tab', { name: /Hoàn thành/i })).toHaveTextContent('7');
    expect(screen.getByRole('tab', { name: /Có vấn đề/i })).toHaveTextContent('4');
  });

  it('shows an error state with retry when the trips request fails, without clobbering a working summary', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(api.fetchDriverTrips).mockRejectedValue(new Error('API Error 500: Server error'));

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Thử lại')).toBeInTheDocument();
    });

    expect(screen.getByText('Không thể tải chuyến đi')).toBeInTheDocument();
    expect(screen.getByText('Vui lòng kiểm tra kết nối mạng và thử lại.')).toBeInTheDocument();
    expect(screen.queryByText(/500|Server error/)).not.toBeInTheDocument();

    expect(consoleSpy).toHaveBeenCalledWith(500);

    vi.mocked(api.fetchDriverTrips).mockResolvedValue({
      trips: mockTrips,
      total: 2,
      next_cursor: null,
      counts: { all: 2, completed: 1, flagged: 1 },
    });
    fireEvent.click(screen.getByTestId('driver-history-retry'));

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });
    consoleSpy.mockRestore();
  });

  it('a failed summary request shows an inline summary error but keeps the trip list intact', async () => {
    vi.mocked(api.fetchDriverTripsSummary).mockRejectedValue(new Error('summary down'));

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });
    // Trips still render even though the summary card failed.
    expect(screen.queryByText(/Chưa có chuyến đi/i)).not.toBeInTheDocument();
  });

  it('month picker steps the selected month and refetches', async () => {
    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });

    vi.mocked(api.fetchDriverTrips).mockClear();
    fireEvent.click(screen.getByLabelText('Tháng trước'));

    await waitFor(() => {
      expect(api.fetchDriverTrips).toHaveBeenCalled();
    });
    const lastCallArgs = vi.mocked(api.fetchDriverTrips).mock.calls.at(-1)?.[0];
    expect(lastCallArgs?.month).toBeDefined();
  });

  it('loads more trips on scroll via IntersectionObserver sentinel, dedupes by trip_id across pages', async () => {
    const extraTrip = {
      trip_id: 'extra-trip-uuid-0001',
      pickup_label: 'Extra pickup',
      dropoff_label: 'Extra dropoff',
      started_at: '2026-10-20T08:00:00Z',
      ended_at: '2026-10-20T08:30:00Z',
      distance_km: 5.0,
      duration_min: 15.0,
      fare_vnd: 50000,
      payment_method: 'wallet',
      payment_method_synthetic: true,
      rating: null,
      status: 'completed',
      has_case: false,
      case_id: null,
    };

    vi.mocked(api.fetchDriverTrips).mockResolvedValueOnce({
      trips: mockTrips,
      total: 3,
      next_cursor: 'cursor-page-2',
      counts: { all: 3, completed: 2, flagged: 1 },
    });
    // Second page intentionally repeats a trip_id already shown (dedupe must drop it).
    vi.mocked(api.fetchDriverTrips).mockResolvedValueOnce({
      trips: [mockTrips[1], extraTrip],
      total: 3,
      next_cursor: null,
      counts: { all: 3, completed: 2, flagged: 1 },
    });

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
    });

    expect(observerInstances.length).toBeGreaterThan(0);
    observerInstances[observerInstances.length - 1].trigger(true);

    await waitFor(() => {
      expect(screen.getByText('Extra pickup')).toBeInTheDocument();
    });

    // The repeated trip_id (mockTrips[1]) appears exactly once across both pages.
    const html = document.body.innerHTML;
    const occurrences = html.split('Tòa Landmark 81, Vinhomes Central Park').length - 1;
    expect(occurrences).toBe(1);
  });

  it('ignores a stale load-more response after the filter changed mid-flight', async () => {
    let resolveSecondPage!: (value: Awaited<ReturnType<typeof api.fetchDriverTrips>>) => void;

    vi.mocked(api.fetchDriverTrips).mockResolvedValueOnce({
      trips: mockTrips,
      total: 3,
      next_cursor: 'cursor-page-2',
      counts: { all: 3, completed: 2, flagged: 1 },
    });

    render(
      <DriverI18nProvider locale="vi">
        <DriverHistoryPage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Sảnh R1, Vinhomes Ocean Park 1')).toBeInTheDocument();
      // The trip DOM can commit before the observer's passive effect runs.
      expect(observerInstances.length).toBeGreaterThan(0);
      expect(observerInstances[observerInstances.length - 1].elements).toHaveLength(1);
    });

    // Load-more request hangs ("in flight").
    const secondPage = new Promise<Awaited<ReturnType<typeof api.fetchDriverTrips>>>((resolve) => {
      resolveSecondPage = resolve;
    });
    vi.mocked(api.fetchDriverTrips).mockReturnValueOnce(secondPage);
    await act(async () => {
      observerInstances[observerInstances.length - 1].trigger(true);
    });
    expect(api.fetchDriverTrips).toHaveBeenCalledTimes(2);
    expect(api.fetchDriverTrips).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: 'cursor-page-2', status: undefined })
    );
    expect(screen.getByRole('button', { name: /Tải thêm chuyến đi/i })).toBeDisabled();

    // User switches tab while the load-more request is still pending: new filter generation.
    vi.mocked(api.fetchDriverTrips).mockResolvedValueOnce({
      trips: [],
      total: 0,
      next_cursor: null,
      counts: { all: 0, completed: 0, flagged: 0 },
    });
    fireEvent.click(screen.getByRole('tab', { name: /Hoàn thành/i }));

    await waitFor(() => {
      expect(screen.getByText(/Chưa có chuyến đi/i)).toBeInTheDocument();
    });
    expect(api.fetchDriverTrips).toHaveBeenCalledTimes(3);
    expect(api.fetchDriverTrips).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'completed' })
    );

    // The stale load-more now resolves; it must be ignored (must not resurrect old trips).
    await act(async () => {
      resolveSecondPage({
        trips: [mockTrips[1]],
        total: 3,
        next_cursor: null,
        counts: { all: 3, completed: 2, flagged: 1 },
      });
      await secondPage;
    });

    expect(screen.queryByText('Tòa Landmark 81, Vinhomes Central Park')).not.toBeInTheDocument();
    expect(screen.getByText(/Chưa có chuyến đi/i)).toBeInTheDocument();
  });
});
