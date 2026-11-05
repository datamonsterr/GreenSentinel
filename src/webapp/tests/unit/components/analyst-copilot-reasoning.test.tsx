import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalystCopilotPanel } from "@/components/copilot/analyst-copilot-panel";

const chat = vi.hoisted(() => ({
  messages: [] as any[], status: "streaming", setMessages: vi.fn(), sendMessage: vi.fn(), error: undefined,
}));
vi.mock("@ai-sdk/react", () => ({ useChat: () => chat }));
vi.mock("@/lib/api-client", () => ({
  fetchAgentSession: vi.fn().mockResolvedValue({ messages: [] }),
  fetchDriverScorecard: vi.fn(),
}));
vi.mock("@/lib/copilot/context-api", () => ({
  getAgentContext: vi.fn().mockResolvedValue({ total_tokens: 0, context_window: 10000 }),
  clearAgentContext: vi.fn(),
}));

function message(parts: any[]) {
  return { id: "streaming-answer", role: "assistant", parts };
}

function panel() { return <AnalystCopilotPanel caseId="case-thinking" isLockedByMe />; }

describe("Analyst copilot Thinking stream", () => {
  beforeEach(() => { chat.status = "streaming"; chat.messages = []; });
  afterEach(() => { vi.restoreAllMocks(); });

  it("streams reasoning text, then collapses once with measured duration and remains reopenable", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1000);
    chat.messages = [message([{ type: "reasoning", state: "streaming", text: "Compare route" }])];
    const view = render(panel());
    const trigger = screen.getByRole("button", { name: "Thinking" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Compare route")).toBeVisible();
    chat.messages = [message([{ type: "reasoning", state: "streaming", text: "Compare route evidence" }])];
    view.rerender(panel());
    expect(screen.getByText("Compare route evidence")).toBeVisible();
    now.mockReturnValue(2350);
    chat.status = "ready";
    chat.messages = [message([{ type: "reasoning", state: "done", text: "Compare route evidence" }, { type: "text", text: "Evidence checked." }])];
    view.rerender(panel());
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "false"));
    expect(trigger).toHaveTextContent("1350 ms");
    expect(screen.queryByText("Compare route evidence")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.getByText("Compare route evidence")).toBeVisible();
  });

  it("collapses partial reasoning when the stream stops before the part is marked done", async () => {
    chat.messages = [message([{ type: "reasoning", state: "streaming", text: "Partial route evidence" }])];
    const view = render(panel());
    const trigger = screen.getByRole("button", { name: "Thinking" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    chat.status = "ready";
    view.rerender(panel());
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "false"));
    fireEvent.click(trigger);
    expect(screen.getByText("Partial route evidence")).toBeVisible();
  });

  it("renders public thinking labels once inside Thinking when there are no reasoning parts", async () => {
    chat.messages = [message([{ type: "data-status", data: { label: "Checking public route evidence" } }])];
    const view = render(panel());
    expect(screen.getAllByText("Checking public route evidence")).toHaveLength(1);
    const trigger = screen.getByRole("button", { name: "Thinking" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    chat.status = "ready";
    view.rerender(panel());
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "false"));
    fireEvent.click(trigger);
    expect(screen.getByText("Checking public route evidence")).toBeVisible();
  });

  it("prefers actual reasoning over a public status label in one Thinking block", () => {
    chat.messages = [message([
      { type: "data-status", data: { label: "Checking route" } },
      { type: "reasoning", state: "streaming", text: "Compare the observed route with the baseline." },
    ])];
    render(panel());
    expect(screen.getAllByRole("button", { name: "Thinking" })).toHaveLength(1);
    expect(screen.getByText("Compare the observed route with the baseline.")).toBeVisible();
    expect(screen.queryByText("Checking route")).not.toBeInTheDocument();
  });
});
