import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import DriverChatCasePage from '@/app/driver/(tabs)/chat/[caseId]/page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useParams: () => ({ caseId: 'case-test-123' }),
}));

vi.mock('@/components/driver/chat/driver-chat-view', () => ({
  DriverChatView: ({ caseId }: { caseId: string }) => (
    <div data-testid="driver-chat-view" data-case-id={caseId}>
      <div data-testid="chat-composer" className="p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))]">
        <input placeholder="Enter dispute details" />
      </div>
    </div>
  ),
}));

describe('DriverChatCasePage Composer clearance', () => {
  it('renders chat view and clears the fixed bottom nav with bottom padding and safe-area', async () => {
    render(<DriverChatCasePage />);
    const chatWrapper = await screen.findByTestId('driver-chat-container');
    expect(chatWrapper).toBeInTheDocument();
    // Verify container or composer has bottom padding/clearance class
    expect(chatWrapper.className).toMatch(/pb-/);
  });
});

describe('DriverChatCasePage bounded height', () => {
  it('bounds the chat container to the viewport so a long conversation cannot push the composer out of view', async () => {
    render(<DriverChatCasePage />);
    const chatWrapper = await screen.findByTestId('driver-chat-container');
    expect(chatWrapper.className).toMatch(/h-\[calc\(100dvh-5rem\)\]/);
    expect(chatWrapper.className).toMatch(/min-h-0/);
  });
});
