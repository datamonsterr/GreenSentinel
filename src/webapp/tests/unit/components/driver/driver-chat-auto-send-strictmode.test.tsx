import React from "react";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

const sendMessage = vi.fn();

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [],
    setMessages: vi.fn(),
    sendMessage,
    regenerate: vi.fn(),
    status: "ready",
    error: undefined,
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "An" }, isLoaded: true }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const fetchDriverSession = vi.fn();
const getDriverDisputeContext = vi.fn();
vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: (...args: any[]) => fetchDriverSession(...args),
  getDriverDisputeContext: (...args: any[]) => getDriverDisputeContext(...args),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — auto-send StrictMode + remount safety", () => {
  beforeEach(() => {
    sendMessage.mockClear();
    fetchDriverSession.mockReset().mockResolvedValue({ messages: [] });
    getDriverDisputeContext.mockReset().mockResolvedValue({
      violation_title: "Case title",
      dispute_status: "in_dispute",
      dispute_deadline: null,
    });
  });

  afterEach(() => cleanup());

  it("auto-sends exactly once under React.StrictMode double-invoke", async () => {
    render(
      <React.StrictMode>
        <DriverI18nProvider locale="en" messages={enMessages}>
          <DriverChatView caseId="case-strict-1" />
        </DriverI18nProvider>
      </React.StrictMode>
    );

    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
    // Give any duplicate effect invocation a chance to fire before asserting
    // it never does.
    await new Promise((r) => setTimeout(r, 20));
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  it("does not re-fire on an unrelated re-render after the first auto-send", async () => {
    const { rerender } = render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-remount-1" />
      </DriverI18nProvider>
    );

    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));

    rerender(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-remount-1" />
      </DriverI18nProvider>
    );

    await new Promise((r) => setTimeout(r, 20));
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  it("a fresh mount for a different case resets the guard and auto-sends again", async () => {
    const { unmount } = render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-A" />
      </DriverI18nProvider>
    );
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
    unmount();

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-B" />
      </DriverI18nProvider>
    );
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
  });
});
