import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { CaseCopilotTransport, AttachmentError } from "@/lib/copilot/transport";
import { setApiTokenProvider } from "@/lib/api-client";
import { readUIMessageStream } from "ai";
import type { UIMessage, UIMessageChunk } from "ai";

function createByteStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

async function collectChunks<T>(stream: ReadableStream<T>): Promise<T[]> {
  const reader = stream.getReader();
  const chunks: T[] = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }
  return chunks;
}

describe("CaseCopilotTransport (AI SDK ChatTransport)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    setApiTokenProvider(null);
  });

  describe("reconnectToStream", () => {
    it("always returns null", async () => {
      const transport = new CaseCopilotTransport({ caseId: "case-001" });
      const result = await transport.reconnectToStream({ chatId: "case-001" });
      expect(result).toBeNull();
    });
  });

  describe("POST request payload & auth", () => {
    it("maps reasoning stream events into UI message reasoning parts", async () => {
      const encoder = new TextEncoder();
      const sse = [
        `event: reasoning.start\ndata: {"type":"reasoning.start","payload":{"id":"r1"}}\n\n`,
        `event: reasoning.delta\ndata: {"type":"reasoning.delta","payload":{"id":"r1","delta":"Check policy"}}\n\n`,
        `event: reasoning.end\ndata: {"type":"reasoning.end","payload":{"id":"r1","duration_ms":42}}\n\n`,
        `event: run.completed\ndata: {}\n\n`,
      ].join("");
      global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body: createByteStream([encoder.encode(sse)]) });
      const stream = await new CaseCopilotTransport({ caseId: "case-alpha" }).sendMessages({
        trigger: "submit-message", chatId: "case-alpha", messageId: undefined,
        messages: [{ id: "u1", role: "user", parts: [{ type: "text", text: "Check" }] }], abortSignal: undefined,
      });
      expect(await collectChunks(stream)).toEqual(expect.arrayContaining([
        { type: "reasoning-start", id: expect.any(String) },
        { type: "reasoning-delta", id: expect.any(String), delta: "Check policy" },
        expect.objectContaining({ type: "reasoning-end", providerMetadata: { copilot: { durationMs: 42 } } }),
      ]));
    });

    it("consumes interleaved reasoning and answer into one completed UI message", async () => {
      const encoder = new TextEncoder();
      const sse = [
        `event: thinking_start\ndata: {"id":"r1"}\n\n`,
        `event: thinking_delta\ndata: {"id":"r1","text":"in"}\n\n`,
        `event: thinking_delta\ndata: {"id":"r1","text":"spect"}\n\n`,
        `event: thinking_end\ndata: {"id":"r1","duration_ms":7}\n\n`,
        `event: text.delta\ndata: {"delta":"Answer"}\n\n`,
        `event: run.completed\ndata: {}\n\n`,
      ].join("");
      global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body: createByteStream([encoder.encode(sse)]) });
      const transport = new CaseCopilotTransport({ caseId: "case-alpha" });
      const chunks = await transport.sendMessages({ trigger: "submit-message", chatId: "case-alpha", messageId: undefined,
        messages: [{ id: "u1", role: "user", parts: [{ type: "text", text: "Check" }] }], abortSignal: undefined });
      const snapshots: UIMessage[] = [];
      for await (const message of readUIMessageStream({ message: { id: "a1", role: "assistant", parts: [] }, stream: chunks })) snapshots.push(structuredClone(message));
      expect(snapshots.some((message) => message.parts.some((part) => part.type === "reasoning" && part.text === "in" && part.state === "streaming"))).toBe(true);
      const final = snapshots.at(-1)!;
      expect(final.parts).toEqual(expect.arrayContaining([
        expect.objectContaining({ type: "reasoning", text: "inspect", state: "done", providerMetadata: { copilot: { durationMs: 7 } } }),
        expect.objectContaining({ type: "text", text: "Answer", state: "done" }),
      ]));
    });

    it.each(["run.completed", "run.error", "eof"])("ends reasoning before transport %s", async (terminal) => {
      const encoder = new TextEncoder();
      const frames = [
        `event: reasoning-start\ndata: {"id":"r1"}\n\n`,
        `event: reasoning-delta\ndata: {"delta":"why"}\n\n`,
        ...(terminal === "eof" ? [] : [`event: ${terminal}\ndata: {}\n\n`]),
      ].join("");
      global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body: createByteStream([encoder.encode(frames)]) });
      const stream = await new CaseCopilotTransport({ caseId: "case-alpha" }).sendMessages({ trigger: "submit-message", chatId: "case-alpha", messageId: undefined,
        messages: [{ id: "u1", role: "user", parts: [{ type: "text", text: "Check" }] }], abortSignal: undefined });
      const chunks = await collectChunks(stream) as any[];
      const endIndex = chunks.findIndex((chunk) => chunk.type === "reasoning-end");
      expect(endIndex).toBeGreaterThanOrEqual(0);
      if (terminal === "run.completed") expect(chunks[endIndex + 1]?.type).toBe("finish");
      if (terminal === "run.error") expect(chunks[endIndex + 1]?.type).toBe("error");
      if (terminal === "eof") expect(chunks.at(-1)?.type).toBe("finish");
    });
    it("POSTs to /api/v1/policy/chat/stream with {query, case_id, turn_id, event_schema_version: '1.1', attachments}", async () => {
      setApiTokenProvider(async () => "mock-bearer-token");

      const encoder = new TextEncoder();
      const ssePayload = "event: run.completed\ndata: {\"type\":\"run.completed\",\"payload\":{\"status\":\"completed\"}}\n\n";

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: createByteStream([encoder.encode(ssePayload)]),
      });
      global.fetch = fetchMock;

      const transport = new CaseCopilotTransport({ caseId: "case-alpha" });

      const messages: UIMessage[] = [
        {
          id: "u1",
          role: "user",
          parts: [{ type: "text", text: "Kiểm tra quy định xử lý" }],
        },
      ];

      const stream = await transport.sendMessages({
        trigger: "submit-message",
        chatId: "case-alpha",
        messageId: undefined,
        messages,
        abortSignal: undefined,
      });

      await collectChunks(stream);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toContain("/api/v1/policy/chat/stream");
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer mock-bearer-token");

      const body = JSON.parse(init?.body as string);
      expect(body).toMatchObject({
        query: "Kiểm tra quy định xử lý",
        case_id: "case-alpha",
        event_schema_version: "1.1",
        attachments: [],
      });
      expect(body.turn_id).toBeDefined();
      expect(typeof body.turn_id).toBe("string");
    });
  });

  describe("image attachments extraction & validation", () => {
    it("extracts data URL image parts from last user message into attachments", async () => {
      const encoder = new TextEncoder();
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: createByteStream([encoder.encode("event: run.completed\ndata: {}\n\n")]),
      });

      const transport = new CaseCopilotTransport({ caseId: "case-01" });
      const smallBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

      const messages: UIMessage[] = [
        {
          id: "u1",
          role: "user",
          parts: [
            { type: "text", text: "Ảnh hiện trường" },
            {
              type: "file",
              mediaType: "image/png",
              filename: "evidence1.png",
              url: `data:image/png;base64,${smallBase64}`,
            },
          ],
        },
      ];

      const stream = await transport.sendMessages({
        trigger: "submit-message",
        chatId: "case-01",
        messageId: undefined,
        messages,
        abortSignal: undefined,
      });
      await collectChunks(stream);

      const fetchCall = vi.mocked(global.fetch).mock.calls[0];
      const body = JSON.parse(fetchCall[1]?.body as string);
      expect(body.attachments).toEqual([
        {
          name: "evidence1.png",
          media_type: "image/png",
          data_base64: smallBase64,
        },
      ]);
    });

    it("rejects more than 3 image attachments with typed AttachmentError", async () => {
      const transport = new CaseCopilotTransport({ caseId: "case-01" });
      const smallBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

      const messages: UIMessage[] = [
        {
          id: "u1",
          role: "user",
          parts: [
            { type: "text", text: "Nhiều ảnh" },
            { type: "file", mediaType: "image/png", filename: "1.png", url: `data:image/png;base64,${smallBase64}` },
            { type: "file", mediaType: "image/png", filename: "2.png", url: `data:image/png;base64,${smallBase64}` },
            { type: "file", mediaType: "image/png", filename: "3.png", url: `data:image/png;base64,${smallBase64}` },
            { type: "file", mediaType: "image/png", filename: "4.png", url: `data:image/png;base64,${smallBase64}` },
          ],
        },
      ];

      await expect(
        transport.sendMessages({
          trigger: "submit-message",
          chatId: "case-01",
          messageId: undefined,
          messages,
          abortSignal: undefined,
        })
      ).rejects.toThrow(AttachmentError);
    });

    it("rejects attachments larger than 4MB decoded with typed AttachmentError", async () => {
      const transport = new CaseCopilotTransport({ caseId: "case-01" });

      // Create a base64 string that decodes to > 4MB (4 * 1024 * 1024 = 4194304 bytes)
      // 4194305 bytes decoded requires ~5592408 base64 characters
      const largeBase64 = "A".repeat(5_600_000);

      const messages: UIMessage[] = [
        {
          id: "u1",
          role: "user",
          parts: [
            { type: "text", text: "Ảnh quá lớn" },
            {
              type: "file",
              mediaType: "image/jpeg",
              filename: "oversized.jpg",
              url: `data:image/jpeg;base64,${largeBase64}`,
            },
          ],
        },
      ];

      await expect(
        transport.sendMessages({
          trigger: "submit-message",
          chatId: "case-01",
          messageId: undefined,
          messages,
          abortSignal: undefined,
        })
      ).rejects.toThrow(AttachmentError);
    });

    it("rejects unsupported media type with typed AttachmentError", async () => {
      const transport = new CaseCopilotTransport({ caseId: "case-01" });
      const smallBase64 = "AAA=";

      const messages: UIMessage[] = [
        {
          id: "u1",
          role: "user",
          parts: [
            {
              type: "file",
              mediaType: "image/gif",
              filename: "anim.gif",
              url: `data:image/gif;base64,${smallBase64}`,
            },
          ],
        },
      ];

      await expect(
        transport.sendMessages({
          trigger: "submit-message",
          chatId: "case-01",
          messageId: undefined,
          messages,
          abortSignal: undefined,
        })
      ).rejects.toThrow(AttachmentError);
    });
  });

  describe("SSE event mapping & recorded replay", () => {
    const recordedEvents = [
      `event: status.thinking\ndata: {"schema_version":"1.1","type":"status.thinking","payload":{"label":"Đang phân tích câu hỏi"}}\n\n`,
      `event: tool.start\ndata: {"schema_version":"1.1","type":"tool.start","payload":{"tool_id":"query_policy","tool_name":"query_policy","tool_call_id":"call-1","input":{"article":"14.2"}}}\n\n`,
      `event: tool.end\ndata: {"schema_version":"1.1","type":"tool.end","payload":{"tool_id":"query_policy","tool_call_id":"call-1","status":"succeeded","output":{"found":true,"text":"Quy định 14.2"}}}\n\n`,
      `event: tool.start\ndata: {"schema_version":"1.1","type":"tool.start","payload":{"tool_id":"check_weather_condition","tool_name":"check_weather_condition","tool_call_id":"call-2","input":{"lat":21.0,"lng":105.8}}}\n\n`,
      `event: tool.end\ndata: {"schema_version":"1.1","type":"tool.end","payload":{"tool_id":"check_weather_condition","tool_call_id":"call-2","status":"failed","error":{"code":"SERVICE_UNAVAILABLE","message":"Cảm biến thời tiết không phản hồi"}}}\n\n`,
      `event: text.delta\ndata: {"schema_version":"1.1","type":"text.delta","payload":{"delta":"Theo kết quả tra cứu, "}}\n\n`,
      `event: text.delta\ndata: {"schema_version":"1.1","type":"text.delta","payload":{"delta":"tài xế không vi phạm."}}\n\n`,
      `event: citation\ndata: {"schema_version":"1.1","type":"citation","payload":{"id":"c1","source":"Quy chế 2026","section":"Điều 14.2","content":"Trường hợp bất khả kháng","score":0.98}}\n\n`,
      `event: citation\ndata: {"schema_version":"1.1","type":"citation","payload":{"id":"c2","source":"Sổ tay vận hành","section":"Phụ lục B","content":"Miễn trừ trách nhiệm","score":0.92}}\n\n`,
      `event: suggestions\ndata: {"schema_version":"1.1","type":"suggestions","payload":{"items":[{"label":"Miễn phạt tài xế","prompt":"Đề xuất miễn phạt"},{"label":"Kiểm tra lại GPS","prompt":"Kiểm tra lại dữ liệu GPS"}]}}\n\n`,
      `event: usage\ndata: {"schema_version":"1.1","type":"usage","payload":{"prompt_tokens":150,"completion_tokens":40,"total_tokens":190,"context_window":128000,"breakdown":{"system":20,"dossier":30,"history":40,"tool_results":50,"query":10}}}\n\n`,
      `event: interaction.request\ndata: {"schema_version":"1.1","type":"interaction.request","payload":{"question":"Bạn có muốn lập biên bản không?","options":["Có","Không"]}}\n\n`,
      `event: run.completed\ndata: {"schema_version":"1.1","type":"run.completed","payload":{"status":"completed"}}\n\n`,
    ];

    it("maps full recorded SSE stream to the exact UIMessageChunk sequence", async () => {
      const encoder = new TextEncoder();
      const rawText = recordedEvents.join("");

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: createByteStream([encoder.encode(rawText)]),
      });

      const transport = new CaseCopilotTransport({ caseId: "case-rec" });
      const stream = await transport.sendMessages({
        trigger: "submit-message",
        chatId: "case-rec",
        messageId: undefined,
        messages: [{ id: "m1", role: "user", parts: [{ type: "text", text: "Hỏi quy định" }] }],
        abortSignal: undefined,
      });

      const chunks = await collectChunks(stream);

      expect(chunks).toEqual([
        // status.thinking
        {
          type: "data-status",
          data: { label: "Đang phân tích câu hỏi" },
        },
        // tool 1 start
        {
          type: "tool-input-available",
          toolCallId: "call-1",
          toolName: "query_policy",
          input: { article: "14.2" },
          dynamic: true,
        },
        // tool 1 end (succeeded)
        {
          type: "tool-output-available",
          toolCallId: "call-1",
          output: { found: true, text: "Quy định 14.2" },
          dynamic: true,
        },
        // tool 2 start
        {
          type: "tool-input-available",
          toolCallId: "call-2",
          toolName: "check_weather_condition",
          input: { lat: 21.0, lng: 105.8 },
          dynamic: true,
        },
        // tool 2 end (failed)
        {
          type: "tool-output-error",
          toolCallId: "call-2",
          errorText: "Cảm biến thời tiết không phản hồi",
          dynamic: true,
        },
        // text delta 1 (starts text)
        {
          type: "text-start",
          id: expect.any(String),
        },
        {
          type: "text-delta",
          id: expect.any(String),
          delta: "Theo kết quả tra cứu, ",
        },
        // text delta 2
        {
          type: "text-delta",
          id: expect.any(String),
          delta: "tài xế không vi phạm.",
        },
        // text end before subsequent parts
        {
          type: "text-end",
          id: expect.any(String),
        },
        // citation 1
        {
          type: "data-citation",
          data: {
            id: "c1",
            source: "Quy chế 2026",
            section: "Điều 14.2",
            content: "Trường hợp bất khả kháng",
            score: 0.98,
          },
        },
        // citation 2
        {
          type: "data-citation",
          data: {
            id: "c2",
            source: "Sổ tay vận hành",
            section: "Phụ lục B",
            content: "Miễn trừ trách nhiệm",
            score: 0.92,
          },
        },
        // suggestions
        {
          type: "data-suggestions",
          data: {
            items: [
              { label: "Miễn phạt tài xế", prompt: "Đề xuất miễn phạt" },
              { label: "Kiểm tra lại GPS", prompt: "Kiểm tra lại dữ liệu GPS" },
            ],
          },
        },
        // usage
        {
          type: "data-usage",
          data: {
            prompt_tokens: 150,
            completion_tokens: 40,
            total_tokens: 190,
            context_window: 128000,
            breakdown: {
              system: 20,
              dossier: 30,
              history: 40,
              tool_results: 50,
              query: 10,
            },
          },
        },
        // interaction
        {
          type: "data-interaction",
          data: {
            question: "Bạn có muốn lập biên bản không?",
            options: ["Có", "Không"],
          },
        },
        // finish
        {
          type: "finish",
          finishReason: "stop",
        },
      ]);
    });

    it("correctly handles chunk boundaries splitting a frame across multibyte characters and lines", async () => {
      const encoder = new TextEncoder();
      const rawText = recordedEvents.join("");
      const fullBytes = encoder.encode(rawText);

      // Split raw bytes into arbitrary small chunks (17 bytes each)
      const byteChunks: Uint8Array[] = [];
      const chunkSize = 17;
      for (let i = 0; i < fullBytes.length; i += chunkSize) {
        byteChunks.push(fullBytes.slice(i, i + chunkSize));
      }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: createByteStream(byteChunks),
      });

      const transport = new CaseCopilotTransport({ caseId: "case-split" });
      const stream = await transport.sendMessages({
        trigger: "submit-message",
        chatId: "case-split",
        messageId: undefined,
        messages: [{ id: "m1", role: "user", parts: [{ type: "text", text: "Split test" }] }],
        abortSignal: undefined,
      });

      const chunks = await collectChunks(stream);

      // Must produce the exact same chunks despite fragmented bytes
      expect(chunks.length).toBe(15);
      expect(chunks[0]).toEqual({ type: "data-status", data: { label: "Đang phân tích câu hỏi" } });
      expect(chunks[chunks.length - 1]).toEqual({ type: "finish", finishReason: "stop" });
      expect(chunks.filter((c: UIMessageChunk) => c.type === "data-citation")).toHaveLength(2);
    });

    it("maps run.error event to error chunk", async () => {
      const encoder = new TextEncoder();
      const errorStream = [
        `event: status.thinking\ndata: {"type":"status.thinking","payload":{"label":"Khởi động"}}\n\n`,
        `event: text.delta\ndata: {"type":"text.delta","payload":{"delta":"Đang xử lý thì..."}}\n\n`,
        `event: run.error\ndata: {"type":"run.error","payload":{"code":"TIMEOUT","message":"Thời gian phản hồi vượt quá quy định"}}\n\n`,
      ].join("");

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: createByteStream([encoder.encode(errorStream)]),
      });

      const transport = new CaseCopilotTransport({ caseId: "case-err" });
      const stream = await transport.sendMessages({
        trigger: "submit-message",
        chatId: "case-err",
        messageId: undefined,
        messages: [{ id: "m1", role: "user", parts: [{ type: "text", text: "Error test" }] }],
        abortSignal: undefined,
      });

      const chunks = await collectChunks(stream);

      expect(chunks).toEqual([
        { type: "data-status", data: { label: "Khởi động" } },
        { type: "text-start", id: expect.any(String) },
        { type: "text-delta", id: expect.any(String), delta: "Đang xử lý thì..." },
        { type: "text-end", id: expect.any(String) },
        { type: "error", errorText: "Thời gian phản hồi vượt quá quy định" },
      ]);
    });

    it("maps canonical and legacy thinking text into collapsible reasoning chunks", async () => {
      const encoder = new TextEncoder();
      const streamText = [
        `event: reasoning.start\ndata: {"type":"reasoning.start","payload":{}}\n\n`,
        `event: reasoning.delta\ndata: {"type":"reasoning.delta","payload":{"delta":"Checking policy"}}\n\n`,
        `event: thinking\ndata: {"status":"streaming","thought":" and evidence"}\n\n`,
        `event: thinking\ndata: {"status":"completed"}\n\n`,
        `event: run.completed\ndata: {"type":"run.completed","payload":{}}\n\n`,
      ].join("");
      global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body: createByteStream([encoder.encode(streamText)]) });
      const transport = new CaseCopilotTransport({ caseId: "case-reasoning" });
      const stream = await transport.sendMessages({
        trigger: "submit-message", chatId: "case-reasoning", messageId: undefined,
        messages: [{ id: "m1", role: "user", parts: [{ type: "text", text: "Reason" }] }], abortSignal: undefined,
      });
      const chunks = await collectChunks(stream);
      expect(chunks.filter((chunk: UIMessageChunk) => chunk.type === "reasoning-start")).toHaveLength(1);
      expect(chunks.filter((chunk: UIMessageChunk) => chunk.type === "reasoning-delta")).toHaveLength(2);
      expect(chunks.filter((chunk: UIMessageChunk) => chunk.type === "reasoning-end")).toHaveLength(1);
      expect(chunks.at(-1)).toEqual({ type: "finish", finishReason: "stop" });
    });
  });
});
