import { afterEach, describe, expect, it, vi } from "vitest";
import { readUIMessageStream, type UIMessage, type UIMessageChunk } from "ai";
import { ChatEventStreamParser, consumeChatEventStream } from "@/lib/chat-event-stream";
import { CaseCopilotTransport } from "@/lib/copilot/transport";

vi.mock("@/lib/api-client", () => ({
  getApiBaseUrl: () => "https://copilot.test",
  authorizedHeaders: async (headers: HeadersInit) => headers,
}));

const encoder = new TextEncoder();
const reasoningId = "reasoning-turn-test-1";
const textId = "text-turn-test-1";

function envelope(type: string, payload: Record<string, unknown>, sequence: number) {
  return { schema_version: "1.1", event_id: `event-${sequence}`, run_id: "run-test", message_id: "message-test", sequence, type, payload };
}

function frame(type: string, payload: Record<string, unknown>, sequence: number) {
  return `event: ${type}\r\ndata: ${JSON.stringify(envelope(type, payload, sequence))}\r\n\r\n`;
}

function bytes(wire: string, splitBytes = false) {
  const encoded = encoder.encode(wire);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      if (splitBytes) {
        for (const byte of encoded) controller.enqueue(Uint8Array.of(byte));
      } else {
        controller.enqueue(encoded);
      }
      controller.close();
    },
  });
}

async function transport(byteStream: ReadableStream<Uint8Array>, abortSignal?: AbortSignal) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, body: byteStream }));
  return new CaseCopilotTransport().sendMessages({
    trigger: "submit-message", chatId: "case-test", messageId: undefined,
    messages: [{ id: "user-test", role: "user", parts: [{ type: "text", text: "Analyze trip" }] }],
    abortSignal, body: { turn_id: "turn-test" },
  });
}

async function collect(stream: ReadableStream<UIMessageChunk>) {
  const reader = stream.getReader();
  const chunks: UIMessageChunk[] = [];
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) return chunks;
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
}

afterEach(() => vi.unstubAllGlobals());

describe("reasoning stream parser contract", () => {
  it("accumulates canonical thoughts separately from answers across UTF-8/frame boundaries", async () => {
    const onReasoning = vi.fn();
    const onDelta = vi.fn();
    const onTerminal = vi.fn();
    const wire = frame("status.thinking", { label: "Checking evidence" }, 0)
      + frame("reasoning.start", {}, 1)
      + frame("reasoning.delta", { delta: "Kiểm tra " }, 2)
      + frame("reasoning.delta", { text: "dữ liệu 🚕" }, 3)
      + frame("reasoning.end", {}, 4)
      + frame("text.delta", { delta: "Answer." }, 5)
      + frame("thinking.delta", { thought: " Second pass." }, 6)
      + frame("run.completed", {}, 7);
    const state = await consumeChatEventStream(bytes(wire, true), { onReasoning, onDelta, onTerminal });
    expect(state).toMatchObject({ status: "completed", text: "Answer.", reasoning: "Kiểm tra dữ liệu 🚕 Second pass.", thinking: "Checking evidence" });
    expect(onReasoning.mock.calls).toEqual([
      ["Kiểm tra ", "Kiểm tra "],
      ["dữ liệu 🚕", "Kiểm tra dữ liệu 🚕"],
      [" Second pass.", "Kiểm tra dữ liệu 🚕 Second pass."],
    ]);
    expect(onDelta.mock.calls).toEqual([["Answer.", "Answer."]]);
    expect(onTerminal).toHaveBeenCalledOnce();
  });

  it("retains optional status thought and legacy completed thought without treating labels as reasoning", () => {
    const parser = new ChatEventStreamParser();
    parser.processSseMessage("status.thinking", JSON.stringify(envelope("status.thinking", { label: "Finding evidence", thought: "Read evidence. " }, 0)));
    parser.processSseMessage("thinking", JSON.stringify({ status: "completed", thought: "Compare route." }));
    parser.processSseMessage("done", "{}");
    expect(parser.getState()).toMatchObject({ status: "completed", reasoning: "Read evidence. Compare route.", text: "" });
  });

  it.each(["reasoning.delta", "thinking.delta"])("accepts unwrapped %s events", async (type) => {
    const wire = `event: ${type}\ndata: {"delta":"Check route."}\n\nevent: done\ndata: {}\n\n`;
    const state = await consumeChatEventStream(bytes(wire, true));
    expect(state).toMatchObject({ status: "completed", reasoning: "Check route.", text: "" });
  });

  it("does not duplicate replayed reasoning or append thoughts after terminal", () => {
    const onReasoning = vi.fn();
    const parser = new ChatEventStreamParser({ onReasoning });
    const delta = JSON.stringify(envelope("reasoning.delta", { delta: "Only once." }, 0));
    parser.processSseMessage("reasoning.delta", delta);
    parser.processSseMessage("reasoning.delta", delta);
    parser.processSseMessage("run.completed", JSON.stringify(envelope("run.completed", {}, 1)));
    parser.processSseMessage("reasoning.delta", JSON.stringify(envelope("reasoning.delta", { delta: "Late." }, 2)));
    expect(parser.getState().reasoning).toBe("Only once.");
    expect(onReasoning).toHaveBeenCalledExactlyOnceWith("Only once.", "Only once.");
  });

  it("preserves partial reasoning when EOF interrupts the response", async () => {
    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(bytes(frame("reasoning.delta", { delta: "Partial thought" }, 0)), { onTerminal });
    expect(state).toMatchObject({ status: "interrupted", reasoning: "Partial thought", error: { code: "INTERRUPTED" } });
    expect(onTerminal).toHaveBeenCalledOnce();
  });
});

describe("reasoning SSE to AI SDK contract", () => {
  it("emits exact reasoning IDs and text across multiple blocks and a tool boundary", async () => {
    const wire = frame("reasoning.start", {}, 0)
      + frame("reasoning.delta", { delta: "Inspect " }, 1)
      + frame("reasoning.delta", { text: "route 🚕" }, 2)
      + frame("tool.start", { tool_call_id: "lookup-1", tool_name: "search", input: { query: "route" } }, 3)
      + frame("tool.end", { tool_call_id: "lookup-1", status: "succeeded", output: { matched: true } }, 4)
      + frame("thinking.delta", { thought: "Evidence agrees." }, 5)
      + frame("text.delta", { delta: "No anomaly." }, 6)
      + frame("run.completed", {}, 7);
    expect(await collect(await transport(bytes(wire, true)))).toEqual([
      { type: "reasoning-start", id: reasoningId },
      { type: "reasoning-delta", id: reasoningId, delta: "Inspect " },
      { type: "reasoning-delta", id: reasoningId, delta: "route 🚕" },
      { type: "reasoning-end", id: reasoningId },
      { type: "tool-input-available", toolCallId: "lookup-1", toolName: "search", input: { query: "route" }, dynamic: true },
      { type: "tool-output-available", toolCallId: "lookup-1", output: { matched: true }, dynamic: true },
      { type: "reasoning-start", id: "reasoning-turn-test-2" },
      { type: "reasoning-delta", id: "reasoning-turn-test-2", delta: "Evidence agrees." },
      { type: "reasoning-end", id: "reasoning-turn-test-2" },
      { type: "text-start", id: textId },
      { type: "text-delta", id: textId, delta: "No anomaly." },
      { type: "text-end", id: textId },
      { type: "finish", finishReason: "stop" },
    ]);
  });

  it("keeps status labels as data and forwards optional status thoughts into reasoning", async () => {
    const wire = frame("status.thinking", { label: "Reviewing request" }, 0)
      + frame("status.thinking", { label: "Checking route", thought: "Compare GPS." }, 1)
      + frame("run.completed", {}, 2);
    expect(await collect(await transport(bytes(wire)))).toEqual([
      { type: "data-status", data: { label: "Reviewing request" } },
      { type: "data-status", data: { label: "Checking route" } },
      { type: "reasoning-start", id: reasoningId },
      { type: "reasoning-delta", id: reasoningId, delta: "Compare GPS." },
      { type: "reasoning-end", id: reasoningId },
      { type: "finish", finishReason: "stop" },
    ]);
  });

  it("preserves the real backend legacy thinking label without inventing reasoning text", async () => {
    const wire = 'event: thinking\ndata: {"status":"thinking","label":"Reviewing case evidence and relevant policy"}\n\n'
      + frame("run.completed", {}, 0);
    expect(await collect(await transport(bytes(wire)))).toEqual([
      { type: "data-status", data: { label: "Reviewing case evidence and relevant policy" } },
      { type: "finish", finishReason: "stop" },
    ]);
  });

  it("forwards a completed legacy thinking thought before closing its reasoning part", async () => {
    const wire = 'event: thinking\ndata: {"status":"completed","thought":"Check full route."}\n\n'
      + frame("text.delta", { delta: "Route checked." }, 0)
      + frame("run.completed", {}, 1);
    expect((await collect(await transport(bytes(wire)))).slice(0, 3)).toEqual([
      { type: "reasoning-start", id: reasoningId },
      { type: "reasoning-delta", id: reasoningId, delta: "Check full route." },
      { type: "reasoning-end", id: reasoningId },
    ]);
  });

  it.each(["run.completed", "run.error", "eof"])("closes active reasoning exactly once on %s", async (terminal) => {
    const wire = frame("reasoning.delta", { delta: "Partial thought" }, 0)
      + (terminal === "eof" ? "" : frame(terminal, { message: "Provider failed" }, 1))
      + (terminal === "eof" ? "" : frame("reasoning.delta", { delta: "Must ignore" }, 2));
    expect(await collect(await transport(bytes(wire)))).toEqual([
      { type: "reasoning-start", id: reasoningId },
      { type: "reasoning-delta", id: reasoningId, delta: "Partial thought" },
      { type: "reasoning-end", id: reasoningId },
      terminal === "run.error" ? { type: "error", errorText: "Provider failed" } : { type: "finish", finishReason: "stop" },
    ]);
  });

  it("cancels the upstream reader and closes active reasoning when aborted", async () => {
    const abort = new AbortController();
    const cancel = vi.fn();
    const upstream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(encoder.encode(frame("reasoning.delta", { delta: "Working" }, 0))); },
      cancel,
    });
    const reader = (await transport(upstream, abort.signal)).getReader();
    expect((await reader.read()).value).toEqual({ type: "reasoning-start", id: reasoningId });
    expect((await reader.read()).value).toEqual({ type: "reasoning-delta", id: reasoningId, delta: "Working" });
    abort.abort();
    expect((await reader.read()).value).toEqual({ type: "reasoning-end", id: reasoningId });
    expect((await reader.read()).done).toBe(true);
    expect(cancel).toHaveBeenCalledOnce();
    reader.releaseLock();
  });

  it("produces real AI SDK reasoning parts with the full streamed text and completed state", async () => {
    const wire = frame("reasoning.delta", { delta: "Check " }, 0)
      + frame("reasoning.delta", { delta: "route." }, 1)
      + frame("reasoning.end", {}, 2)
      + frame("text.delta", { delta: "Result." }, 3)
      + frame("run.completed", {}, 4);
    const stream = await transport(bytes(wire, true));
    const errors: unknown[] = [];
    let message: UIMessage | undefined;
    for await (const snapshot of readUIMessageStream({ stream, onError: (error) => errors.push(error) })) message = snapshot;
    expect(errors).toEqual([]);
    expect(message?.parts).toEqual([
      expect.objectContaining({ type: "reasoning", text: "Check route.", state: "done" }),
      expect.objectContaining({ type: "text", text: "Result.", state: "done" }),
    ]);
  });
});
