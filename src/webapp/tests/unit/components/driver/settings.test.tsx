import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DriverSettingsView } from '@/components/driver/driver-settings-view';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';

const mockPush = vi.fn();
const mockRefresh = vi.fn();
const mockSignOut = vi.fn();
const mockOpenUserProfile = vi.fn();

let mockUser: {
  fullName: string | null;
  primaryEmailAddress: { emailAddress: string } | null;
  imageUrl: string;
} | null = {
  fullName: 'Nguyen Van An',
  primaryEmailAddress: { emailAddress: 'an.nguyen@greensm.vn' },
  imageUrl: 'https://example.com/avatar.jpg',
};

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    refresh: mockRefresh,
  }),
}));

vi.mock('@clerk/nextjs', () => ({
  useUser: () => ({
    user: mockUser,
    isLoaded: true,
  }),
  useClerk: () => ({
    signOut: mockSignOut,
    openUserProfile: mockOpenUserProfile,
  }),
}));

describe('DriverSettingsView Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.cookie = '';
    localStorage.clear();
    document.documentElement.className = '';
    mockUser = {
      fullName: 'Nguyen Van An',
      primaryEmailAddress: { emailAddress: 'an.nguyen@greensm.vn' },
      imageUrl: 'https://example.com/avatar.jpg',
    };
  });

  function renderSettings(locale: 'vi' | 'en' = 'vi') {
    const messages = locale === 'vi' ? viMessages : enMessages;
    return render(
      <DriverI18nProvider locale={locale} messages={messages}>
        <DriverSettingsView />
      </DriverI18nProvider>
    );
  }

  it('renders driver user info from Clerk and app version', () => {
    renderSettings('vi');
    expect(screen.getByText('Nguyen Van An')).toBeInTheDocument();
    expect(screen.getByText('an.nguyen@greensm.vn')).toBeInTheDocument();
    expect(screen.getByAltText(/Avatar|Đại diện/i)).toBeInTheDocument();
  });

  it('renders empty/i18n placeholder when primary email is missing without falling back to hardcoded an.nguyen@greensm.vn', () => {
    mockUser = {
      fullName: 'Tran Van B',
      primaryEmailAddress: null,
      imageUrl: '',
    };
    renderSettings('vi');
    expect(screen.getByText('Tran Van B')).toBeInTheDocument();
    expect(screen.queryByText('an.nguyen@greensm.vn')).not.toBeInTheDocument();
  });

  it('removes ALL fabricated data (gold tier, vehicle/battery, hotline, policies, regulations, partner ID)', () => {
    renderSettings('vi');
    expect(screen.queryByText(/Hạng Vàng|Gold Tier/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/VF 5|29E/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pin khả dụng|Battery/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/1900 2088/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/GSM-VN-/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Điều khoản|Terms/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Quy chế|Regulations/i })).not.toBeInTheDocument();
  });

  it('opens Clerk user profile when clicking Manage account', () => {
    renderSettings('vi');
    const manageBtn = screen.getByRole('button', { name: /Quản lý tài khoản|Manage account/i });
    fireEvent.click(manageBtn);
    expect(mockOpenUserProfile).toHaveBeenCalledTimes(1);
  });

  it('toggles theme on driver root wrapper and persists in cookie without mutating documentElement', () => {
    const driverRoot = document.createElement('div');
    driverRoot.id = 'driver-root';
    driverRoot.className = 'driver-scope light';
    document.body.appendChild(driverRoot);

    renderSettings('vi');
    const darkBtn = screen.getByRole('button', { name: /Tối|Dark/i });
    fireEvent.click(darkBtn);

    expect(driverRoot.classList.contains('dark')).toBe(true);
    expect(driverRoot.classList.contains('light')).toBe(false);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.cookie).toContain('theme=dark');

    const lightBtn = screen.getByRole('button', { name: /Sáng|Light/i });
    fireEvent.click(lightBtn);

    expect(driverRoot.classList.contains('dark')).toBe(false);
    expect(driverRoot.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.cookie).toContain('theme=light');

    document.body.removeChild(driverRoot);
  });

  it('switches language and calls setLocaleCookie and router.refresh', () => {
    renderSettings('vi');
    const enBtn = screen.getByRole('button', { name: /English/i });
    fireEvent.click(enBtn);

    expect(document.cookie).toContain('NEXT_LOCALE=en');
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it('calls Clerk signOut and asserts router push/redirect to /sign-in', async () => {
    mockSignOut.mockImplementation((cb?: () => void) => {
      if (typeof cb === 'function') cb();
      return Promise.resolve();
    });

    renderSettings('vi');
    const signOutBtn = screen.getByRole('button', { name: /Đăng xuất|Sign out/i });
    fireEvent.click(signOutBtn);

    expect(mockSignOut).toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith('/sign-in');
  });

  it('renders app version from NEXT_PUBLIC_APP_VERSION config rather than hardcoded literal', () => {
    vi.stubEnv('NEXT_PUBLIC_APP_VERSION', '1.9.9');
    renderSettings('vi');
    expect(screen.getByText('v1.9.9')).toBeInTheDocument();
    vi.unstubAllEnvs();
  });
});
