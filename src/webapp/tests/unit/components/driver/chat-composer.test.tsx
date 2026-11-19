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

describe('DriverChatCasePage full-screen height', () => {
  it('fills the whole viewport (nav is hidden on this route) and stays bounded so the composer stays visible', async () => {
    render(<DriverChatCasePage />);
    const chatWrapper = await screen.findByTestId('driver-chat-container');
    expect(chatWrapper.className).toMatch(/\bh-dvh\b/);
    expect(chatWrapper.className).not.toMatch(/100dvh-5rem/);
    expect(chatWrapper.className).toMatch(/min-h-0/);
    expect(chatWrapper.className).toMatch(/overflow-hidden/);
  });
});
