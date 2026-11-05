import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [
      {
        id: "m-tool-trace",
        role: "assistant",
        parts: [
          {
            type: "tool-corroborate_traffic_conditions",
            toolCallId: "call_traffic_1",
            toolName: "corroborate_traffic_conditions",
            title: "Checking traffic conditions",
            state: "output-available",
            output: { status: "ok" },
          },
          {
            type: "tool-check_weather_condition",
            toolCallId: "call_weather_2",
            toolName: "check_weather_condition",
            title: "Checking weather conditions",
            state: "input-available",
            input: {},
          },
          { type: "text", text: "I have checked the physical conditions." },
        ],
      },
    ],
    setMessages: vi.fn(),
    sendMessage: vi.fn(),
    status: "ready",
    error: undefined,
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "Driver" }, isLoaded: true }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: vi.fn().mockResolvedValue({ messages: [] }),
  getDriverDisputeContext: vi.fn().mockResolvedValue({
    driver_name: "Driver A",
    violation_title: "Header case title",
    dispute_status: "in_dispute",
  }),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — collapsible tool trace", () => {
  it("renders a compact collapsible trace with localized labels, spinner and check", async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="018f2f4e-0000" />
      </DriverI18nProvider>
    );

    // Assert localized labels are displayed
    expect(await screen.findByText("Checking traffic conditions")).toBeInTheDocument();
    expect(await screen.findByText("Checking weather conditions")).toBeInTheDocument();

    // Assert spinner for running tool and check icon for completed tool
    expect(screen.getByTestId("tool-check")).toBeInTheDocument();
    expect(screen.getByTestId("tool-spinner")).toBeInTheDocument();
  });
});
