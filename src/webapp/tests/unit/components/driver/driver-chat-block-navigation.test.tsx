import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

const push = vi.fn();

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [
      {
        id: "a1",
        role: "assistant",
        parts: [
          {
            type: "data-blocks",
            data: {
              blocks: [
                { type: "case_card", case_id: "case-999", title: "Case title" },
                { type: "trip_card", trip_id: "trip-abc12345", pickup: "A", destination: "B" },
                {
                  type: "list",
                  items: [{ label: "Policy 12.2", href: "policy://c12_2 force-majeure text" }],
                },
              ],
            },
          },
        ],
      },
    ],
    setMessages: vi.fn(),
    sendMessage: vi.fn(),
    regenerate: vi.fn(),
    status: "ready",
    error: undefined,
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "An" }, isLoaded: true }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: vi.fn().mockResolvedValue({ messages: [] }),
  getDriverDisputeContext: vi.fn().mockResolvedValue({
    violation_title: "Case title",
    dispute_status: "in_dispute",
    dispute_deadline: null,
  }),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — block navigation routing", () => {
  it("routes case:// to /driver/chat/<id>", async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-999" />
      </DriverI18nProvider>
    );

    fireEvent.click(await screen.findByRole("button", { name: /Case title|case-999/i }));
    expect(push).toHaveBeenCalledWith("/driver/chat/case-999");
  });

  it("routes trip:// to /driver/history?trip=<id>", async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-999" />
      </DriverI18nProvider>
    );

    const tripButton = await screen.findByText(/Trip details|Chi tiết chuyến/i);
    fireEvent.click(tripButton);
    expect(push).toHaveBeenCalledWith(expect.stringContaining("/driver/history?trip="));
  });

  it("opens the policy sheet (dialog) for policy:// instead of a silent no-op", async () => {
    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-999" />
      </DriverI18nProvider>
    );

    fireEvent.click(await screen.findByText("Policy 12.2"));
    expect(await screen.findByTestId("driver-chat-policy-sheet")).toBeInTheDocument();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
