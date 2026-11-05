import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import enMessages from "@/messages/en.json";

const sendMessage = vi.fn();
const setMessages = vi.fn();
let chatMessages: any[] = [];

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: chatMessages,
    setMessages,
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

describe("DriverChatView — case error/expired/resolved/exoneration/analyst states", () => {
  beforeEach(() => {
    sendMessage.mockClear();
    setMessages.mockClear();
    chatMessages = [];
    fetchDriverSession.mockReset();
    getDriverDisputeContext.mockReset();
  });

  it("renders a 404 card and never auto-sends when the case context is not found", async () => {
    fetchDriverSession.mockResolvedValue({ messages: [] });
    getDriverDisputeContext.mockRejectedValue(new Error("API Error 404: Case not found"));

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-missing" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("driver-chat-404")).toBeInTheDocument();
    await waitFor(() => expect(getDriverDisputeContext).toHaveBeenCalled());
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("renders a 403 card when the driver is not authorized for the case", async () => {
    fetchDriverSession.mockResolvedValue({ messages: [] });
    getDriverDisputeContext.mockRejectedValue(new Error("API Error 403: forbidden"));

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-forbidden" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("driver-chat-403")).toBeInTheDocument();
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("shows the expired-deadline banner and disables the composer when the 48h window has passed", async () => {
    fetchDriverSession.mockResolvedValue({ messages: [{ id: "m1", role: "driver", content: "hi" }] });
    getDriverDisputeContext.mockResolvedValue({
      violation_title: "Case title",
      dispute_status: "in_dispute",
      dispute_deadline: new Date(Date.now() - 3600_000).toISOString(),
    });

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-expired" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("driver-chat-expired-banner")).toBeInTheDocument();
    const textarea = await screen.findByPlaceholderText("Type a message…");
    expect(textarea).toBeDisabled();
  });

  it("shows the resolved verdict banner for a resolved case", async () => {
    fetchDriverSession.mockResolvedValue({ messages: [{ id: "m1", role: "driver", content: "hi" }] });
    getDriverDisputeContext.mockResolvedValue({
      violation_title: "Case title",
      dispute_status: "resolved",
      dispute_deadline: null,
    });

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-resolved" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("driver-chat-resolved-banner")).toBeInTheDocument();
  });

  it("renders the exoneration receipt from the done payload, never fabricated client-side", async () => {
    chatMessages = [
      {
        id: "a1",
        role: "assistant",
        parts: [
          { type: "text", text: "Done." },
          { type: "data-done", data: { is_auto_dismissed: true, status: "completed" } },
        ],
      },
    ];
    fetchDriverSession.mockResolvedValue({ messages: [] });
    getDriverDisputeContext.mockResolvedValue({
      violation_title: "Case title",
      dispute_status: "auto_dismissed",
      dispute_deadline: null,
    });

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-exonerated" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("driver-chat-exoneration-receipt")).toBeInTheDocument();
  });

  it("renders a distinct badge for analyst messages", async () => {
    fetchDriverSession.mockResolvedValue({
      messages: [{ id: "m1", role: "analyst", content: "Chuyên viên đã xem xét hồ sơ." }],
    });
    getDriverDisputeContext.mockResolvedValue({
      violation_title: "Case title",
      dispute_status: "in_dispute",
      dispute_deadline: null,
    });
    // setMessages is mocked (no-op); render the mapped messages directly via
    // the chatMessages fixture to assert the badge renders for analyst role.
    chatMessages = [
      {
        id: "m1",
        role: "assistant",
        parts: [{ type: "text", text: "Chuyên viên đã xem xét hồ sơ." }],
        metadata: { sourceRole: "analyst" },
      },
    ];

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-analyst" />
      </DriverI18nProvider>
    );

    expect(await screen.findByTestId("analyst-badge")).toBeInTheDocument();
  });
});
