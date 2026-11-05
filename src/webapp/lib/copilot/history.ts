/**
 * History mapper: transforms AgentSessionResponse into AI SDK UIMessage[].
 */

import type { UIMessage } from "ai";
import type { AgentSessionResponse, AgentSessionMessage } from "@/types/schemas";

export interface AgentUIMessageMetadata {
  turn_id: string;
  created_at: string;
  session_id?: string;
}

/**
 * Maps GET /api/v1/cases/{id}/agent-session response to AI SDK UIMessage array.
 */
export function mapAgentSessionToUIMessages(
  session?: AgentSessionResponse | null
): UIMessage<AgentUIMessageMetadata>[] {
  if (!session || !Array.isArray(session.messages)) {
    return [];
  }

  return session.messages
    .filter((message: AgentSessionMessage) => message.role === "user" || message.role === "assistant")
    .map((message: AgentSessionMessage) => {
      const role: "user" | "assistant" = message.role === "assistant" ? "assistant" : "user";
    const metadata: AgentUIMessageMetadata = {
      turn_id: message.turn_id,
      created_at: message.created_at,
      ...(session.session_id ? { session_id: session.session_id } : {}),
    };

    const parts =
      (message as { parts?: any[] }).parts &&
      Array.isArray((message as { parts?: any[] }).parts) &&
      (message as { parts?: any[] }).parts!.length > 0
        ? (message as { parts?: any[] }).parts!
        : [
            {
              type: "text" as const,
              text: message.content ?? "",
            },
          ];

    return {
      id: message.id,
      role,
      parts,
      metadata,
    };
  });
}
