import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

const sendMessage = vi.fn();
const setMessages = vi.fn();

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [],
    setMessages,
    sendMessage,
    status: "ready",
    error: undefined,
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: vi.fn(),
  getDriverDisputeContext: vi.fn(),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "An" }, isLoaded: true }),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — case-less greeting", () => {
  beforeEach(() => {
    sendMessage.mockClear();
  });

  it("renders a greeting and 4 suggestion chips when there is no caseId", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(screen.getByTestId("driver-chat-greeting")).toBeInTheDocument();
    expect(screen.getByText(/How can I help you today\?/i)).toBeInTheDocument();

    const suggestions = screen.getByTestId("driver-chat-suggestions");
    const buttons = suggestions.querySelectorAll("button");
    expect(buttons.length).toBe(4);
  });

  it("uses the Clerk user's first name in the greeting", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(screen.getByText(/Hi An/i)).toBeInTheDocument();
  });

  it("sends the suggestion prompt when a chip is clicked", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    fireEvent.click(screen.getByText("Do I have any open cases?"));
    expect(sendMessage).toHaveBeenCalledWith({ text: "Do I have any open cases?" });
  });
});
