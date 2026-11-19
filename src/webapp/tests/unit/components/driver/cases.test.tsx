import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { DriverCaseCard } from '@/components/driver/cases/driver-case-card';
import { DriverCasesView } from '@/components/driver/cases/driver-cases-view';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import * as api from '@/lib/api-client';
import type { DriverCaseSessionItem } from '@/types/schemas';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
}));

vi.mock('@/lib/api-client', () => ({
  fetchDriverCases: vi.fn(),
}));

const sampleOpenCase: DriverCaseSessionItem = {
  case_id: '018f2f4e-a000-7000-8000-000000001234',
  case_code: '#1234',
  driver_id: 'drv-secret-uuid-999',
  driver_name: 'Nguyễn Văn Hưng',
  violation_code: 'ERR-01',
  violation_title: 'Chậm trễ đón khách',
  dispute_status: 'not_disputed',
  status: 'open',
  dispute_deadline: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
  created_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  alleged_time: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  description: 'Xe tiếp cận điểm đón chậm 15 phút so với quy chuẩn lộ trình',
  trip_id: 'trip-raw-secret-777',
  source: 'system_detected',
};

const sampleResolvedCase: DriverCaseSessionItem = {
  case_id: '018f2f4e-b000-7000-8000-000000005678',
  case_code: '#5678',
  driver_id: 'drv-secret-uuid-999',
  driver_name: 'Nguyễn Văn Hưng',
  violation_code: 'ERR-05',
  violation_title: 'Sai lệch lộ trình di chuyển',
  dispute_status: 'resolved',
  status: 'closed',
  dispute_deadline: null,
  created_at: new Date(Date.now() - 86400 * 3 * 1000).toISOString(),
  alleged_time: new Date(Date.now() - 86400 * 3 * 1000).toISOString(),
  description: 'Lộ trình di chuyển sai lệch do né điểm ngập nước',
  trip_id: 'trip-raw-secret-888',
  source: 'customer_report',
};

describe('DriverCaseCard Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders short case code, brief title, natural status pill, and relative time', () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={sampleOpenCase} />
      </DriverI18nProvider>
    );

    // Short case ID formatted from UUID
    expect(screen.getByText('#1234')).toBeInTheDocument();

    // Localized violation title from VIOLATION_TITLE_MAP
    expect(
      screen.getByText('Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt')
    ).toBeInTheDocument();

    // Natural status pill (from status-copy)
    expect(screen.getByText('Chưa khiếu nại')).toBeInTheDocument();

    // Response deadline hint present when available
    expect(screen.getByText(/phản hồi/i)).toBeInTheDocument();
  });

  it('navigates to /driver/chat/[caseId] when tapped', () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={sampleOpenCase} />
      </DriverI18nProvider>
    );

    const card = screen.getByRole('button', { name: /#1234/i });
    fireEvent.click(card);

    expect(mockPush).toHaveBeenCalledWith(`/driver/chat/${sampleOpenCase.case_id}`);
  });

  it('omits response deadline hint when deadline is null or not provided', () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={sampleResolvedCase} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('#5678')).toBeInTheDocument();
    expect(screen.queryByText(/Còn.*để phản hồi/i)).not.toBeInTheDocument();
  });

  it('omits response deadline hint for an OPEN case when dispute_deadline is null', () => {
    const openNullDeadline: DriverCaseSessionItem = {
      ...sampleOpenCase,
      case_id: '018f2f4e-c000-7000-8000-000000009999',
      dispute_deadline: null,
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={openNullDeadline} />
      </DriverI18nProvider>
    );

    expect(screen.queryByText(/Còn.*để phản hồi/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/hết hạn/i)).not.toBeInTheDocument();
  });

  it('shows "deadline passed" when dispute_deadline is in the past', () => {
    const pastDeadline: DriverCaseSessionItem = {
      ...sampleOpenCase,
      dispute_deadline: new Date(Date.now() - 3600 * 1000).toISOString(),
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={pastDeadline} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('Đã hết hạn phản hồi')).toBeInTheDocument();
  });

  it('shows hours-remaining hint when deadline is within 24h', () => {
    const hoursDeadline: DriverCaseSessionItem = {
      ...sampleOpenCase,
      dispute_deadline: new Date(Date.now() + 5 * 3600 * 1000).toISOString(),
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={hoursDeadline} />
      </DriverI18nProvider>
    );

    expect(screen.getByText(/Còn \d+ giờ để phản hồi/)).toBeInTheDocument();
  });

  it('shows days-remaining hint when deadline is more than 24h out', () => {
    const daysDeadline: DriverCaseSessionItem = {
      ...sampleOpenCase,
      dispute_deadline: new Date(Date.now() + 3 * 24 * 3600 * 1000).toISOString(),
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={daysDeadline} />
      </DriverI18nProvider>
    );

    expect(screen.getByText(/Còn \d+ ngày để phản hồi/)).toBeInTheDocument();
  });

  it('NEVER renders "NaN" when dispute_deadline is an invalid date string', () => {
    const invalidDeadline: DriverCaseSessionItem = {
      ...sampleOpenCase,
      dispute_deadline: 'not-a-real-date',
    };

    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={invalidDeadline} />
      </DriverI18nProvider>
    );

    expect(container.textContent || '').not.toContain('NaN');
    expect(screen.queryByText(/Còn.*để phản hồi/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Đã hết hạn phản hồi')).not.toBeInTheDocument();
  });

  it('NEVER renders "NaN" and falls back to "Gần đây" when alleged_time is invalid', () => {
    const invalidTime: DriverCaseSessionItem = {
      ...sampleOpenCase,
      alleged_time: 'garbage-timestamp',
      created_at: 'garbage-timestamp',
    };

    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={invalidTime} />
      </DriverI18nProvider>
    );

    expect(container.textContent || '').not.toContain('NaN');
    expect(screen.getByText('Gần đây')).toBeInTheDocument();
  });

  describe('Relative time calendar-date buckets', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('treats 23:50 yesterday viewed at 00:10 today as "Yesterday", not "Today"', () => {
      // "Now" is 00:10 local time, 2026-01-02.
      vi.setSystemTime(new Date(2026, 0, 2, 0, 10, 0));

      // Alleged time was 23:50 on 2026-01-01 (only 20 minutes earlier in ms,
      // but a different calendar day).
      const lateYesterday: DriverCaseSessionItem = {
        ...sampleOpenCase,
        alleged_time: new Date(2026, 0, 1, 23, 50, 0).toISOString(),
        created_at: new Date(2026, 0, 1, 23, 50, 0).toISOString(),
      };

      render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <DriverCaseCard item={lateYesterday} />
        </DriverI18nProvider>
      );

      expect(screen.getByText(/Hôm qua,/)).toBeInTheDocument();
      expect(screen.queryByText(/Hôm nay,/)).not.toBeInTheDocument();
    });

    it('treats a timestamp earlier today as "Today"', () => {
      vi.setSystemTime(new Date(2026, 0, 2, 12, 0, 0));

      const earlierToday: DriverCaseSessionItem = {
        ...sampleOpenCase,
        alleged_time: new Date(2026, 0, 2, 8, 0, 0).toISOString(),
        created_at: new Date(2026, 0, 2, 8, 0, 0).toISOString(),
      };

      render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <DriverCaseCard item={earlierToday} />
        </DriverI18nProvider>
      );

      expect(screen.getByText(/Hôm nay,/)).toBeInTheDocument();
    });

    it('buckets 3 days ago as "{count} ngày trước"', () => {
      vi.setSystemTime(new Date(2026, 0, 10, 12, 0, 0));

      const threeDaysAgo: DriverCaseSessionItem = {
        ...sampleOpenCase,
        alleged_time: new Date(2026, 0, 7, 9, 0, 0).toISOString(),
        created_at: new Date(2026, 0, 7, 9, 0, 0).toISOString(),
      };

      render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <DriverCaseCard item={threeDaysAgo} />
        </DriverI18nProvider>
      );

      expect(screen.getByText('3 ngày trước')).toBeInTheDocument();
    });
  });

  it('STRICT PRIVACY: never renders raw UUID, trip id, driver id, violation code, or raw description', () => {
    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={sampleOpenCase} />
      </DriverI18nProvider>
    );

    const textContent = container.textContent || '';
    const innerHTML = container.innerHTML || '';

    // Must not leak UUID
    expect(textContent).not.toContain('018f2f4e-a000-7000-8000-000000001234');
    expect(innerHTML).not.toContain('018f2f4e-a000-7000-8000-000000001234');

    // Must not leak trip_id
    expect(textContent).not.toContain('trip-raw-secret-777');
    expect(innerHTML).not.toContain('trip-raw-secret-777');

    // Must not leak driver_id
    expect(textContent).not.toContain('drv-secret-uuid-999');
    expect(innerHTML).not.toContain('drv-secret-uuid-999');

    // Must not leak raw internal code ERR-01
    expect(textContent).not.toContain('ERR-01');

    // Must not leak raw backend description
    expect(textContent).not.toContain('Xe tiếp cận điểm đón chậm 15 phút');

    // Must not render source badge / emoji
    expect(textContent).not.toContain('🤖');
    expect(textContent).not.toContain('Sentinel AI');
    expect(textContent).not.toContain('👤');
    expect(textContent).not.toContain('Khách báo');
  });

  it('supports light and dark theme styling classes', () => {
    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCaseCard item={sampleOpenCase} />
      </DriverI18nProvider>
    );

    const card = container.querySelector('[role="button"]');
    expect(card?.className).toMatch(/dark:bg-/);
    expect(card?.className).toMatch(/dark:border-/);
  });
});

describe('DriverCasesView (Cases Tab)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders header with count and Open / Resolved segmented control', async () => {
    vi.mocked(api.fetchDriverCases).mockResolvedValue({
      items: [sampleOpenCase, sampleResolvedCase],
      total: 2,
    });

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    // Header count
    expect(await screen.findByText(/Vụ việc của bạn/i)).toBeInTheDocument();
    expect(screen.getByText('(2)')).toBeInTheDocument();

    // Segmented control tabs
    const openTab = screen.getByRole('button', { name: /Đang mở/i });
    const resolvedTab = screen.getByRole('button', { name: /Đã đóng/i });
    expect(openTab).toBeInTheDocument();
    expect(resolvedTab).toBeInTheDocument();

    // Default is "all"; Open tab shows only sampleOpenCase
    expect(screen.getByText('#5678')).toBeInTheDocument();
    fireEvent.click(openTab);
    expect(screen.getByText('#1234')).toBeInTheDocument();
    expect(screen.queryByText('#5678')).not.toBeInTheDocument();

    // Switch to Resolved tab
    fireEvent.click(resolvedTab);
    expect(await screen.findByText('#5678')).toBeInTheDocument();
    expect(screen.queryByText('#1234')).not.toBeInTheDocument();
  });

  it('renders loading skeleton while fetching data', () => {
    vi.mocked(api.fetchDriverCases).mockReturnValue(new Promise(() => {})); // Never resolves

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    expect(screen.getByTestId('cases-loading-skeleton')).toBeInTheDocument();
  });

  it('renders empty state when there are no cases in tab', async () => {
    vi.mocked(api.fetchDriverCases).mockResolvedValue({
      items: [],
      total: 0,
    });

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId('cases-empty-state')).toBeInTheDocument();
  });

  it('renders error state with retry button on network failure', async () => {
    vi.mocked(api.fetchDriverCases).mockRejectedValueOnce(new Error('Network error'));

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId('cases-error-state')).toBeInTheDocument();
    const retryBtn = screen.getByRole('button', { name: /Thử lại/i });
    expect(retryBtn).toBeInTheDocument();

    // Resolves on retry
    vi.mocked(api.fetchDriverCases).mockResolvedValueOnce({
      items: [sampleOpenCase],
      total: 1,
    });
    fireEvent.click(retryBtn);

    expect(await screen.findByText('#1234')).toBeInTheDocument();
  });

  it('segments an "upheld" dispute_status case into Resolved, not Open', async () => {
    const upheldCase: DriverCaseSessionItem = {
      ...sampleOpenCase,
      case_id: '018f2f4e-d000-7000-8000-000000004321',
      dispute_status: 'upheld',
      status: 'open',
    };

    vi.mocked(api.fetchDriverCases).mockResolvedValue({
      items: [sampleOpenCase, upheldCase],
      total: 2,
    });

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    await screen.findByText('#1234');
    fireEvent.click(screen.getByRole('button', { name: /Đang mở/i }));
    expect(screen.queryByText('#4321')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Đã đóng/i }));
    expect(await screen.findByText('#4321')).toBeInTheDocument();
    expect(screen.queryByText('#1234')).not.toBeInTheDocument();
  });

  it('renders properly in English locale', async () => {
    vi.mocked(api.fetchDriverCases).mockResolvedValue({
      items: [sampleOpenCase],
      total: 1,
    });

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverCasesView />
      </DriverI18nProvider>
    );

    expect(await screen.findByText(/Your cases/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Closed/i })).toBeInTheDocument();
  });
});
