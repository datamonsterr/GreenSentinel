import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [
      {
        id: "m-user-1",
        role: "user",
        parts: [{ type: "text", text: "Hello from driver" }],
      },
      {
        id: "m-assistant-1",
        role: "assistant",
        parts: [{ type: "text", text: "Hello! How can I help you?" }],
      },
    ],
    setMessages: vi.fn(),
    sendMessage: vi.fn(),
    regenerate: vi.fn(),
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

describe("DriverChatView — user message bubble contrast (BUG 1)", () => {
  it("renders user bubble with teal background, white text, and inverted prose", () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    const userText = screen.getByText("Hello from driver");
    // Find the enclosing message bubble container (MessageContent)
    const bubble = userText.closest(".is-user")?.querySelector('[class*="group-[.is-user]:ml-auto"]')
      || userText.closest('[class*="bg-emerald"]')
      || userText.closest('div');

    expect(bubble).not.toBeNull();
    const className = bubble?.className || "";

    // Dark green background in light mode (bg-emerald-600) and dark mode (dark:bg-emerald-700)
    expect(className).toMatch(/bg-emerald-600/);
    expect(className).toMatch(/dark:bg-emerald-700/);

    // White text
    expect(className).toMatch(/text-white/);

    // Links and markdown child contrast
    expect(className).toMatch(/\[&_\*\]:text-white|prose-invert/);
  });
});
