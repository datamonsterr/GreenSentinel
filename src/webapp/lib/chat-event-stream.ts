/**
 * Canonical Chat Event Stream parser and reducer (v1.1 with legacy fallback).
 * Provides robust frame assembly, multibyte UTF-8 handling, tool pairing,
 * duplicate/conflict/sequence gap detection, and recoverable interrupted states.
 */

export interface ToolActivity {
  tool_id: string;
  tool_name: string;
  tool_call_id: string;
  status: "pending" | "succeeded" | "failed" | "interrupted";
  label?: string;
  duration_ms?: number;
  summary?: string;
  output?: Record<string, unknown>;
  error?: {
    code: string;
    message: string;
    retryable?: boolean;
  };
}

export type ChatStreamStatus = "idle" | "running" | "completed" | "error" | "interrupted";

export interface ChatStreamError {
  code: string;
  message: string;
  retryable?: boolean;
}

export interface ChatStreamCitation {
  source: string;
  section?: string;
  content?: string;
  citation_id?: string;
  [key: string]: any;
}

export interface ChatStreamState {
  run_id: string | null;
  message_id: string | null;
  case_id: string | null;
  turn_id: string | null;
  session_id: string | null;
  request_id: string | null;
  sequence: number;
  status: ChatStreamStatus;
  text: string;
  thinking: string | null;
  reasoning: string;
  tools: Record<string, ToolActivity>;
  citations: ChatStreamCitation[];
  error: ChatStreamError | null;
}

export interface ChatStreamEvent {
  schema_version?: string;
  event_id: string;
  run_id?: string;
  message_id?: string;
  sequence?: number;
  timestamp?: string;
  type: string;
  payload: Record<string, any>;
  request_id?: string;
  case_id?: string;
  session_id?: string;
  turn_id?: string;
}

export interface ChatStreamCallbacks {
  onDelta?: (delta: string, accumulated: string) => void;
  onCitation?: (citation: ChatStreamCitation) => void;
  onToolStart?: (tool: ToolActivity) => void;
  onToolEnd?: (tool: ToolActivity) => void;
  onThinking?: (label: string) => void;
  onReasoning?: (delta: string, accumulated: string) => void;
  onReasoningStart?: (id: string) => void;
  onReasoningDelta?: (delta: string, accumulated: string) => void;
  onReasoningEnd?: (id: string, durationMs?: number) => void;
  onTerminal?: (state: ChatStreamState) => void;
  onError?: (error: Error | ChatStreamError) => void;
  signal?: AbortSignal;
}

export class ChatEventStreamParser {
  private state: ChatStreamState = {
    run_id: null,
    message_id: null,
    case_id: null,
    turn_id: null,
    session_id: null,
    request_id: null,
    sequence: -1,
    status: "idle",
    text: "",
    thinking: null,
    reasoning: "",
    tools: {},
    citations: [],
    error: null,
  };

  private seenEvents = new Map<string, string>(); // event_id -> raw payload json
  private terminalNotified = false;
  private callbacks: ChatStreamCallbacks;
  private reasoningId = "reasoning-0";
  private reasoningIndex = 0;
  private reasoningText = "";
  private reasoningStartedAt: number | null = null;
  private reasoningActive = false;

  constructor(callbacks: ChatStreamCallbacks = {}) {
    this.callbacks = callbacks;
  }

  public getState(): ChatStreamState {
    return {
      ...this.state,
      tools: { ...this.state.tools },
      citations: [...this.state.citations],
    };
  }

  private closePendingTools(reason: "failed" | "interrupted" = "interrupted") {
    for (const [callId, tool] of Object.entries(this.state.tools)) {
      if (tool.status === "pending") {
        this.state.tools[callId] = {
          ...tool,
          status: reason,
          error: tool.error || {
            code: "INTERRUPTED",
            message: "Thao tác bị gián đoạn",
            retryable: true,
          },
        };
        this.callbacks.onToolEnd?.(this.state.tools[callId]);
      }
    }
  }

  private notifyTerminalOnce() {
    if (this.terminalNotified) return;
    this.terminalNotified = true;
    this.closePendingTools("interrupted");
    this.endReasoning();
    this.callbacks.onTerminal?.(this.getState());
  }

  private startReasoning(id?: string) {
    if (this.reasoningActive) return;
    this.reasoningIndex += 1;
    this.reasoningId = id || `reasoning-${this.reasoningIndex}`;
    this.reasoningText = "";
    this.reasoningStartedAt = Date.now();
    this.reasoningActive = true;
    this.callbacks.onReasoningStart?.(this.reasoningId);
  }

  private appendReasoning(delta: unknown) {
    if (typeof delta !== "string" || !delta) return;
    this.startReasoning();
    this.reasoningText += delta;
    this.state.reasoning += delta;
    this.callbacks.onReasoning?.(delta, this.state.reasoning);
    this.callbacks.onReasoningDelta?.(delta, this.reasoningText);
  }

  private endReasoning(id?: string, durationMs?: number) {
    if (!this.reasoningActive) return;
    const measured = this.reasoningStartedAt == null ? 0 : Date.now() - this.reasoningStartedAt;
    const duration = Number.isFinite(durationMs) && durationMs! >= 0 ? durationMs : Math.max(0, measured);
    this.callbacks.onReasoningEnd?.(id || this.reasoningId, duration);
    this.reasoningActive = false;
    this.reasoningStartedAt = null;
  }

  public handleAbort() {
    if (this.state.status === "completed" || this.state.status === "error") return;
    this.state.status = "interrupted";
    this.state.error = {
      code: "ABORTED",
      message: "Yêu cầu đã bị hủy",
      retryable: true,
    };
    this.notifyTerminalOnce();
  }

  public handleInterruptedEof() {
    if (this.state.status === "completed" || this.state.status === "error" || this.state.status === "interrupted") {
      return;
    }
    this.state.status = "interrupted";
    this.state.error = {
      code: "INTERRUPTED",
      message: "Stream closed before terminal event",
      retryable: true,
    };
    this.notifyTerminalOnce();
  }

  public processSseMessage(eventType: string, dataStr: string): boolean {
    if (this.state.status === "completed" || this.state.status === "error" || this.state.status === "interrupted") {
      return false; // ignore after terminal
    }

    this.state.status = "running";

    let parsed: any;
    try {
      parsed = JSON.parse(dataStr);
    } catch {
      // Malformed data
      this.state.status = "interrupted";
      this.state.error = {
        code: "MALFORMED_EVENT",
        message: "Failed to parse SSE JSON payload",
        retryable: false,
      };
      this.notifyTerminalOnce();
      return false;
    }

    // 1. Check if this is a v1.0 or v1.1 canonical event envelope
    const isEnvelope = Boolean(parsed && typeof parsed === "object" && parsed.type && parsed.payload);

    if (isEnvelope) {
      const event: ChatStreamEvent = parsed;
      const eventId = event.event_id;

      // Duplicate / conflict detection
      if (eventId) {
        const payloadStr = JSON.stringify(event.payload);
        if (this.seenEvents.has(eventId)) {
          const priorPayload = this.seenEvents.get(eventId);
          if (priorPayload !== payloadStr) {
            // Conflicting duplicate
            this.state.status = "interrupted";
            this.state.error = {
              code: "CONFLICT",
              message: `Conflicting duplicate event_id received: ${eventId}`,
              retryable: false,
            };
            this.notifyTerminalOnce();
            return false;
          }
          // Exact replay, ignore
          return true;
        }
        this.seenEvents.set(eventId, payloadStr);
      }

      // Run isolation
      if (event.run_id) {
        if (!this.state.run_id) {
          this.state.run_id = event.run_id;
          this.state.message_id = event.message_id || null;
          this.state.case_id = event.case_id || null;
          this.state.turn_id = event.turn_id || null;
          this.state.session_id = event.session_id || null;
          this.state.request_id = event.request_id || null;
        } else if (this.state.run_id !== event.run_id) {
          // Stale event from another run, discard safely
          return true;
        }
      }

      // Sequence check
      if (typeof event.sequence === "number") {
        if (this.state.sequence === -1) {
          this.state.sequence = event.sequence;
        } else if (event.sequence !== this.state.sequence + 1) {
          // Sequence gap
          this.state.status = "interrupted";
          this.state.error = {
            code: "SEQUENCE_GAP",
            message: `Sequence gap detected: expected ${this.state.sequence + 1}, got ${event.sequence}`,
            retryable: true,
          };
          this.notifyTerminalOnce();
          return false;
        } else {
          this.state.sequence = event.sequence;
        }
      }

      // Dispatch by event type
      switch (event.type) {
        case "thinking":
        case "status.thinking": {
          const label = event.payload.label || "Reviewing request";
          this.state.thinking = label;
          this.callbacks.onThinking?.(label);
          this.appendReasoning(event.payload.thought ?? event.payload.delta ?? event.payload.text ?? event.payload.content);
          if (["end", "completed", "done"].includes(event.payload.status)) this.endReasoning(undefined, event.payload.duration_ms);
          break;
        }
        case "reasoning.start":
        case "reasoning-start":
        case "reasoning_start":
        case "thinking.start":
        case "thinking_start":
        case "thinking-start":
          this.startReasoning(event.payload.id || event.payload.reasoning_id);
          break;
        case "reasoning.delta":
        case "reasoning-delta":
        case "reasoning_delta":
        case "thinking.delta":
        case "thinking_delta":
        case "thinking-delta":
          this.appendReasoning(event.payload.delta ?? event.payload.text ?? event.payload.thought ?? event.payload.content);
          break;
        case "reasoning.end":
        case "reasoning-end":
        case "reasoning_end":
        case "thinking.end":
        case "thinking_end":
        case "thinking-end":
          this.endReasoning(event.payload.id || event.payload.reasoning_id, event.payload.duration_ms);
          break;
        case "tool.start": {
          this.endReasoning();
          const callId = event.payload.tool_call_id;
          const toolActivity: ToolActivity = {
            tool_id: event.payload.tool_id,
            tool_name: event.payload.tool_name || event.payload.tool_id,
            tool_call_id: callId,
            status: "pending",
            label: event.payload.label,
          };
          this.state.tools[callId] = toolActivity;
          this.callbacks.onToolStart?.(toolActivity);
          break;
        }
        case "tool.end": {
          const callId = event.payload.tool_call_id;
          const existing = this.state.tools[callId];
          const updated: ToolActivity = {
            tool_id: event.payload.tool_id || existing?.tool_id || "",
            tool_name: event.payload.tool_name || existing?.tool_name || event.payload.tool_id || "",
            tool_call_id: callId,
            status: event.payload.status === "succeeded" ? "succeeded" : "failed",
            label: existing?.label,
            duration_ms: event.payload.duration_ms,
            summary: event.payload.summary,
            output: event.payload.output,
            error: event.payload.error,
          };
          this.state.tools[callId] = updated;
          this.callbacks.onToolEnd?.(updated);
          break;
        }
        case "text.delta": {
          this.endReasoning();
          const delta = event.payload.delta ?? "";
          this.state.text += delta;
          this.callbacks.onDelta?.(delta, this.state.text);
          break;
        }
        case "citation": {
          this.state.citations.push(event.payload as ChatStreamCitation);
          this.callbacks.onCitation?.(event.payload as ChatStreamCitation);
          break;
        }
        case "run.completed": {
          this.state.status = "completed";
          this.notifyTerminalOnce();
          break;
        }
        case "run.error": {
          this.state.status = "error";
          this.state.error = {
            code: event.payload.code || "INTERNAL_ERROR",
            message: event.payload.message || "Run encountered error",
            retryable: Boolean(event.payload.retryable),
          };
          this.callbacks.onError?.(this.state.error);
          this.notifyTerminalOnce();
          break;
        }
        default:
          break;
      }
    } else {
      // Legacy unnegotiated SSE event handling
      switch (eventType) {
        case "text_delta":
        case "delta":
        case "token": {
          this.endReasoning();
          const delta = parsed.delta ?? parsed.token ?? "";
          this.state.text += delta;
          this.callbacks.onDelta?.(delta, this.state.text);
          break;
        }
        case "citation": {
          this.state.citations.push(parsed as ChatStreamCitation);
          this.callbacks.onCitation?.(parsed as ChatStreamCitation);
          break;
        }
        case "status.thinking":
        case "thinking": {
          if (parsed.label) {
            this.state.thinking = parsed.label;
            this.callbacks.onThinking?.(parsed.label);
          }
          this.appendReasoning(parsed.delta ?? parsed.text ?? parsed.thought ?? parsed.content);
          if (["end", "completed", "done"].includes(parsed.status)) this.endReasoning(undefined, parsed.duration_ms);
          break;
        }
        case "reasoning_start":
        case "reasoning-start":
        case "reasoning.start":
        case "thinking.start":
        case "thinking_start":
        case "thinking-start":
          this.startReasoning(parsed.id || parsed.reasoning_id);
          break;
        case "reasoning_delta":
        case "reasoning-delta":
        case "reasoning.delta":
        case "thinking.delta":
        case "thinking_delta":
        case "thinking-delta":
        case "reasoning":
          this.appendReasoning(parsed.delta ?? parsed.text ?? parsed.thought ?? parsed.content);
          break;
        case "reasoning_end":
        case "reasoning-end":
        case "reasoning.end":
        case "thinking.end":
        case "thinking_end":
        case "thinking-end":
          this.endReasoning(parsed.id || parsed.reasoning_id, parsed.duration_ms);
          break;
        case "tool_call": {
          this.endReasoning();
          const toolName = parsed.tool || "unknown_tool";
          const callId = `legacy-${toolName}`;
          const toolActivity: ToolActivity = {
            tool_id: toolName,
            tool_name: toolName,
            tool_call_id: callId,
            status: parsed.status === "blocked" || parsed.status === "not_found" ? "failed" : "pending",
          };
          this.state.tools[callId] = toolActivity;
          this.callbacks.onToolStart?.(toolActivity);
          break;
        }
        case "tool_done": {
          const toolName = parsed.tool || "unknown_tool";
          const callId = `legacy-${toolName}`;
          const existing = this.state.tools[callId];
          const updated: ToolActivity = {
            tool_id: toolName,
            tool_name: toolName,
            tool_call_id: callId,
            status: parsed.status === "success" || parsed.status === "completed" ? "succeeded" : "failed",
            label: existing?.label,
          };
          this.state.tools[callId] = updated;
          this.callbacks.onToolEnd?.(updated);
          break;
        }
        case "error": {
          this.state.status = "error";
          this.state.error = {
            code: "LEGACY_ERROR",
            message: parsed.message || "Agent request failed",
            retryable: false,
          };
          this.callbacks.onError?.(this.state.error);
          this.notifyTerminalOnce();
          break;
        }
        case "done":
        case "completion": {
          this.state.status = "completed";
          this.notifyTerminalOnce();
          break;
        }
        default:
          break;
      }
    }

    return true;
  }
}

/**
 * Consumes a raw byte ReadableStream, assembling SSE frames across chunk boundaries
 * with multibyte UTF-8 awareness and reducer logic.
 */
export async function consumeChatEventStream(
  stream: ReadableStream<Uint8Array>,
  callbacks: ChatStreamCallbacks = {}
): Promise<ChatStreamState> {
  const parser = new ChatEventStreamParser(callbacks);
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  if (callbacks.signal) {
    if (callbacks.signal.aborted) {
      parser.handleAbort();
      return parser.getState();
    }
    callbacks.signal.addEventListener("abort", () => {
      parser.handleAbort();
      reader.cancel().catch(() => {});
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
          const shouldContinue = parser.processSseMessage(eventType, data);
          if (!shouldContinue) {
            reader.cancel().catch(() => {});
            return parser.getState();
          }
        }
      }
    }

    // Flush any remaining characters in decoder
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
        parser.processSseMessage(eventType, data);
      }
    }

    // Check if EOF occurred without explicit terminal
    parser.handleInterruptedEof();
  } catch (err: any) {
    if (err.name === "AbortError" || callbacks.signal?.aborted) {
      parser.handleAbort();
    } else {
      callbacks.onError?.(err);
      parser.handleInterruptedEof();
    }
  } finally {
    reader.releaseLock();
  }

  return parser.getState();
}
