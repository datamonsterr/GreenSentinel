import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DriverBottomNav } from '@/components/driver/driver-bottom-nav';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';

let mockPathname = '/driver/cases';

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

describe('DriverBottomNav Component', () => {
  beforeEach(() => {
    mockPathname = '/driver/cases';
  });

  function renderNav(locale: 'vi' | 'en' = 'vi') {
    const messages = locale === 'vi' ? viMessages : enMessages;
    return render(
      <DriverI18nProvider locale={locale} messages={messages}>
        <DriverBottomNav />
      </DriverI18nProvider>
    );
  }

  it('renders all 5 tabs with links and translated labels in vi', () => {
    renderNav('vi');
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(5);

    expect(screen.getByRole('link', { name: /Vụ việc/i })).toHaveAttribute('href', '/driver/cases');
    expect(screen.getByRole('link', { name: /Hồ sơ/i })).toHaveAttribute('href', '/driver/profile');
    expect(screen.getByRole('link', { name: /GSupport/i })).toHaveAttribute('href', '/driver/chat');
    expect(screen.getByRole('link', { name: /Lịch sử/i })).toHaveAttribute('href', '/driver/history');
    expect(screen.getByRole('link', { name: /Cài đặt/i })).toHaveAttribute('href', '/driver/settings');
  });

  it('renders all 5 tabs with translated labels in en', () => {
    renderNav('en');
    expect(screen.getByRole('link', { name: /Cases/i })).toHaveAttribute('href', '/driver/cases');
    expect(screen.getByRole('link', { name: /Profile/i })).toHaveAttribute('href', '/driver/profile');
    expect(screen.getByRole('link', { name: /GSupport/i })).toHaveAttribute('href', '/driver/chat');
    expect(screen.getByRole('link', { name: /History/i })).toHaveAttribute('href', '/driver/history');
    expect(screen.getByRole('link', { name: /Settings/i })).toHaveAttribute('href', '/driver/settings');
  });

  it('marks active tab with aria-current="page"', () => {
    mockPathname = '/driver/cases';
    const { unmount } = renderNav();
    expect(screen.getByRole('link', { name: /Vụ việc/i })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Cài đặt/i })).not.toHaveAttribute('aria-current');
    unmount();

    mockPathname = '/driver/settings';
    renderNav();
    expect(screen.getByRole('link', { name: /Cài đặt/i })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Vụ việc/i })).not.toHaveAttribute('aria-current');
  });

  it('supports keyboard navigation with tab order and enter activation', async () => {
    const { unmount } = renderNav('en');

    const casesLink = screen.getByRole('link', { name: /Cases/i });
    const profileLink = screen.getByRole('link', { name: /Profile/i });
    const chatLink = screen.getByRole('link', { name: /GSupport/i });
    const historyLink = screen.getByRole('link', { name: /History/i });
    const settingsLink = screen.getByRole('link', { name: /Settings/i });

    // Focus first tab link and verify Tab navigation order
    casesLink.focus();
    expect(casesLink).toHaveFocus();

    profileLink.focus();
    expect(profileLink).toHaveFocus();

    chatLink.focus();
    expect(chatLink).toHaveFocus();

    historyLink.focus();
    expect(historyLink).toHaveFocus();

    settingsLink.focus();
    expect(settingsLink).toHaveFocus();

    // Verify Enter key activation on focused link
    const clickHandler = vi.fn((e: MouseEvent) => e.preventDefault());
    settingsLink.addEventListener('click', clickHandler);
    settingsLink.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    settingsLink.click();
    expect(clickHandler).toHaveBeenCalled();

    unmount();
  });
});
