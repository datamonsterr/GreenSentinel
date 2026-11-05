import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ProfileIdentityCard } from '@/components/driver/profile/profile-identity-card';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';
import type { DriverProfileResponse } from '@/types/schemas';

const mockUseUser = vi.fn();

vi.mock('@clerk/nextjs', () => ({
  useUser: () => mockUseUser(),
}));

const baseProfile: DriverProfileResponse = {
  driver_id: 'drv-123',
  display_name: 'Nguyễn Văn An',
  member_since: '2023-04-15T00:00:00Z',
  vehicle: {
    model: 'VinFast VF e34',
    plate: '29E-123.45',
  },
  scorecard: {
    driver_id: 'drv-123',
    total_trips: 100,
    total_cases: 0,
    violation_ratio_90d: 0,
    benchmark_violation_ratio: 2,
    fined_ratio: 0,
    repeat_offense_risk_score: 0,
    tenure_months: 12,
    past_incidents: [],
  },
  rating_average: 4.9,
  rated_count: 50,
  distribution: { '5': 45, '4': 5, '3': 0, '2': 0, '1': 0 },
  weekly_trend: [],
};

describe('ProfileIdentityCard Component (F5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: null,
      isLoaded: true,
      isSignedIn: true,
    });
  });

  it('renders standard display_name without @ directly with initial avatar', () => {
    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={baseProfile} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('Nguyễn Văn An')).toBeInTheDocument();
    expect(screen.getByText('N')).toBeInTheDocument();
    expect(screen.queryByTestId('driver-avatar-image')).toBeNull();
  });

  it('when display_name contains @, displays Clerk fullName and Clerk imageUrl avatar', () => {
    mockUseUser.mockReturnValue({
      user: {
        id: 'user-1',
        fullName: 'Nguyễn Văn An',
        firstName: 'An',
        imageUrl: 'https://img.clerk.com/avatar-123.png',
      },
      isLoaded: true,
      isSignedIn: true,
    });

    const emailProfile: DriverProfileResponse = {
      ...baseProfile,
      display_name: 'an.nguyen@greensm.vn',
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={emailProfile} />
      </DriverI18nProvider>
    );

    // Shows Clerk fullName instead of email
    expect(screen.getByText('Nguyễn Văn An')).toBeInTheDocument();
    expect(screen.queryByText('an.nguyen@greensm.vn')).toBeNull();

    // Shows avatar image with Clerk imageUrl
    const img = screen.getByTestId('driver-avatar-image');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', 'https://img.clerk.com/avatar-123.png');
  });

  it('when display_name is null, falls back to Clerk fullName', () => {
    mockUseUser.mockReturnValue({
      user: {
        id: 'user-3',
        fullName: 'Test Driver',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test.driver@greensm.vn' },
        imageUrl: '',
      },
      isLoaded: true,
      isSignedIn: true,
    });

    const nullNameProfile: DriverProfileResponse = {
      ...baseProfile,
      display_name: null,
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={nullNameProfile} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('Test Driver')).toBeInTheDocument();
    expect(screen.getByText('T')).toBeInTheDocument();
  });

  it('when display_name is null and Clerk has no fullName, falls back to Clerk primary email', () => {
    mockUseUser.mockReturnValue({
      user: {
        id: 'user-4',
        fullName: null,
        firstName: null,
        primaryEmailAddress: { emailAddress: 'driver.only@greensm.vn' },
        imageUrl: '',
      },
      isLoaded: true,
      isSignedIn: true,
    });

    const nullNameProfile: DriverProfileResponse = {
      ...baseProfile,
      display_name: null,
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={nullNameProfile} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('driver.only@greensm.vn')).toBeInTheDocument();
  });

  it('when display_name is null and Clerk user has no name/email, shows localized generic label', () => {
    mockUseUser.mockReturnValue({
      user: null,
      isLoaded: true,
      isSignedIn: true,
    });

    const nullNameProfile: DriverProfileResponse = {
      ...baseProfile,
      display_name: null,
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={nullNameProfile} />
      </DriverI18nProvider>
    );

    expect(screen.getByText(viMessages.driver.profile.unnamedDriver)).toBeInTheDocument();
  });

  it('when display_name contains @ and user has only firstName, displays firstName', () => {
    mockUseUser.mockReturnValue({
      user: {
        id: 'user-2',
        fullName: null,
        firstName: 'An',
        imageUrl: '',
      },
      isLoaded: true,
      isSignedIn: true,
    });

    const emailProfile: DriverProfileResponse = {
      ...baseProfile,
      display_name: 'driver@greensm.vn',
    };

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <ProfileIdentityCard profile={emailProfile} />
      </DriverI18nProvider>
    );

    expect(screen.getByText('An')).toBeInTheDocument();
    expect(screen.getByText('A')).toBeInTheDocument();
  });
});
