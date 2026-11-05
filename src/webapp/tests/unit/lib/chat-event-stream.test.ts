import { describe, it, expect, vi } from "vitest";
import {
  ChatEventStreamParser,
  consumeChatEventStream,
  ChatStreamState,
} from "@/lib/chat-event-stream";

function createChunkStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

function createByteChunkStream(byteChunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of byteChunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

describe("ChatEventStreamParser & consumeChatEventStream (T7)", () => {
  it("accumulates legacy completed thinking thought and canonical reasoning deltas", async () => {
    const onReasoning = vi.fn();
    const state = await consumeChatEventStream(createChunkStream([
      `event: thinking\ndata: {"status":"streaming","thought":"first ","label":"Reviewing"}\n\n`,
      `event: thinking\ndata: {"status":"completed","thought":"second"}\n\n`,
      `event: run.completed\ndata: {"type":"run.completed","payload":{}}\n\n`,
    ]), { onReasoning });
    expect(state.reasoning).toBe("first second");
    expect(onReasoning).toHaveBeenNthCalledWith(1, "first ", "first ");
    expect(onReasoning).toHaveBeenNthCalledWith(2, "second", "first second");
  });

  it("accumulates canonical reasoning blocks without losing prior text", () => {
    const onReasoning = vi.fn();
    const parser = new ChatEventStreamParser({ onReasoning });
    const event = (id: string, sequence: number, type: string, payload: Record<string, unknown>) =>
      JSON.stringify({ event_id: id, run_id: "reasoning-run", sequence, type, payload });
    parser.processSseMessage("reasoning.start", event("r0", 0, "reasoning.start", {}));
    parser.processSseMessage("reasoning.delta", event("r1", 1, "reasoning.delta", { delta: "first" }));
    parser.processSseMessage("reasoning.end", event("r2", 2, "reasoning.end", { duration_ms: 10 }));
    parser.processSseMessage("reasoning.start", event("r3", 3, "reasoning.start", {}));
    parser.processSseMessage("reasoning.delta", event("r4", 4, "reasoning.delta", { delta: " second" }));
    expect(parser.getState().reasoning).toBe("first second");
    expect(onReasoning).toHaveBeenLastCalledWith(" second", "first second");
  });

  it("emits explicit reasoning deltas and closes the part on terminal", async () => {
    const onReasoningStart = vi.fn();
    const onReasoningDelta = vi.fn();
    const onReasoningEnd = vi.fn();
    const state = await consumeChatEventStream(createChunkStream([
      `event: reasoning.start\ndata: {"type":"reasoning.start","payload":{"id":"r-1"}}\n\n`,
      `event: reasoning.delta\ndata: {"type":"reasoning.delta","payload":{"id":"r-1","delta":"Read "}}\n\n`,
      `event: reasoning.delta\ndata: {"type":"reasoning.delta","payload":{"id":"r-1","delta":"policy"}}\n\n`,
      `event: run.completed\ndata: {"type":"run.completed","payload":{}}\n\n`,
    ]), { onReasoningStart, onReasoningDelta, onReasoningEnd });
    expect(state.status).toBe("completed");
    expect(onReasoningStart).toHaveBeenCalledWith("r-1");
    expect(onReasoningDelta).toHaveBeenNthCalledWith(2, "policy", "Read policy");
    expect(onReasoningEnd).toHaveBeenCalledWith("r-1", expect.any(Number));
  });

  it("treats legacy thinking text as reasoning while retaining label-only status", async () => {
    const onThinking = vi.fn();
    const onReasoningDelta = vi.fn();
    const state = await consumeChatEventStream(createChunkStream([
      `event: thinking\ndata: {"label":"Reviewing"}\n\n`,
      `event: thinking\ndata: {"text":"inspect evidence"}\n\n`,
      `event: done\ndata: {}\n\n`,
    ]), { onThinking, onReasoningDelta });
    expect(onThinking).toHaveBeenCalledWith("Reviewing");
    expect(onReasoningDelta).toHaveBeenCalledWith("inspect evidence", "inspect evidence");
    expect(state.thinking).toBe("Reviewing");
  });

  it.each([
    ["thinking_start", "thinking_delta", "thinking_end"],
    ["reasoning_start", "reasoning_delta", "reasoning_end"],
  ])("supports legacy %s/%s/%s aliases and closes before answer", async (start, delta, end) => {
    const onReasoningStart = vi.fn();
    const onReasoningEnd = vi.fn();
    const state = await consumeChatEventStream(createChunkStream([
      `event: ${start}\ndata: {"id":"one"}\n\n`,
      `event: ${delta}\ndata: {"delta":"why"}\n\n`,
      `event: text_delta\ndata: {"delta":"answer"}\n\n`,
      `event: ${end}\ndata: {"id":"one","duration_ms":-4}\n\n`,
      `event: done\ndata: {}\n\n`,
    ]), { onReasoningStart, onReasoningEnd });
    expect(state.text).toBe("answer");
    expect(onReasoningStart).toHaveBeenCalledTimes(1);
    expect(onReasoningEnd).toHaveBeenCalledWith("one", expect.any(Number));
    expect(onReasoningEnd.mock.calls[0][1]).toBeGreaterThanOrEqual(0);
  });

  it("closes each reasoning phase with a distinct id before tools", async () => {
    const starts = vi.fn();
    const ends = vi.fn();
    await consumeChatEventStream(createChunkStream([
      `event: reasoning.start\ndata: {"id":"one"}\n\n`,
      `event: reasoning.delta\ndata: {"delta":"first"}\n\n`,
      `event: tool_call\ndata: {"tool":"lookup","status":"running"}\n\n`,
      `event: reasoning.start\ndata: {"id":"two"}\n\n`,
      `event: reasoning.delta\ndata: {"delta":"second"}\n\n`,
      `event: done\ndata: {}\n\n`,
    ]), { onReasoningStart: starts, onReasoningEnd: ends });
    expect(starts.mock.calls.map(([id]) => id)).toEqual(["one", "two"]);
    expect(ends).toHaveBeenCalledTimes(2);
  });

  it.each(["run.completed", "run.error", "eof"])("closes reasoning exactly once on %s", async (terminal) => {
    const onReasoningDelta = vi.fn();
    const onReasoningEnd = vi.fn();
    const frames = [
      `event: reasoning_start\ndata: {"id":"r"}\n\n`,
      `event: reasoning_delta\ndata: {"delta":"in"}\n\n`,
      `event: reasoning_delta\ndata: {"delta":"sight"}\n\n`,
      ...(terminal === "eof" ? [] : [`event: ${terminal}\ndata: ${JSON.stringify({ type: terminal, payload: terminal === "run.error" ? { message: "bad" } : {} })}\n\n`]),
    ];
    const state = await consumeChatEventStream(createChunkStream(frames), { onReasoningDelta, onReasoningEnd });
    expect(onReasoningDelta).toHaveBeenLastCalledWith("sight", "insight");
    expect(onReasoningEnd).toHaveBeenCalledTimes(1);
    expect(state.status).toBe(terminal === "run.completed" ? "completed" : terminal === "run.error" ? "error" : "interrupted");
  });
  it("assembles frames split across CRLF, JSON strings and multibyte UTF-8 boundaries", async () => {
    const encoder = new TextEncoder();
    const fullText = "event: text.delta\r\ndata: {\"schema_version\":\"1.1\",\"event_id\":\"evt-1\",\"run_id\":\"run-1\",\"message_id\":\"msg-1\",\"sequence\":0,\"type\":\"text.delta\",\"payload\":{\"delta\":\"Căn cứ theo điều 14.2 quy định về vi phạm.\"}}\r\n\r\n";
    const bytes = encoder.encode(fullText);

    // Split right in the middle of a Vietnamese multibyte character "đ" (UTF-8 0xC4 0x91)
    const splitIndex = fullText.indexOf("điều") + 1; // within multibyte
    const chunk1 = bytes.slice(0, splitIndex);
    const chunk2 = bytes.slice(splitIndex);

    const onDelta = vi.fn();
    const onTerminal = vi.fn();

    const state = await consumeChatEventStream(createByteChunkStream([chunk1, chunk2]), {
      onDelta,
      onTerminal,
    });

    expect(state.text).toBe("Căn cứ theo điều 14.2 quy định về vi phạm.");
    expect(onDelta).toHaveBeenCalledWith("Căn cứ theo điều 14.2 quy định về vi phạm.", "Căn cứ theo điều 14.2 quy định về vi phạm.");
  });

  it("handles parallel and repeated tools with independent call identity", async () => {
    const events = [
      `event: tool.start\ndata: {"schema_version":"1.1","event_id":"e-1","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"tool.start","payload":{"tool_id":"search_policy","tool_name":"search_policy","tool_call_id":"call-1","label":"Tra cứu quy chế"}}\n\n`,
      `event: tool.start\ndata: {"schema_version":"1.1","event_id":"e-2","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"tool.start","payload":{"tool_id":"search_policy","tool_name":"search_policy","tool_call_id":"call-2","label":"Tra cứu quy chế lần 2"}}\n\n`,
      `event: tool.end\ndata: {"schema_version":"1.1","event_id":"e-3","run_id":"run-1","message_id":"msg-1","sequence":2,"type":"tool.end","payload":{"tool_id":"search_policy","tool_call_id":"call-2","status":"succeeded","duration_ms":120,"summary":"Điều 14.2"}}\n\n`,
      `event: tool.end\ndata: {"schema_version":"1.1","event_id":"e-4","run_id":"run-1","message_id":"msg-1","sequence":3,"type":"tool.end","payload":{"tool_id":"search_policy","tool_call_id":"call-1","status":"failed","duration_ms":250,"error":{"code":"SOURCE_UNAVAILABLE","message":"Không khả dụng","retryable":true}}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","event_id":"e-5","run_id":"run-1","message_id":"msg-1","sequence":4,"type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    const state = await consumeChatEventStream(createChunkStream(events));

    expect(state.status).toBe("completed");
    expect(state.tools["call-1"]).toEqual({
      tool_id: "search_policy",
      tool_name: "search_policy",
      tool_call_id: "call-1",
      status: "failed",
      label: "Tra cứu quy chế",
      duration_ms: 250,
      summary: undefined,
      error: { code: "SOURCE_UNAVAILABLE", message: "Không khả dụng", retryable: true },
    });
    expect(state.tools["call-2"]).toEqual({
      tool_id: "search_policy",
      tool_name: "search_policy",
      tool_call_id: "call-2",
      status: "succeeded",
      label: "Tra cứu quy chế lần 2",
      duration_ms: 120,
      summary: "Điều 14.2",
      error: undefined,
    });
    expect(Object.values(state.tools).every((t) => t.status !== "pending")).toBe(true);
  });

  it("retains sanitized tool output from canonical tool.end events", async () => {
    const events = [
      `event: tool.start\ndata: {"schema_version":"1.1","event_id":"e-1","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"tool.start","payload":{"tool_id":"fetch_corridor_historical_traffic","tool_call_id":"traffic-1"}}\n\n`,
      `event: tool.end\ndata: {"schema_version":"1.1","event_id":"e-2","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"tool.end","payload":{"tool_id":"fetch_corridor_historical_traffic","tool_call_id":"traffic-1","status":"succeeded","duration_ms":12,"output":{"source_type":"first_party_peer_telemetry","peer_count":3}}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","event_id":"e-3","run_id":"run-1","message_id":"msg-1","sequence":2,"type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    const state = await consumeChatEventStream(createChunkStream(events));

    expect(state.tools["traffic-1"].output).toEqual({
      source_type: "first_party_peer_telemetry",
      peer_count: 3,
    });
  });

  it("deduplicates replayed event IDs and ignores exact replays", async () => {
    const events = [
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-dup","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Xin chào "}}\n\n`,
      // Exact replayed event
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-dup","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Xin chào "}}\n\n`,
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-next","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"text.delta","payload":{"delta":"bạn"}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","event_id":"e-end","run_id":"run-1","message_id":"msg-1","sequence":2,"type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    const onDelta = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(events), { onDelta });

    expect(state.text).toBe("Xin chào bạn");
    expect(onDelta).toHaveBeenCalledTimes(2);
  });

  it("marks stream interrupted on conflicting duplicate event IDs", async () => {
    const events = [
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-conflict","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Lời chào 1"}}\n\n`,
      // Same event_id but conflicting payload!
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-conflict","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Lời chào khác"}}\n\n`,
    ];

    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(events), { onTerminal });

    expect(state.status).toBe("interrupted");
    expect(state.error?.code).toBe("CONFLICT");
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });

  it("marks stream interrupted on sequence gaps", async () => {
    const events = [
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-0","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Bắt đầu"}}\n\n`,
      // Sequence jumps to 2 (missing 1)
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-2","run_id":"run-1","message_id":"msg-1","sequence":2,"type":"text.delta","payload":{"delta":"Bỏ qua"}}\n\n`,
    ];

    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(events), { onTerminal });

    expect(state.status).toBe("interrupted");
    expect(state.error?.code).toBe("SEQUENCE_GAP");
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });

  it("handles EOF before terminal: marks interrupted, retains partial text, closes pending tools, fires onTerminal once", async () => {
    const events = [
      `event: status.thinking\ndata: {"schema_version":"1.1","event_id":"e-0","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"status.thinking","payload":{"label":"Đang chuẩn bị"}}\n\n`,
      `event: tool.start\ndata: {"schema_version":"1.1","event_id":"e-1","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"tool.start","payload":{"tool_id":"query_policy","tool_call_id":"c-pending","label":"Đang tra cứu"}}\n\n`,
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-2","run_id":"run-1","message_id":"msg-1","sequence":2,"type":"text.delta","payload":{"delta":"Partial answer"}}\n\n`,
      // Sudden stream EOF here! No run.completed or run.error
    ];

    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(events), { onTerminal });

    expect(state.status).toBe("interrupted");
    expect(state.text).toBe("Partial answer");
    expect(Object.values(state.tools).every((tool) => tool.status !== "pending")).toBe(true);
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });

  it("handles user abort: closes pending tools, marks interrupted, fires onTerminal once", async () => {
    const controller = new AbortController();
    const encoder = new TextEncoder();

    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.enqueue(
          encoder.encode(
            `event: tool.start\ndata: {"schema_version":"1.1","event_id":"e-0","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"tool.start","payload":{"tool_id":"lookup","tool_call_id":"c-1"}}\n\n`
          )
        );
        ctrl.enqueue(
          encoder.encode(
            `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-1","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"text.delta","payload":{"delta":"Đang phân tích"}}\n\n`
          )
        );
        // Abort right here!
        controller.abort();
      },
    });

    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(stream, {
      onTerminal,
      signal: controller.signal,
    });

    expect(state.status).toBe("interrupted");
    expect(Object.values(state.tools).every((tool) => tool.status !== "pending")).toBe(true);
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });

  it("rejects stale events from previous runs", async () => {
    const events = [
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-0","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"text.delta","payload":{"delta":"Run 1"}}\n\n`,
      // Stale event from run-old
      `event: text.delta\ndata: {"schema_version":"1.1","event_id":"e-stale","run_id":"run-old","message_id":"msg-0","sequence":0,"type":"text.delta","payload":{"delta":" Stale"}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","event_id":"e-1","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    const state = await consumeChatEventStream(createChunkStream(events));

    expect(state.status).toBe("completed");
    expect(state.text).toBe("Run 1");
  });

  it("preserves policy citations in state", async () => {
    const events = [
      `event: citation\ndata: {"schema_version":"1.1","event_id":"e-cit","run_id":"run-1","message_id":"msg-1","sequence":0,"type":"citation","payload":{"source":"GreenSM 2026","section":"14.2","content":"Nội dung quy chế"}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","event_id":"e-end","run_id":"run-1","message_id":"msg-1","sequence":1,"type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    const onCitation = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(events), { onCitation });

    expect(state.citations).toHaveLength(1);
    expect(state.citations[0].section).toBe("14.2");
    expect(onCitation).toHaveBeenCalledWith(expect.objectContaining({ section: "14.2" }));
  });

  it("supports legacy unnegotiated SSE event streams gracefully", async () => {
    const legacyEvents = [
      `event: thinking\ndata: {"label":"Đang tra cứu hồ sơ"}\n\n`,
      `event: tool_call\ndata: {"tool":"search_policy","status":"running"}\n\n`,
      `event: text_delta\ndata: {"delta":"Kết quả tra cứu: "}\n\n`,
      `event: citation\ndata: {"source":"Quy chế 2026","section":"Điều 5","content":"Nội dung"}\n\n`,
      `event: tool_done\ndata: {"tool":"search_policy","status":"success"}\n\n`,
      `event: done\ndata: {"status":"completed"}\n\n`,
    ];

    const onDelta = vi.fn();
    const onTerminal = vi.fn();
    const state = await consumeChatEventStream(createChunkStream(legacyEvents), {
      onDelta,
      onTerminal,
    });

    expect(state.status).toBe("completed");
    expect(state.text).toBe("Kết quả tra cứu: ");
    expect(state.citations).toHaveLength(1);
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });
});
