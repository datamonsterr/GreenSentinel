/**
 * AI SDK ChatTransport for GSupport driver chat (Issue #482).
 *
 * Consumes the `token` / `blocks` / `done` SSE lifecycle documented in
 * docs/CHAT_UI_EVENT_CONTRACT.md Step 4, from either:
 * - POST /api/v1/driver/chat/stream (case-less, no caseId)
 * - POST /api/v1/driver/cases/{caseId}/chat/stream (case-scoped)
 *
 * Driver identity is resolved server-side from the authenticated principal;
 * this transport never sends a client-chosen driver id.
 */

import type { ChatTransport, UIMessage, UIMessageChunk } from "ai";
import { getApiBaseUrl, authorizedHeaders } from "@/lib/api-client";

export interface DriverChatTransportOptions {
  caseId?: string;
  locale?: "vi" | "en";
  baseUrl?: string;
}

function extractText(lastUserMessage?: UIMessage): string {
  if (!lastUserMessage) return "";
  if (Array.isArray(lastUserMessage.parts)) {
    const text = lastUserMessage.parts
      .filter((p): p is { type: "text"; text: string } => p.type === "text")
      .map((p) => p.text)
      .join("");
    if (text) return text;
  }
  const content = (lastUserMessage as unknown as { content?: string }).content;
  return typeof content === "string" ? content : "";
}

export class DriverChatTransport implements ChatTransport<UIMessage> {
  private options: DriverChatTransportOptions;

  constructor(options: DriverChatTransportOptions = {}) {
    this.options = options;
  }

  public async reconnectToStream(): Promise<ReadableStream<UIMessageChunk> | null> {
    return null;
  }

  public async sendMessages(options: {
    trigger: "submit-message" | "regenerate-message";
    chatId: string;
    messageId: string | undefined;
    messages: UIMessage[];
    abortSignal: AbortSignal | undefined;
    headers?: HeadersInit;
    body?: any;
  }): Promise<ReadableStream<UIMessageChunk>> {
    const userMessages = options.messages.filter((m) => m.role === "user");
    const lastUserMessage = userMessages[userMessages.length - 1];
    const message = options.body?.message ?? extractText(lastUserMessage);

    const caseId = options.body?.case_id ?? this.options.caseId;
    const locale = options.body?.locale ?? this.options.locale ?? "vi";

    const baseUrl = this.options.baseUrl || getApiBaseUrl();
    const url = caseId
      ? `${baseUrl}/api/v1/driver/cases/${caseId}/chat/stream`
      : `${baseUrl}/api/v1/driver/chat/stream`;

    const payload: Record<string, unknown> = caseId
      ? { message, locale }
      : { message, locale };

    const fetchStream = async (forceRefresh = false): Promise<Response> => {
      const headers = await authorizedHeaders(
        {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(options.headers || {}),
        },
        forceRefresh
      );
      return fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: options.abortSignal,
      });
    };

    let res = await fetchStream(false);
    if (res.status === 401) {
      res = await fetchStream(true);
    }
    if (!res.ok) {
      const err = new Error(`Driver chat stream failed with status ${res.status}`);
      (err as any).status = res.status;
      throw err;
    }
    if (!res.body) {
      throw new Error("Empty SSE stream");
    }

    const byteStream = res.body;
    const messageId = options.messageId || `msg-${Date.now()}`;

    return new ReadableStream<UIMessageChunk>({
      async start(controller) {
        const reader = byteStream.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let textActive = false;
        const textId = `text-${messageId}`;
        let terminalEmitted = false;

        const startTextIfNeeded = () => {
          if (!textActive) {
            controller.enqueue({ type: "text-start", id: textId });
            textActive = true;
          }
        };
        const endTextIfActive = () => {
          if (textActive) {
            controller.enqueue({ type: "text-end", id: textId });
            textActive = false;
          }
        };

        const processEvent = (eventType: string, dataString: string) => {
          if (terminalEmitted) return;
          let parsed: any;
          try {
            parsed = JSON.parse(dataString);
          } catch {
            return;
          }

          switch (eventType) {
            case "token": {
              const delta = parsed?.token ?? parsed?.delta ?? "";
              startTextIfNeeded();
              controller.enqueue({ type: "text-delta", id: textId, delta });
              break;
            }
            case "tool.start": {
              controller.enqueue({
                type: "tool-input-available",
                toolCallId: parsed?.tool_call_id || "",
                toolName: parsed?.name || "",
                input: {},
                title: parsed?.label,
              });
              break;
            }
            case "tool.end": {
              if (parsed?.status === "error") {
                controller.enqueue({
                  type: "tool-output-error",
                  toolCallId: parsed?.tool_call_id || "",
                  errorText: "Tool execution failed",
                });
              } else {
                controller.enqueue({
                  type: "tool-output-available",
                  toolCallId: parsed?.tool_call_id || "",
                  output: { status: "ok" },
                });
              }
              break;
            }
            case "blocks": {
              endTextIfActive();
              controller.enqueue({
                type: "data-blocks",
                data: { blocks: parsed?.blocks || [] },
              });
              break;
            }
            case "done": {
              endTextIfActive();
              terminalEmitted = true;
              controller.enqueue({
                type: "data-done",
                data: parsed,
              });
              controller.enqueue({ type: "finish", finishReason: "stop" });
              break;
            }
            case "error": {
              endTextIfActive();
              terminalEmitted = true;
              controller.enqueue({
                type: "error",
                errorText: parsed?.message || "Agent request failed",
              });
              break;
            }
            default:
              break;
          }
        };

        if (options.abortSignal) {
          options.abortSignal.addEventListener("abort", () => {
            endTextIfActive();
            reader.cancel().catch(() => {});
            try {
              controller.close();
            } catch {
              // already closed
            }
          });
        }

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() ?? "";
            for (const part of parts) {
              if (!part.trim()) continue;
              let eventType = "message";
              let data = "";
              for (const line of part.split(/\r?\n/)) {
                if (line.startsWith("event:")) {
                  eventType = line.slice(6).trim();
                } else if (line.startsWith("data:")) {
                  const slice = line.slice(5).trim();
                  data = data ? `${data}\n${slice}` : slice;
                }
              }
              if (data) processEvent(eventType, data);
            }
          }
          endTextIfActive();
          if (!terminalEmitted) {
            // Contract: "A closed connection without a terminal event is
            // interrupted, not completed" (Issue #538 blocker #10). Never
            // silently report success for a stream that never sent `done`
            // or `error`.
            terminalEmitted = true;
            controller.enqueue({
              type: "error",
              errorText: "Stream ended without a terminal event",
            });
          }
        } catch (err) {
          endTextIfActive();
          if (!options.abortSignal?.aborted) {
            controller.error(err);
          }
        } finally {
          reader.releaseLock();
          try {
            controller.close();
          } catch {
            // already closed
          }
        }
      },
    });
  }
}
