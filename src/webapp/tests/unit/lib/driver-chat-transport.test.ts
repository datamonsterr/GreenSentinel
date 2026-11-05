import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DriverChatTransport } from "@/lib/driver/chat-transport";
import { setApiTokenProvider } from "@/lib/api-client";
import type { UIMessage, UIMessageChunk } from "ai";

function createByteStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collectChunks(stream: ReadableStream<UIMessageChunk>): Promise<UIMessageChunk[]> {
  const reader = stream.getReader();
  const chunks: UIMessageChunk[] = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }
  return chunks;
}

const userMessages: UIMessage[] = [
  { id: "u1", role: "user", parts: [{ type: "text", text: "Hello" }] },
];

describe("DriverChatTransport (AI SDK ChatTransport)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    setApiTokenProvider(null);
  });

  it("routes to the case-less endpoint when no caseId is configured", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: token\ndata: {"token":"Hi"}\n\n' +
      'event: blocks\ndata: {"blocks":[]}\n\n' +
      'event: done\ndata: {"status":"completed","reply":"Hi"}\n\n';
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });
    global.fetch = fetchMock;

    const transport = new DriverChatTransport({});
    await transport.sendMessages({
      trigger: "submit-message",
      chatId: "driver-chat-caseless",
      messageId: undefined,
      messages: userMessages,
      abortSignal: undefined,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/driver/chat/stream");
  });

  it("routes to the case-scoped endpoint when caseId is configured", async () => {
    const encoder = new TextEncoder();
    const sse = 'event: done\ndata: {"status":"completed","reply":"Hi"}\n\n';
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });
    global.fetch = fetchMock;

    const transport = new DriverChatTransport({ caseId: "case-123" });
    await transport.sendMessages({
      trigger: "submit-message",
      chatId: "case-123",
      messageId: undefined,
      messages: userMessages,
      abortSignal: undefined,
    });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/driver/cases/case-123/chat/stream");
  });

  it("maps token/blocks/done into text-delta/data-blocks/data-done + finish, exactly one terminal chunk", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: token\ndata: {"token":"Hi "}\n\n' +
      'event: token\ndata: {"token":"there"}\n\n' +
      'event: blocks\ndata: {"blocks":[{"type":"status_pill","status_key":"in_dispute"}]}\n\n' +
      'event: done\ndata: {"status":"completed","reply":"Hi there"}\n\n';
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    const types = chunks.map((c) => c.type);
    expect(types).toContain("text-delta");
    expect(types).toContain("data-blocks");
    expect(types).toContain("data-done");
    expect(types.filter((t) => t === "finish")).toHaveLength(1);
    expect(types.filter((t) => t === "error")).toHaveLength(0);
  });

  it("maps an `error` SSE event to a single error chunk, never a finish", async () => {
    const encoder = new TextEncoder();
    const sse = 'event: error\ndata: {"message":"Agent request failed"}\n\n';
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    expect(chunks.filter((c) => c.type === "error")).toHaveLength(1);
    expect(chunks.filter((c) => c.type === "finish")).toHaveLength(0);
  });

  it("treats a stream that ends without a terminal `done`/`error` event as an error, never a silent success", async () => {
    const encoder = new TextEncoder();
    // Only token events, connection simply closes — interrupted, not completed.
    const sse = 'event: token\ndata: {"token":"partial"}\n\n';
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    expect(chunks.filter((c) => c.type === "finish")).toHaveLength(0);
    expect(chunks.filter((c) => c.type === "error")).toHaveLength(1);
  });

  it("never emits a chunk after the terminal event, even if more SSE frames follow", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: done\ndata: {"status":"completed","reply":"Hi"}\n\n' +
      // A stale/duplicate frame after done must be ignored.
      'event: token\ndata: {"token":"stale"}\n\n';
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    expect(chunks.filter((c) => c.type === "finish")).toHaveLength(1);
    expect(chunks.filter((c) => c.type === "text-delta")).toHaveLength(0);
  });

  it("does not emit an error chunk when the caller aborts intentionally", async () => {
    const controller = new AbortController();
    let cancelled = false;
    const byteStream = new ReadableStream<Uint8Array>({
      start() {
        // Never closes on its own; only the abort listener should end it.
      },
      cancel() {
        cancelled = true;
      },
    });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: byteStream,
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: controller.signal,
    });

    const reader = stream.getReader();
    const readPromise = reader.read();
    controller.abort();
    await readPromise;

    expect(cancelled).toBe(true);
  });

  it("parses `tool.start` and `tool.end` events into AI SDK tool parts", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: tool.start\ndata: {"tool_call_id":"tc-1","name":"corroborate_traffic_conditions","label":"Đang đối soát tình trạng giao thông"}\n\n' +
      'event: tool.end\ndata: {"tool_call_id":"tc-1","name":"corroborate_traffic_conditions","status":"ok"}\n\n' +
      'event: token\ndata: {"token":"Dữ liệu hợp lệ"}\n\n' +
      'event: done\ndata: {"status":"completed","reply":"Dữ liệu hợp lệ"}\n\n';

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    const toolInput = chunks.find((c) => c.type === "tool-input-available") as any;
    expect(toolInput).toBeDefined();
    expect(toolInput.toolCallId).toBe("tc-1");
    expect(toolInput.toolName).toBe("corroborate_traffic_conditions");
    expect(toolInput.title).toBe("Đang đối soát tình trạng giao thông");

    const toolOutput = chunks.find((c) => c.type === "tool-output-available") as any;
    expect(toolOutput).toBeDefined();
    expect(toolOutput.toolCallId).toBe("tc-1");
  });

  it("parses `tool.end` with status='error' into a tool-output-error chunk", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: tool.start\ndata: {"tool_call_id":"tc-err","name":"check_weather_condition","label":"Đang kiểm tra thời tiết"}\n\n' +
      'event: tool.end\ndata: {"tool_call_id":"tc-err","name":"check_weather_condition","status":"error"}\n\n' +
      'event: done\ndata: {"status":"completed","reply":"Lỗi kết nối thời tiết"}\n\n';

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: createByteStream([encoder.encode(sse)]),
    });

    const transport = new DriverChatTransport({});
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "c1",
      messageId: "m1",
      messages: userMessages,
      abortSignal: undefined,
    });
    const chunks = await collectChunks(stream);

    const toolError = chunks.find((c) => c.type === "tool-output-error") as any;
    expect(toolError).toBeDefined();
    expect(toolError.toolCallId).toBe("tc-err");
  });
});

