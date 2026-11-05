/**
 * Maps GET /api/v1/driver/cases/{caseId}/session response (driver-scoped
 * projection: driver / driver_agent / analyst roles) to AI SDK UIMessage[].
 */

import type { UIMessage } from "ai";

export interface DriverSessionMessage {
  id: string;
  role: "driver" | "driver_agent" | "analyst" | string;
  content: string;
  turn_id?: string;
  created_at?: string;
}

export interface DriverSessionResponse {
  session_id?: string;
  messages?: DriverSessionMessage[];
}

export function mapDriverSessionToUIMessages(
  session?: DriverSessionResponse | null
): UIMessage[] {
  if (!session || !Array.isArray(session.messages)) {
    return [];
  }

  return session.messages.map((message, idx) => {
    const role: "user" | "assistant" = message.role === "driver" ? "user" : "assistant";
    return {
      id: message.id || `hist-${idx}`,
      role,
      parts: [{ type: "text" as const, text: message.content ?? "" }],
      // Distinct human badge for analyst messages (Issue #538 blocker #7).
      metadata: { sourceRole: message.role },
    };
  });
}
