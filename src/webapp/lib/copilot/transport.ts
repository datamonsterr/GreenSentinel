/**
 * AI SDK ChatTransport implementation for VinUni AI20K Copilot.
 * Connects to /api/v1/policy/chat/stream (event_schema_version: "1.1")
 * and maps SSE events into AI SDK UIMessageChunks.
 */

import type { ChatTransport, UIMessage, UIMessageChunk } from "ai";
import { getApiBaseUrl, authorizedHeaders } from "@/lib/api-client";

export class AttachmentError extends Error {
  readonly code: string;

  constructor(message: string, code: string = "ATTACHMENT_ERROR") {
    super(message);
    this.name = "AttachmentError";
    this.code = code;
  }
}

export class AttachmentValidationError extends AttachmentError {
  constructor(message: string, code: string = "ATTACHMENT_VALIDATION_ERROR") {
    super(message, code);
    this.name = "AttachmentValidationError";
  }
}

export interface PolicyChatAttachment {
  name: string;
  media_type: "image/png" | "image/jpeg" | "image/webp";
  data_base64: string;
}

export interface CaseCopilotTransportOptions {
  caseId?: string;
  baseUrl?: string;
}

const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_ATTACHMENTS = 3;
const MAX_DECODED_BYTES = 4 * 1024 * 1024; // 4MB

/**
 * Calculates base64 decoded size in bytes without full buffer allocation.
 */
function getBase64DecodedSize(b64: string): number {
  const clean = b64.replace(/[\r\n\s]/g, "");
  if (!clean) return 0;
  const padding = clean.endsWith("==") ? 2 : clean.endsWith("=") ? 1 : 0;
  return Math.floor((clean.length * 3) / 4) - padding;
}

/**
 * Extracts and validates image attachments from the last user message.
 */
function extractAttachments(lastUserMessage?: UIMessage): PolicyChatAttachment[] {
  if (!lastUserMessage || !Array.isArray(lastUserMessage.parts)) {
    return [];
  }

  const attachments: PolicyChatAttachment[] = [];
  let fileIndex = 0;

  for (const part of lastUserMessage.parts) {
    const isFilePart = part.type === "file" || (part as any).type === "image";
    if (!isFilePart) continue;

    const rawUrl = (part as any).url;
    if (typeof rawUrl !== "string") continue;

    fileIndex++;
    const dataUrlMatch = rawUrl.match(/^data:([^;]+);base64,([\s\S]+)$/);
    if (!dataUrlMatch) {
      continue;
    }

    let rawMediaType = (part as any).mediaType || dataUrlMatch[1];
    rawMediaType = rawMediaType.toLowerCase().trim();
    if (rawMediaType === "image/jpg") {
      rawMediaType = "image/jpeg";
    }

    if (!ALLOWED_IMAGE_TYPES.has(rawMediaType)) {
      throw new AttachmentValidationError(
        `Unsupported image media type: ${rawMediaType}. Only PNG, JPEG, and WebP are allowed.`,
        "UNSUPPORTED_MEDIA_TYPE"
      );
    }

    const dataBase64 = dataUrlMatch[2].replace(/\s/g, "");
    const decodedSize = getBase64DecodedSize(dataBase64);

    if (decodedSize > MAX_DECODED_BYTES) {
      throw new AttachmentValidationError(
        `Image attachment exceeds 4MB limit (decoded size: ${decodedSize} bytes).`,
        "ATTACHMENT_TOO_LARGE"
      );
    }

    const extension = rawMediaType.split("/")[1] || "png";
    const filename =
      (part as any).filename ||
      (part as any).name ||
      `attachment-${fileIndex}.${extension}`;

    attachments.push({
      name: filename,
      media_type: rawMediaType as "image/png" | "image/jpeg" | "image/webp",
      data_base64: dataBase64,
    });
  }

  if (attachments.length > MAX_ATTACHMENTS) {
    throw new AttachmentValidationError(
      `Too many attachments: maximum ${MAX_ATTACHMENTS} allowed, received ${attachments.length}.`,
      "MAX_ATTACHMENTS_EXCEEDED"
    );
  }

  return attachments;
}

export class CaseCopilotTransport implements ChatTransport<UIMessage> {
  private options: CaseCopilotTransportOptions;

  constructor(options: CaseCopilotTransportOptions | string = {}) {
    if (typeof options === "string") {
      this.options = { caseId: options };
    } else {
      this.options = options;
    }
  }

  public async reconnectToStream(
    _options?: {
      chatId: string;
      abortSignal?: AbortSignal;
    } & Record<string, any>
  ): Promise<ReadableStream<UIMessageChunk> | null> {
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
    metadata?: any;
  }): Promise<ReadableStream<UIMessageChunk>> {
    const userMessages = options.messages.filter((m) => m.role === "user");
    const lastUserMessage = userMessages[userMessages.length - 1];

    let query = "";
    if (lastUserMessage && Array.isArray(lastUserMessage.parts)) {
      query = lastUserMessage.parts
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("");
    }
    if (!query && lastUserMessage && typeof (lastUserMessage as any).content === "string") {
      query = (lastUserMessage as any).content;
    }
    if (options.body?.query) {
      query = options.body.query;
    }

    const attachments =
      options.body?.attachments !== undefined
        ? options.body.attachments
        : extractAttachments(lastUserMessage);

    const caseId =
      options.body?.case_id ||
      options.metadata?.case_id ||
      this.options.caseId ||
      options.chatId;

    const turnId =
      options.body?.turn_id ||
      options.metadata?.turn_id ||
      (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `turn-${Date.now()}`);

    const payload: Record<string, any> = {
      query,
      case_id: caseId,
      turn_id: turnId,
      event_schema_version: "1.1",
      attachments,
      ...(options.body || {}),
    };

    const baseUrl = this.options.baseUrl || getApiBaseUrl();
    const url = `${baseUrl}/api/v1/policy/chat/stream`;

    const fetchStream = async (forceRefresh: boolean = false): Promise<Response> => {
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
      throw new Error(`Policy Chat stream failed with status ${res.status}`);
    }

    if (!res.body) {
      throw new Error("Empty SSE stream");
    }

    const byteStream = res.body;

    return new ReadableStream<UIMessageChunk>({
      async start(controller) {
        const reader = byteStream.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        let textActive = false;
        let textPartIndex = 0;
        let currentTextId = `text-${turnId}-${textPartIndex}`;
        let terminalEmitted = false;
        let reasoningActive = false;
        let reasoningPartIndex = 0;
        let reasoningId = `reasoning-${turnId}-${reasoningPartIndex}`;

        const endTextIfActive = () => {
          if (textActive) {
            controller.enqueue({
              type: "text-end",
              id: currentTextId,
            });
            textActive = false;
          }
        };

        const startReasoning = (id?: string) => {
          if (reasoningActive) return;
          reasoningPartIndex++;
          reasoningId = id || `reasoning-${turnId}-${reasoningPartIndex}`;
          reasoningActive = true;
          controller.enqueue({ type: "reasoning-start", id: reasoningId });
        };

        const endReasoningIfActive = (durationMs?: number) => {
          if (!reasoningActive) return;
          const elapsed = Number.isFinite(durationMs) && durationMs! >= 0 ? durationMs : undefined;
          controller.enqueue({ type: "reasoning-end", id: reasoningId, ...(elapsed === undefined ? {} : { providerMetadata: { copilot: { durationMs: elapsed } } }) });
          reasoningActive = false;
        };

        const processEvent = (eventType: string, dataString: string) => {
          if (terminalEmitted) return;

          let parsed: any;
          try {
            parsed = JSON.parse(dataString);
          } catch {
            return;
          }

          const type = parsed?.event || parsed?.type || eventType;
          const eventPayload = parsed?.payload !== undefined ? parsed.payload : parsed;

          switch (type) {
            case "status.thinking": {
              endTextIfActive();
              controller.enqueue({
                type: "data-status",
                data: {
                  label: eventPayload?.label || "Reviewing request",
                },
              });
              const thought = eventPayload?.thought ?? eventPayload?.delta ?? eventPayload?.text ?? eventPayload?.content;
              if (typeof thought === "string" && thought) {
                startReasoning(eventPayload?.id || eventPayload?.reasoning_id);
                controller.enqueue({ type: "reasoning-delta", id: reasoningId, delta: thought });
              }
              break;
            }

            case "reasoning.start":
            case "reasoning-start":
            case "reasoning_start":
            case "thinking.start":
            case "thinking-start":
            case "thinking_start":
              endReasoningIfActive();
              endTextIfActive();
              startReasoning(eventPayload?.id || eventPayload?.reasoning_id);
              break;

            case "reasoning.delta":
            case "reasoning-delta":
            case "reasoning_delta":
            case "thinking.delta":
            case "thinking-delta":
            case "thinking_delta":
            case "thinking":
            case "reasoning": {
              endTextIfActive();
              if (type === "thinking" && typeof eventPayload?.label === "string") {
                controller.enqueue({ type: "data-status", data: { label: eventPayload.label } });
              }
              const delta = eventPayload?.delta ?? eventPayload?.text ?? eventPayload?.thought ?? eventPayload?.content ?? "";
              if (typeof delta === "string" && delta) {
                startReasoning(eventPayload?.id || eventPayload?.reasoning_id);
                controller.enqueue({ type: "reasoning-delta", id: reasoningId, delta });
              }
              if (type === "thinking") {
                if (["end", "completed", "done"].includes(eventPayload?.status)) endReasoningIfActive(eventPayload?.duration_ms);
                else if (!delta && ["start", "streaming"].includes(eventPayload?.status)) startReasoning(eventPayload?.id || eventPayload?.reasoning_id);
              }
              break;
            }

            case "reasoning.end":
            case "reasoning-end":
            case "reasoning_end":
            case "thinking.end":
            case "thinking-end":
            case "thinking_end":
              endReasoningIfActive(eventPayload?.duration_ms);
              break;

            case "tool.start": {
              endReasoningIfActive();
              endTextIfActive();
              controller.enqueue({
                type: "tool-input-available",
                toolCallId: eventPayload?.tool_call_id || eventPayload?.toolCallId || "tool-call",
                toolName: eventPayload?.tool_name || eventPayload?.tool_id || eventPayload?.tool || "unknown_tool",
                input: eventPayload?.input ?? eventPayload?.arguments ?? {},
                dynamic: true,
              });
              break;
            }

            case "tool.end": {
              endReasoningIfActive();
              endTextIfActive();
              const toolCallId = eventPayload?.tool_call_id || eventPayload?.toolCallId || "tool-call";
              const isFailed =
                eventPayload?.status === "failed" ||
                Boolean(eventPayload?.error) ||
                eventPayload?.status === "error";

              if (isFailed) {
                const errorText =
                  (typeof eventPayload?.error === "object"
                    ? eventPayload?.error?.message
                    : eventPayload?.error) ||
                  eventPayload?.summary ||
                  "Tool execution failed";

                controller.enqueue({
                  type: "tool-output-error",
                  toolCallId,
                  errorText,
                  dynamic: true,
                });
              } else {
                const output =
                  eventPayload?.output !== undefined
                    ? eventPayload.output
                    : eventPayload?.summary !== undefined
                    ? { summary: eventPayload.summary }
                    : {};

                controller.enqueue({
                  type: "tool-output-available",
                  toolCallId,
                  output,
                  dynamic: true,
                });
              }
              break;
            }

            case "text.delta": {
              endReasoningIfActive();
              const delta = eventPayload?.delta ?? "";
              if (!textActive) {
                textPartIndex++;
                currentTextId = `text-${turnId}-${textPartIndex}`;
                controller.enqueue({
                  type: "text-start",
                  id: currentTextId,
                });
                textActive = true;
              }
              controller.enqueue({
                type: "text-delta",
                id: currentTextId,
                delta,
              });
              break;
            }

            case "citation": {
              endTextIfActive();
              endReasoningIfActive();
              controller.enqueue({
                type: "data-citation",
                data: {
                  id: eventPayload?.id || eventPayload?.citation_id || "c1",
                  source: eventPayload?.source ?? "",
                  section: eventPayload?.section ?? "",
                  content: eventPayload?.content ?? "",
                  score: eventPayload?.score !== undefined ? eventPayload.score : null,
                },
              });
              break;
            }

            case "suggestions": {
              endTextIfActive();
              controller.enqueue({
                type: "data-suggestions",
                data: {
                  items: eventPayload?.items || [],
                },
              });
              break;
            }

            case "usage": {
              endTextIfActive();
              controller.enqueue({
                type: "data-usage",
                data: eventPayload,
              });
              break;
            }

            case "interaction.request": {
              endTextIfActive();
              controller.enqueue({
                type: "data-interaction",
                data: eventPayload,
              });
              break;
            }

            case "run.error": {
              endTextIfActive();
              endReasoningIfActive();
              terminalEmitted = true;
              controller.enqueue({
                type: "error",
                errorText: eventPayload?.message || eventPayload?.error || "Run error",
              });
              break;
            }

            case "run.completed": {
              endTextIfActive();
              endReasoningIfActive();
              terminalEmitted = true;
              controller.enqueue({
                type: "finish",
                finishReason: "stop",
              });
              break;
            }

            default:
              break;
          }
        };

        if (options.abortSignal) {
          options.abortSignal.addEventListener("abort", () => {
            endReasoningIfActive();
            endTextIfActive();
            reader.cancel().catch(() => {});
            try {
              controller.close();
            } catch {
              // controller may already be closed
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
              const lines = part.split(/\r?\n/);
              for (const line of lines) {
                if (line.startsWith("event:")) {
                  eventType = line.slice(6).trim();
                } else if (line.startsWith("data:")) {
                  const dataSlice = line.slice(5).trim();
                  data = data ? `${data}\n${dataSlice}` : dataSlice;
                }
              }
              if (data) {
                processEvent(eventType, data);
              }
            }
          }

          buffer += decoder.decode();
          if (buffer.trim()) {
            let eventType = "message";
            let data = "";
            const lines = buffer.split(/\r?\n/);
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                const dataSlice = line.slice(5).trim();
                data = data ? `${data}\n${dataSlice}` : dataSlice;
              }
            }
            if (data) {
              processEvent(eventType, data);
            }
          }

          endTextIfActive();
          endReasoningIfActive();
          if (!terminalEmitted) {
            terminalEmitted = true;
            controller.enqueue({
              type: "finish",
              finishReason: "stop",
            });
          }
        } catch (err) {
          endReasoningIfActive();
          endTextIfActive();
          if (!options.abortSignal?.aborted) {
            controller.error(err);
          }
        } finally {
          reader.releaseLock();
          try {
            controller.close();
          } catch {
            // Already closed
          }
        }
      },
    });
  }
}
