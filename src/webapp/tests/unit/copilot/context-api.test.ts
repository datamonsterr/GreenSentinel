import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getAgentContext,
  clearAgentContext,
  AgentContextResponse,
  ClearAgentContextResponse,
} from "@/lib/copilot/context-api";
import { setApiTokenProvider } from "@/lib/api-client";

describe("context-api (agent context management)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    setApiTokenProvider(null);
  });

  describe("getAgentContext", () => {
    it("calls GET /api/v1/cases/{id}/agent-context with auth and returns context data", async () => {
      const mockContext: AgentContextResponse = {
        prompt_tokens: 1200,
        completion_tokens: 350,
        total_tokens: 1550,
        context_window: 128000,
        breakdown: {
          system: 200,
          dossier: 500,
          history: 300,
          tool_results: 150,
          query: 50,
        },
        turn_count: 3,
      };

      setApiTokenProvider(async () => "mock-jwt-token");

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockContext,
      });
      global.fetch = fetchMock;

      const result = await getAgentContext("case-123/special");

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toContain("/api/v1/cases/case-123%2Fspecial/agent-context");
      expect(init?.method).toBe("GET");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer mock-jwt-token");
      expect(result).toEqual(mockContext);
    });

    it("throws on HTTP error with response detail", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        json: async () => ({ detail: "Analyst does not have access to case" }),
      });

      await expect(getAgentContext("case-forbidden")).rejects.toThrow(
        /Analyst does not have access to case/
      );
    });
  });

  describe("clearAgentContext", () => {
    it("calls DELETE /api/v1/cases/{id}/agent-context and returns deleted counts", async () => {
      const mockResponse: ClearAgentContextResponse = {
        deleted_turns: 4,
        deleted_messages: 8,
      };

      setApiTokenProvider(async () => "mock-jwt-token");

      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      });
      global.fetch = fetchMock;

      const result = await clearAgentContext("case-456");

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toContain("/api/v1/cases/case-456/agent-context");
      expect(init?.method).toBe("DELETE");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer mock-jwt-token");
      expect(result).toEqual(mockResponse);
    });

    it("retries on 401 with refreshed token", async () => {
      let tokenCallCount = 0;
      setApiTokenProvider(async () => {
        tokenCallCount++;
        return `token-${tokenCallCount}`;
      });

      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          statusText: "Unauthorized",
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ deleted_turns: 1, deleted_messages: 2 }),
        });
      global.fetch = fetchMock;

      const result = await clearAgentContext("case-expired-session");

      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(result).toEqual({ deleted_turns: 1, deleted_messages: 2 });
    });
  });
});
