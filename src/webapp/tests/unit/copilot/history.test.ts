import { describe, it, expect } from "vitest";
import { mapAgentSessionToUIMessages } from "@/lib/copilot/history";
import { AgentSessionResponse } from "@/types/schemas";

describe("history (agent session to UIMessage mapper)", () => {
  it("maps empty or missing session messages to empty array", () => {
    expect(mapAgentSessionToUIMessages({ session_id: null, messages: [] })).toEqual([]);
    expect(mapAgentSessionToUIMessages({ session_id: "s-1", messages: [] })).toEqual([]);
    expect(mapAgentSessionToUIMessages(null as any)).toEqual([]);
    expect(mapAgentSessionToUIMessages({} as any)).toEqual([]);
  });

  it("maps user and assistant messages into AI SDK UIMessage format", () => {
    const session: AgentSessionResponse = {
      session_id: "session-uuid-1",
      messages: [
        {
          id: "msg-user-1",
          turn_id: "turn-1",
          role: "user",
          content: "Hãy kiểm tra dữ liệu GPS của chuyến đi",
          created_at: "2026-10-16T10:00:00Z",
        },
        {
          id: "msg-asst-1",
          turn_id: "turn-1",
          role: "assistant",
          content: "Tôi đã kiểm tra telemetry và không phát hiện lệch lộ trình.",
          created_at: "2026-10-16T10:00:05Z",
        },
      ],
    };

    const uiMessages = mapAgentSessionToUIMessages(session);

    expect(uiMessages).toHaveLength(2);

    expect(uiMessages[0]).toEqual({
      id: "msg-user-1",
      role: "user",
      parts: [
        {
          type: "text",
          text: "Hãy kiểm tra dữ liệu GPS của chuyến đi",
        },
      ],
      metadata: {
        turn_id: "turn-1",
        created_at: "2026-10-16T10:00:00Z",
        session_id: "session-uuid-1",
      },
    });

    expect(uiMessages[1]).toEqual({
      id: "msg-asst-1",
      role: "assistant",
      parts: [
        {
          type: "text",
          text: "Tôi đã kiểm tra telemetry và không phát hiện lệch lộ trình.",
        },
      ],
      metadata: {
        turn_id: "turn-1",
        created_at: "2026-10-16T10:00:05Z",
        session_id: "session-uuid-1",
      },
    });
  });

  it("handles null session_id without error", () => {
    const session: AgentSessionResponse = {
      session_id: null,
      messages: [
        {
          id: "msg-1",
          turn_id: "turn-1",
          role: "user",
          content: "Hello",
          created_at: "2026-10-16T10:00:00Z",
        },
      ],
    };

    const result = mapAgentSessionToUIMessages(session);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("msg-1");
    expect(result[0].role).toBe("user");
    expect(result[0].metadata).toEqual({
      turn_id: "turn-1",
      created_at: "2026-10-16T10:00:00Z",
    });
  });

  it("ignores non-copilot messages (driver, driver_agent) to prevent conversation leak", () => {
    const session: any = {
      session_id: "session-uuid-1",
      messages: [
        {
          id: "msg-driver-1",
          turn_id: "turn-drv-1",
          role: "driver",
          content: "Tôi không đồng ý với cảnh báo vi phạm này",
          created_at: "2026-10-16T09:00:00Z",
        },
        {
          id: "msg-gsupport-1",
          turn_id: "turn-drv-1",
          role: "driver_agent",
          content: "GreenSM Support đã ghi nhận giải trình của bạn.",
          created_at: "2026-10-16T09:00:05Z",
        },
        {
          id: "msg-user-1",
          turn_id: "turn-1",
          role: "user",
          content: "Kiểm tra bằng chứng",
          created_at: "2026-10-16T10:00:00Z",
        },
      ],
    };

    const uiMessages = mapAgentSessionToUIMessages(session);
    expect(uiMessages).toHaveLength(1);
    expect(uiMessages[0].id).toBe("msg-user-1");
    expect(uiMessages[0].role).toBe("user");
  });
});
