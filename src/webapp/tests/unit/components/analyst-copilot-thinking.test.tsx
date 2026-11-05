import React from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UIMessage } from "ai";
import { AnalystCopilotPanel } from "@/components/copilot/analyst-copilot-panel";
const chat = vi.hoisted(() => ({ messages: [] as UIMessage[], status: "ready", setMessages: vi.fn(), sendMessage: vi.fn() }));
vi.mock("@ai-sdk/react", () => ({ useChat: () => chat }));
vi.mock("@/lib/locale", () => ({ useLocale: () => ({ locale: "en" }) }));
vi.mock("@/lib/api-client", () => ({ fetchAgentSession: vi.fn(async () => null), fetchDriverScorecard: vi.fn(), getApiBaseUrl: () => "", authorizedHeaders: vi.fn(async () => ({})) }));
vi.mock("@/lib/copilot/context-api", () => ({ getAgentContext: vi.fn(async () => null), clearAgentContext: vi.fn() }));
function setParts(parts: UIMessage["parts"], status = "streaming") { chat.messages = [{ id: "assistant-1", role: "assistant", parts }]; chat.status = status; }
function reasoning(text: string, state: "streaming" | "done" = "streaming", durationMs?: number): UIMessage["parts"][number] {
  return { type: "reasoning", text, state, ...(durationMs === undefined ? {} : { providerMetadata: { copilot: { durationMs } } }) };
}
const panel = () => <AnalystCopilotPanel caseId="case-thinking" isLockedByMe />;
beforeEach(() => { chat.messages = []; chat.status = "ready"; vi.clearAllMocks(); });
afterEach(() => vi.restoreAllMocks());
describe("Analyst copilot Thinking disclosure", () => {
  it("shows streamed reasoning, respects toggles, then collapses once with duration and keyboard reopening", async () => {
    setParts([reasoning("Checking pickup")]);
    const { rerender } = render(panel());
    const toggle = screen.getByRole("button", { name: /Thinking/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Checking pickup")).toBeVisible();
    fireEvent.click(toggle);
    setParts([reasoning("Checking pickup and route")]); rerender(panel());
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByText("Checking pickup and route")).toBeVisible();
    setParts([reasoning("Checking pickup and route", "done", 2400)], "ready"); rerender(panel());
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("2400 ms");
    toggle.focus(); await userEvent.setup().keyboard("{Enter}");
    expect(screen.getByText("Checking pickup and route")).toBeVisible();
    rerender(panel()); expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
  it.each(["ready", "error"])("stops stale streaming parts on %s and freezes locally observed duration", (status) => {
    let now = 1000; vi.spyOn(Date, "now").mockImplementation(() => now);
    setParts([reasoning("Compare evidence")]); const { rerender } = render(panel());
    now = 3500; chat.status = status; rerender(panel());
    const toggle = screen.getByRole("button", { name: /Thinking/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false"); expect(toggle).toHaveTextContent("2500 ms");
    expect(toggle.querySelector(".animate-spin")).toBeNull();
    now = 10000; rerender(panel()); expect(toggle).toHaveTextContent("2500 ms");
  });
  it("keeps historical reasoning collapsed without inventing duration or running an old turn", () => {
    setParts([reasoning("Older reasoning", "streaming")]);
    chat.messages.push({ id: "new-assistant", role: "assistant", parts: [{ type: "text", text: "New answer" }] }); render(panel());
    const toggle = screen.getByRole("button", { name: /Thinking/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false"); expect(toggle).toHaveTextContent(/^Thinking$/);
    expect(toggle.querySelector(".animate-spin")).toBeNull();
  });
  it("does not restart old reasoning while the next user turn is submitted", () => {
    setParts([reasoning("Older reasoning", "streaming")], "submitted");
    chat.messages.push({ id: "new-user", role: "user", parts: [{ type: "text", text: "Next question" }] });
    render(panel());
    const toggle = screen.getByRole("button", { name: /Thinking/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.querySelector(".animate-spin")).toBeNull();
  });
  it("merges adjacent reasoning but preserves order across tools and answer text", () => {
    setParts([reasoning("First", "done", 1000), reasoning("Second", "done", 1500),
      { type: "dynamic-tool", toolCallId: "lookup", toolName: "lookup", state: "output-available", input: {}, output: "Tool evidence" },
      reasoning("Third", "done", 2000), { type: "text", text: "Answer" }, reasoning("Fourth", "done")], "ready"); render(panel());
    const toggles = screen.getAllByRole("button", { name: /Thinking/ }); expect(toggles).toHaveLength(3);
    expect(toggles[0]).toHaveTextContent("2500 ms"); toggles.forEach((toggle) => fireEvent.click(toggle));
    expect(screen.getByText(/First\s+Second/)).toBeVisible(); expect(screen.getByText("Third")).toBeVisible(); expect(screen.getByText("Fourth")).toBeVisible();
    expect(screen.getByText("Answer").compareDocumentPosition(toggles[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("preserves status labels without presenting invented reasoning", () => {
    setParts([{ type: "data-status", data: { label: "Searching policy documents" } }]); render(panel());
    expect(screen.getByText("Searching policy documents")).toBeVisible(); expect(screen.getByRole("button", { name: /Thinking/ })).toHaveAttribute("aria-expanded", "true");
  });
  it("renders inline code compactly and fenced code with exactly one pre wrapper", () => {
    setParts([{ type: "text", text: "Use `case_id` here.\n\n```ts\nconst value = 1;\n```" }], "ready");
    const { container } = render(panel()); const inline = screen.getByText("case_id");
    expect(inline.tagName).toBe("CODE"); expect(inline.closest("pre")).toBeNull(); expect(inline).toHaveClass("text-[0.9em]");
    expect(container.querySelectorAll("pre")).toHaveLength(1); expect(container.querySelector("pre pre")).toBeNull();
    expect(screen.getByText("const value = 1;")).toBeVisible();
  });
});
