import React from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalystCopilotPanel } from "@/components/copilot/analyst-copilot-panel";
import { LocaleProvider } from "@/lib/locale";
import * as apiClient from "@/lib/api-client";
import * as contextApi from "@/lib/copilot/context-api";

vi.mock("@/lib/api-client", () => ({
  fetchAgentSession: vi.fn(), getApiBaseUrl: vi.fn(() => ""),
  authorizedHeaders: vi.fn(async () => ({ "Content-Type": "application/json" })), fetchDriverScorecard: vi.fn(),
}));
vi.mock("@/lib/copilot/context-api", () => ({ getAgentContext: vi.fn(), clearAgentContext: vi.fn() }));
vi.mock("@/lib/copilot/history", () => ({ mapAgentSessionToUIMessages: vi.fn(() => []) }));

function sse(type: string, payload: Record<string, unknown>) {
  return `event: ${type}\ndata: ${JSON.stringify({ type, payload })}\n\n`;
}

describe("AnalystCopilotPanel reasoning stream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.fetchAgentSession).mockResolvedValue({ session_id: "session-1", messages: [] });
    vi.mocked(contextApi.getAgentContext).mockResolvedValue({
      prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, context_window: 10000,
      breakdown: { system: 0, dossier: 0, history: 0, tool_results: 0, query: 0 }, turn_count: 0,
    });
  });

  it("renders streamed reasoning, then collapses it with duration while preserving the text", async () => {
    const user = userEvent.setup();
    let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
    vi.stubGlobal("fetch", vi.fn(async () => {
      const body = new ReadableStream<Uint8Array>({ start(next) { controller = next; } });
      return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    }));

    render(<LocaleProvider><AnalystCopilotPanel caseId="case-stream" isLockedByMe /></LocaleProvider>);
    const composer = await screen.findByRole("textbox");
    await user.type(composer, "Why was this trip flagged?");
    await user.click(screen.getByRole("button", { name: /send message/i }));
    await waitFor(() => expect(controller).toBeDefined());
    const encode = (value: string) => new TextEncoder().encode(value);
    controller!.enqueue(encode(sse("reasoning.start", {})));
    controller!.enqueue(encode(sse("reasoning.delta", { delta: "Checking the trip evidence" })));
    const thinking = await screen.findByRole("button", { name: /thinking/i });
    expect(thinking).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Checking the trip evidence")).toBeInTheDocument();
    controller!.enqueue(encode(sse("reasoning.delta", { delta: " and policy history." })));
    expect(await screen.findByText("Checking the trip evidence and policy history.")).toBeInTheDocument();
    controller!.enqueue(encode(sse("reasoning.end", { duration_ms: 1840 })));
    controller!.enqueue(encode(sse("text.delta", { delta: "The trip matches the review criteria." })));
    controller!.enqueue(encode(sse("run.completed", {})));
    controller!.close();
    await waitFor(() => expect(thinking).toHaveAttribute("aria-expanded", "false"));
    expect(thinking).toHaveTextContent(/Thinking|Suy nghĩ/i);
    expect(thinking).toHaveTextContent(/1840\s*ms/i);
    expect(screen.getByText("The trip matches the review criteria.")).toBeInTheDocument();
    thinking.focus();
    await user.keyboard("{Enter}");
    expect(thinking).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Checking the trip evidence and policy history.")).toBeVisible();
  });
});
