import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DriverProfilePage from '@/app/driver/(tabs)/profile/page';
import { DriverProfileView } from '@/components/driver/profile/driver-profile-view';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import * as api from '@/lib/api-client';
import type { DriverProfileResponse, DriverFeedbackResponse } from '@/types/schemas';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';
import {
  ProfileRatingSummary,
  ProfileKpiGrid,
  ProfileHeader,
  ProfileWeeklySparkline,
} from '@/components/driver/profile';

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    fetchDriverProfile: vi.fn(),
    fetchDriverFeedback: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
}));

type MockUser = { id: string; fullName: string; firstName: string; imageUrl: string };

const mockUseUser = vi.fn((): { user: MockUser | null; isLoaded: boolean; isSignedIn: boolean } => ({
  user: {
    id: 'drv-profile-100',
    fullName: 'Nguyễn Văn An',
    firstName: 'An',
    imageUrl: '',
  },
  isLoaded: true,
  isSignedIn: true,
}));

vi.mock('@clerk/nextjs', () => ({
  useUser: () => mockUseUser(),
}));


const mockProfile: DriverProfileResponse = {
  driver_id: 'drv-profile-100',
  display_name: 'Nguyễn Văn An',
  vehicle: {
    model: 'VinFast VF e34',
    plate: '30A-123.45',
  },
  member_since: '2023-04-15T00:00:00Z',
  rating_average: 4.8,
  rated_count: 1204,
  distribution: {
    '5': 1060,
    '4': 96,
    '3': 24,
    '2': 12,
    '1': 12,
  },
  weekly_trend: [
    { week_label: 'W1', week_start: '2026-08-24', average_rating: 4.75, rated_count: 15 },
    { week_label: 'W2', week_start: '2026-08-31', average_rating: 4.80, rated_count: 18 },
    { week_label: 'W3', week_start: '2026-09-07', average_rating: 4.87, rated_count: 22 },
    { week_label: 'W4', week_start: '2026-09-14', average_rating: 4.92, rated_count: 30 },
    { week_label: 'W5', week_start: '2026-09-21', average_rating: 4.85, rated_count: 20 },
    { week_label: 'W6', week_start: '2026-09-28', average_rating: 4.88, rated_count: 25 },
    { week_label: 'W7', week_start: '2026-10-05', average_rating: 4.90, rated_count: 28 },
    { week_label: 'W8', week_start: '2026-10-12', average_rating: 4.95, rated_count: 35 },
  ],
  scorecard: {
    driver_id: 'drv-profile-100',
    violation_ratio_90d: 1.4,
    benchmark_violation_ratio: 5.0,
    fined_ratio: 1.2,
    repeat_offense_risk_score: 1,
    tenure_months: 18,
    total_trips: 1482,
    total_cases: 0,
    past_incidents: [],
  },
};

const mockFeedback: DriverFeedbackResponse = {
  items: [
    {
      id: 'fb-1',
      stars: 5,
      comment: 'Tài xế lái xe êm ái, xe VinFast điện mát mẻ không mùi say xe!',
      date: '2026-10-17T14:20:00Z',
    },
    {
      id: 'fb-2',
      stars: 5,
      comment: null, // Should render as "No comment"
      date: '2026-10-16T09:15:00Z',
    },
  ],
  total: 2,
  next_cursor: null,
};

describe('DriverProfileView Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchDriverProfile).mockResolvedValue(mockProfile);
    vi.mocked(api.fetchDriverFeedback).mockResolvedValue(mockFeedback);
  });

  it('renders driver identity card, rating summary, distribution, KPI grid, and feedback in Vietnamese', async () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverProfileView profile={mockProfile} feedback={mockFeedback} />
      </DriverI18nProvider>
    );

    // Header & identity
    expect(screen.getByText('Nguyễn Văn An')).toBeInTheDocument();
    expect(screen.getByText('VinFast VF e34')).toBeInTheDocument();
    expect(screen.getByText('30A-123.45')).toBeInTheDocument();

    // Rating summary
    expect(screen.getByText('4.8')).toBeInTheDocument();
    expect(screen.getByText(/1\.204/)).toBeInTheDocument();

    // Distribution bars
    expect(screen.getByText(/1\.060/)).toBeInTheDocument();
    expect(screen.getByText(/96/)).toBeInTheDocument();

    // Bento KPI Grid (progressive disclosure tooltips) — measured fields only
    expect(screen.getByText(/1\.482/)).toBeInTheDocument();
    expect(screen.getByText('1.4%')).toBeInTheDocument(); // violation_ratio_90d, measured
    expect(screen.getByText('1.2%')).toBeInTheDocument(); // fined_ratio, measured

    // Fabricated metrics must never render
    expect(screen.queryByText(/Completion Rate|Tỷ lệ hoàn thành/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Reputation Score|Điểm uy tín/)).not.toBeInTheDocument();
    expect(screen.queryByText('Verified Driver')).not.toBeInTheDocument();
    expect(screen.queryByText(/Active & Good Standing|Đang hoạt động tốt/)).not.toBeInTheDocument();

    // Feedback items: real comment & null comment rendered as 'No comment'
    expect(
      screen.getByText(/Tài xế lái xe êm ái/)
    ).toBeInTheDocument();
    // Null comment must render localized "No comment"
    expect(screen.getByText('Khách không để lại nhận xét')).toBeInTheDocument();

    // Invariant: never render raw internal UUID or driver ID
    expect(screen.queryByText('drv-profile-100')).not.toBeInTheDocument();
    expect(screen.queryByText('fb-1')).not.toBeInTheDocument();
    expect(screen.queryByText('fb-2')).not.toBeInTheDocument();
  });

  it('renders in English when locale is set to "en"', async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverProfileView profile={mockProfile} feedback={mockFeedback} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('Driver Profile')).toBeInTheDocument();
    expect(screen.getByText('Overall Rating')).toBeInTheDocument();
    expect(screen.getByText('No comment provided')).toBeInTheDocument();
  });

  it('handles empty ratings and empty feedback states gracefully', async () => {
    const emptyProfile: DriverProfileResponse = {
      driver_id: 'drv-empty',
      display_name: 'Tài xế Mới',
      vehicle: null,
      member_since: null,
      rating_average: null,
      rated_count: 0,
      distribution: { '5': 0, '4': 0, '3': 0, '2': 0, '1': 0 },
      weekly_trend: [],
      scorecard: {
        driver_id: 'drv-empty',
        violation_ratio_90d: 0.0,
        benchmark_violation_ratio: 5.0,
        fined_ratio: 0.0,
        repeat_offense_risk_score: 10,
        tenure_months: 0,
        total_trips: 0,
        total_cases: 0,
        past_incidents: [],
      },
    };

    const emptyFeedback: DriverFeedbackResponse = {
      items: [],
      total: 0,
      next_cursor: null,
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverProfileView profile={emptyProfile} feedback={emptyFeedback} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('Chưa có đánh giá')).toBeInTheDocument();
    expect(screen.getByText('Chưa có nhận xét từ khách hàng')).toBeInTheDocument();
  });

  it('renders null display_name, null stars, and null feedback date without fabricating values', () => {
    // No Clerk fullName/email available either: the generic localized placeholder is the
    // last-resort fallback, never a raw id or fabricated default.
    mockUseUser.mockReturnValueOnce({ user: null, isLoaded: true, isSignedIn: true });

    const unnamedProfile: DriverProfileResponse = {
      ...mockProfile,
      display_name: null,
    };
    const feedbackWithNulls: DriverFeedbackResponse = {
      items: [
        { id: 'fb-3', stars: null, comment: 'Chỉ nhận xét, không chấm sao', date: null },
      ],
      total: 1,
      next_cursor: null,
    };

    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverProfileView profile={unnamedProfile} feedback={feedbackWithNulls} />
      </DriverI18nProvider>
    );

    // display_name null and no Clerk name/email -> localized unnamed placeholder, never a raw default.
    expect(screen.getByText('Tài xế chưa đặt tên')).toBeInTheDocument();
    // stars null -> "No rating" state, never defaulted to 5 stars.
    expect(screen.getByText('Không có đánh giá sao')).toBeInTheDocument();
    // date null -> renders no timestamp element at all.
    expect(container.querySelector('time')).not.toBeInTheDocument();
  });

  it('distribution sums to rated count', () => {
    const totalFromDist = Object.values(mockProfile.distribution).reduce((a, b) => a + b, 0);
    expect(totalFromDist).toBe(mockProfile.rated_count);
  });

  it('page loads and fetches profile and feedback data', async () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverProfilePage />
      </DriverI18nProvider>
    );

    await waitFor(() => {
      expect(api.fetchDriverProfile).toHaveBeenCalled();
      expect(api.fetchDriverFeedback).toHaveBeenCalled();
    });
    expect(await screen.findByText('Nguyễn Văn An')).toBeInTheDocument();
  });

  it('shows localized natural-language error card and logs status only to console.error on fetch failure, retry re-fetches', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(api.fetchDriverProfile).mockRejectedValueOnce(new Error('API Error 503: Database unavailable'));

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverProfilePage />
      </DriverI18nProvider>
    );

    // Natural-language localized card is rendered
    expect(await screen.findByText('Không thể tải hồ sơ tài xế')).toBeInTheDocument();
    expect(screen.getByText('Vui lòng kiểm tra kết nối mạng và thử lại.')).toBeInTheDocument();
    // No raw error status or developer text
    expect(screen.queryByText(/503|Database unavailable/)).not.toBeInTheDocument();

    // Logged with status only
    expect(consoleSpy).toHaveBeenCalledWith(503);

    // Clicking retry re-fetches
    vi.mocked(api.fetchDriverProfile).mockResolvedValueOnce(mockProfile);
    fireEvent.click(screen.getByTestId('driver-profile-retry'));

    expect(await screen.findByText('Nguyễn Văn An')).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  describe('Profile UI Polish & Layout fixes', () => {
    it('renders correct star distribution for ratings (4.9 -> 5 full; 4.5 -> 4 full + 1 half; 4.2 -> 4 full)', () => {
      const makeProfile = (rating: number): DriverProfileResponse => ({
        ...mockProfile,
        rating_average: rating,
      });

      // 4.9 gives 5 full stars
      const { rerender, container } = render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={makeProfile(4.9)} />
        </DriverI18nProvider>
      );
      const stars49 = container.querySelector('[data-testid="rating-stars"]');
      expect(stars49).not.toBeNull();
      expect(stars49?.querySelectorAll('[data-testid="star-full"]')).toHaveLength(5);
      expect(stars49?.querySelectorAll('[data-testid="star-half"]')).toHaveLength(0);
      expect(stars49?.querySelectorAll('[data-testid="star-empty"]')).toHaveLength(0);

      // 4.5 gives 4 full + 1 half
      rerender(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={makeProfile(4.5)} />
        </DriverI18nProvider>
      );
      const stars45 = container.querySelector('[data-testid="rating-stars"]');
      expect(stars45?.querySelectorAll('[data-testid="star-full"]')).toHaveLength(4);
      expect(stars45?.querySelectorAll('[data-testid="star-half"]')).toHaveLength(1);
      expect(stars45?.querySelectorAll('[data-testid="star-empty"]')).toHaveLength(0);

      // 4.2 gives 4 full
      rerender(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={makeProfile(4.2)} />
        </DriverI18nProvider>
      );
      const stars42 = container.querySelector('[data-testid="rating-stars"]');
      expect(stars42?.querySelectorAll('[data-testid="star-full"]')).toHaveLength(4);
      expect(stars42?.querySelectorAll('[data-testid="star-half"]')).toHaveLength(0);
      expect(stars42?.querySelectorAll('[data-testid="star-empty"]')).toHaveLength(1);

      // Boundary: 4.75 gives 5 full (fraction >= 0.75 rounds up)
      rerender(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={makeProfile(4.75)} />
        </DriverI18nProvider>
      );
      const stars475 = container.querySelector('[data-testid="rating-stars"]');
      expect(stars475?.querySelectorAll('[data-testid="star-full"]')).toHaveLength(5);
      expect(stars475?.querySelectorAll('[data-testid="star-half"]')).toHaveLength(0);
      expect(stars475?.querySelectorAll('[data-testid="star-empty"]')).toHaveLength(0);

      // Boundary: 4.25 gives 4 full + 1 half (fraction >= 0.25 and < 0.75)
      rerender(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={makeProfile(4.25)} />
        </DriverI18nProvider>
      );
      const stars425 = container.querySelector('[data-testid="rating-stars"]');
      expect(stars425?.querySelectorAll('[data-testid="star-full"]')).toHaveLength(4);
      expect(stars425?.querySelectorAll('[data-testid="star-half"]')).toHaveLength(1);
      expect(stars425?.querySelectorAll('[data-testid="star-empty"]')).toHaveLength(0);
    });

    it('formats numbers using active locale in profile-kpi-grid and profile-rating-summary (vi vs en)', () => {
      // In Vietnamese (vi): 1.204, 1.482
      const { rerender } = render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={mockProfile} />
          <ProfileKpiGrid scorecard={mockProfile.scorecard} />
        </DriverI18nProvider>
      );

      // rated_count: 1204 -> 1.204 in vi
      expect(screen.getByText(/1\.204/)).toBeInTheDocument();
      // distribution '5': 1060 -> (1.060) in vi
      expect(screen.getByText(/\(1\.060\)/)).toBeInTheDocument();
      // total_trips: 1482 -> 1.482 in vi
      expect(screen.getByText(/1\.482/)).toBeInTheDocument();

      // In English (en): 1,204, 1,482
      rerender(
        <DriverI18nProvider locale="en" messages={enMessages}>
          <ProfileRatingSummary profile={mockProfile} />
          <ProfileKpiGrid scorecard={mockProfile.scorecard} />
        </DriverI18nProvider>
      );

      // rated_count: 1204 -> 1,204 in en
      expect(screen.getByText(/1,204/)).toBeInTheDocument();
      // distribution '5': 1060 -> (1,060) in en
      expect(screen.getByText(/\(1,060\)/)).toBeInTheDocument();
      // total_trips: 1482 -> 1,482 in en
      expect(screen.getByText(/1,482/)).toBeInTheDocument();
    });

    it('profile-header does not render back button and centers title', () => {
      const onBack = vi.fn();
      render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileHeader onBack={onBack} />
        </DriverI18nProvider>
      );

      // No back button or link rendered
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/quay lại|back/i)).not.toBeInTheDocument();

      // Title is centered
      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toBeInTheDocument();
      expect(heading.parentElement).toHaveClass('justify-center');
    });

    it('profile-weekly-sparkline trend badge uses normal sans font and flex-wrap layout', () => {
      const { container } = render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileWeeklySparkline trend={mockProfile.weekly_trend} />
        </DriverI18nProvider>
      );

      const headerRow = container.querySelector('.flex.items-center.justify-between') || container.querySelector('.flex');
      expect(headerRow).toHaveClass('flex-wrap');

      // The badge should not have font-mono
      const badge = screen.getByText(/Tuần gần nhất có đánh giá|Latest/i);
      expect(badge).not.toHaveClass('font-mono');
    });

    it('profile-rating-summary distribution percent column uses whitespace-nowrap, wider column, and tabular-nums', () => {
      const { container } = render(
        <DriverI18nProvider locale="vi" messages={viMessages}>
          <ProfileRatingSummary profile={mockProfile} />
        </DriverI18nProvider>
      );

      const distSpans = container.querySelectorAll('.space-y-1\\.5 > div > span:last-child');
      expect(distSpans.length).toBeGreaterThan(0);
      distSpans.forEach((span) => {
        expect(span).toHaveClass('whitespace-nowrap');
        expect(span).toHaveClass('tabular-nums');
        expect(span).not.toHaveClass('font-mono');
        expect(span).not.toHaveClass('w-12');
      });
    });
  });
});
