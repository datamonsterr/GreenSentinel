import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DriverTabsLayout from '@/app/driver/(tabs)/layout';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import viMessages from '@/messages/vi.json';

let mockPathname = '/driver/chat';
vi.mock('next/navigation', () => ({ usePathname: () => mockPathname }));

function renderLayout() {
  return render(
    <DriverI18nProvider locale="vi" messages={viMessages}>
      <DriverTabsLayout>
        <div>child</div>
      </DriverTabsLayout>
    </DriverI18nProvider>
  );
}

describe('DriverTabsLayout bottom nav visibility', () => {
  beforeEach(() => {
    mockPathname = '/driver/chat';
  });

  it('hides the bottom nav on the case chat route', () => {
    mockPathname = '/driver/chat/case-123';
    renderLayout();
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByTestId('driver-tabs-shell').className).not.toMatch(/pb-20/);
  });

  it('keeps the bottom nav on the GSupport tab', () => {
    renderLayout();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('keeps the bottom nav on the cases tab', () => {
    mockPathname = '/driver/cases';
    renderLayout();
    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });
});
