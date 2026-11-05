import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [
      {
        id: "m1",
        role: "assistant",
        parts: [
          { type: "text", text: "Here is your case." },
          {
            type: "data-blocks",
            data: {
              blocks: [
                { type: "case_card", case_id: "018f2f4e-0000", title: "Unusual route check" },
              ],
            },
          },
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

describe("DriverChatView — typed block rendering", () => {
  it("renders a case_card block from the assistant message's data-blocks part", async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="018f2f4e-0000" />
      </DriverI18nProvider>
    );

    expect(await screen.findByText("Here is your case.")).toBeInTheDocument();
    expect(await screen.findByText("Unusual route check")).toBeInTheDocument();
  });
});
