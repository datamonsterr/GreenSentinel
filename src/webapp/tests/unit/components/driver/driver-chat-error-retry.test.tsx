import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

const sendMessage = vi.fn();
const regenerate = vi.fn();

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [
      { id: "u1", role: "user", parts: [{ type: "text", text: "Hello" }] },
    ],
    setMessages: vi.fn(),
    sendMessage,
    regenerate,
    status: "error",
    error: { message: "network down" },
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "Driver" }, isLoaded: true }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: vi.fn(),
  getDriverDisputeContext: vi.fn(),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — error and retry", () => {
  it("shows an error state with a retry control", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(screen.getByTestId("driver-chat-error")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the assistant, please try again")).toBeInTheDocument();
    expect(screen.queryByText(/network down/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("driver-chat-retry")).toBeInTheDocument();
  });

  it("retry regenerates the last turn in place without a duplicate user bubble", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    fireEvent.click(screen.getByTestId("driver-chat-retry"));

    expect(regenerate).toHaveBeenCalledTimes(1);
    // Regenerate, not a new sendMessage call — no duplicate user bubble.
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
