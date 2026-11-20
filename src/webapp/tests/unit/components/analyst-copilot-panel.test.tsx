import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalystCopilotPanel } from "@/components/copilot/analyst-copilot-panel";
import * as apiClient from "@/lib/api-client";
import * as contextApi from "@/lib/copilot/context-api";
import type { AgentSessionResponse, DriverScorecardResponse } from "@/types/schemas";

vi.mock("@/lib/api-client", () => ({
  fetchAgentSession: vi.fn(),
  fetchDriverScorecard: vi.fn(),
  getApiBaseUrl: vi.fn(() => ""),
  authorizedHeaders: vi.fn(async () => ({ "Content-Type": "application/json" })),
}));

vi.mock("@/lib/copilot/context-api", () => ({
  getAgentContext: vi.fn(),
  clearAgentContext: vi.fn(),
}));

vi.mock("@/lib/copilot/history", () => ({
  mapAgentSessionToUIMessages: vi.fn((session) => {
    if (!session || !Array.isArray(session.messages)) return [];
    return session.messages.map((m: any) => ({
      id: m.id,
      role: m.role,
      parts: m.parts || [{ type: "text", text: m.content || "" }],
      metadata: { turn_id: m.turn_id, created_at: m.created_at },
    }));
  }),
}));

const mockContextUsage: contextApi.AgentContextResponse = {
  prompt_tokens: 1200,
  completion_tokens: 300,
  total_tokens: 1500,
  context_window: 10000,
  breakdown: {
    system: 400,
    dossier: 500,
    history: 200,
    tool_results: 300,
    query: 100,
  },
  turn_count: 2,
};

const mockSession: AgentSessionResponse = {
  session_id: "session-123",
  messages: [
    {
      id: "msg-1",
      turn_id: "turn-1",
      role: "user",
      content: "Xin tóm tắt vụ việc",
      created_at: "2026-10-16T10:00:00Z",
    },
    {
      id: "msg-2",
      turn_id: "turn-1",
      role: "assistant",
      content: "Hồ sơ vụ việc đã được xem xét kỹ lưỡng.",
      created_at: "2026-10-16T10:00:05Z",
    },
  ],
};

const mockScorecard: DriverScorecardResponse = {
  driver_id: "drv-999",
  violation_ratio_90d: 4.2,
  benchmark_violation_ratio: 5.0,
  fined_ratio: 25.0,
  repeat_offense_risk_score: 65,
  tenure_months: 18,
  past_incidents: [
    {
      trip_id: "trip-old-1",
      occurred_at: "2026-09-01T08:00:00Z",
      violation_type: "DIC",
      investigation_finding: "Cố tình dừng đỗ kéo dài",
      action_taken: "Phạt 200.000đ",
      status: "penalized",
    },
  ],
};

let writeTextMock = vi.fn();

describe("AnalystCopilotPanel Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    writeTextMock = vi.fn().mockResolvedValue(undefined);
    vi.mocked(apiClient.fetchAgentSession).mockResolvedValue(mockSession);
    vi.mocked(apiClient.fetchDriverScorecard).mockResolvedValue(mockScorecard);
    vi.mocked(contextApi.getAgentContext).mockResolvedValue(mockContextUsage);
    vi.mocked(contextApi.clearAgentContext).mockResolvedValue({
      deleted_turns: 2,
      deleted_messages: 2,
    });

    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: writeTextMock,
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    // cleanup
  });

  describe("1. Header & Segmented Switcher", () => {
    it("renders compact 2-option switcher 'Analyst Copilot' | 'Driver' and context ring button", async () => {
      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
          placeholder="Ask Agents about this case…"
        />
      );

      // Verify no "Agents" title or case code badge
      expect(screen.queryByText(/^Agents$/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/#case-100/i)).not.toBeInTheDocument();

      // Check tablist and tabs
      const tablist = screen.getByRole("tablist", { name: /Agent panels/i });
      expect(tablist).toBeInTheDocument();

      const copilotTab = screen.getByRole("tab", { name: /Analyst Copilot/i });
      const driverTab = screen.getByRole("tab", { name: /Driver/i });

      expect(copilotTab).toHaveAttribute("id", "tab-ai-copilot");
      expect(driverTab).toHaveAttribute("id", "tab-driver-relay");
      expect(copilotTab).toHaveAttribute("aria-selected", "true");
      expect(driverTab).toHaveAttribute("aria-selected", "false");

      // Check context ring button renders formatted % of context window used (1500 / 10000 = 15%)
      await waitFor(() => {
        expect(screen.getByText(/15(\.0)?%/)).toBeInTheDocument();
      });
    });

    it("supports keyboard navigation with ArrowRight, ArrowLeft, Home, End", async () => {
      const user = userEvent.setup();
      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      const copilotTab = screen.getByRole("tab", { name: /Analyst Copilot/i });
      const driverTab = screen.getByRole("tab", { name: /Driver/i });

      copilotTab.focus();
      expect(copilotTab).toHaveFocus();

      await user.keyboard("{ArrowRight}");
      expect(driverTab).toHaveFocus();
      expect(driverTab).toHaveAttribute("aria-selected", "true");

      await user.keyboard("{ArrowLeft}");
      expect(copilotTab).toHaveFocus();
      expect(copilotTab).toHaveAttribute("aria-selected", "true");

      await user.keyboard("{End}");
      expect(driverTab).toHaveFocus();

      await user.keyboard("{Home}");
      expect(copilotTab).toHaveFocus();
    });
  });

  describe("2. Context Popover & Clear Flow", () => {
    it("renders context breakdown and handles clear context flow with confirm step", async () => {
      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      await waitFor(() => {
        expect(screen.getByText(/15(\.0)?%/)).toBeInTheDocument();
      });

      // Click context trigger to open Context Popover
      const trigger = screen.getByText(/15(\.0)?%/).closest("button")!;
      fireEvent.click(trigger);

      // Context breakdown rows
      expect(await screen.findByText(/^System$/i)).toBeInTheDocument();
      expect(screen.getByText(/^Hồ sơ vụ việc$/)).toBeInTheDocument();
      expect(screen.getByText(/^Lịch sử hội thoại$/)).toBeInTheDocument();
      expect(screen.getByText(/^Kết quả công cụ$/)).toBeInTheDocument();
      expect(screen.getByText(/^Câu hỏi$/)).toBeInTheDocument();

      // Find "Xóa ngữ cảnh" button
      const clearBtn = screen.getByRole("button", { name: /Xóa ngữ cảnh/i });
      expect(clearBtn).toBeEnabled();

      // Click requires confirm step
      fireEvent.click(clearBtn);

      const confirmBtn = await screen.findByRole("button", { name: /Xác nhận/i });
      expect(confirmBtn).toBeInTheDocument();

      // Refetch context response after clear
      vi.mocked(contextApi.getAgentContext).mockResolvedValueOnce({
        ...mockContextUsage,
        total_tokens: 0,
        turn_count: 0,
        breakdown: { system: 0, dossier: 0, history: 0, tool_results: 0, query: 0 },
      });

      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(contextApi.clearAgentContext).toHaveBeenCalledWith("case-100");
        expect(contextApi.getAgentContext).toHaveBeenCalledTimes(2);
      });

      // Verify messages cleared
      await waitFor(() => {
        expect(screen.queryByText("Hồ sơ vụ việc đã được xem xét kỹ lưỡng.")).not.toBeInTheDocument();
      });
    });

    it("disables clear context button when not locked by me", async () => {
      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={false}
        />
      );

      await waitFor(() => {
        expect(screen.getByText(/15(\.0)?%/)).toBeInTheDocument();
      });

      const trigger = screen.getByText(/15(\.0)?%/).closest("button")!;
      fireEvent.click(trigger);

      const clearBtn = await screen.findByRole("button", { name: /Xóa ngữ cảnh/i });
      expect(clearBtn).toBeDisabled();
    });
  });

  describe("3. Link Renderers (case://, driver://, trip://, policy://)", () => {
    it("handles case:// link: copies case id on click and triggers onSelectCase on ctrl/cmd-click", async () => {
      const onSelectCase = vi.fn();

      // Mock session containing markdown links
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValue({
        session_id: "s-1",
        messages: [
          {
            id: "m-1",
            turn_id: "t-1",
            role: "assistant",
            content: "Tham khảo [Vụ việc liên quan](case://case-uuid-8888) để biết chi tiết.",
            created_at: "2026-10-16T10:00:00Z",
          },
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
          onSelectCase={onSelectCase}
        />
      );

      const caseLink = await screen.findByRole("button", { name: /Vụ việc liên quan/i });
      expect(caseLink).toBeInTheDocument();

      // ID should never be shown in text, but present in title tooltip
      expect(caseLink).not.toHaveTextContent("case-uuid-8888");
      expect(caseLink).toHaveAttribute("title", "case-uuid-8888");

      // Click copies to clipboard
      fireEvent.click(caseLink);
      expect(writeTextMock).toHaveBeenCalledWith("case-uuid-8888");

      // Ctrl-click calls onSelectCase
      fireEvent.click(caseLink, { ctrlKey: true });
      expect(onSelectCase).toHaveBeenCalledWith("case-uuid-8888");
    });

    it("handles driver:// link: opens Dialog with driver scorecard data", async () => {
      const user = userEvent.setup();
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValue({
        session_id: "s-1",
        messages: [
          {
            id: "m-1",
            turn_id: "t-1",
            role: "assistant",
            content: "Thông tin [Tài xế Nguyễn Văn An](driver://drv-999) cần xem xét.",
            created_at: "2026-10-16T10:00:00Z",
          },
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      const driverLink = await screen.findByRole("button", { name: /Tài xế Nguyễn Văn An/i });
      await user.click(driverLink);

      expect(apiClient.fetchDriverScorecard).toHaveBeenCalledWith("drv-999");
      expect(await screen.findByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText(/Hồ sơ tài xế/i)).toBeInTheDocument();
      expect(screen.getByText("4.2%")).toBeInTheDocument();
      expect(screen.getByText(/65\/100/)).toBeInTheDocument();
    });

    it("handles trip:// link: renders chip with map icon and calls onOpenTrip", async () => {
      const onOpenTrip = vi.fn();
      const user = userEvent.setup();

      vi.mocked(apiClient.fetchAgentSession).mockResolvedValue({
        session_id: "s-1",
        messages: [
          {
            id: "m-1",
            turn_id: "t-1",
            role: "assistant",
            content: "Xem [Điểm đón → Điểm đến](trip://trip-777?pickup=VinUni&dest=Keangnam).",
            created_at: "2026-10-16T10:00:00Z",
          },
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
          onOpenTrip={onOpenTrip}
        />
      );

      const tripChip = await screen.findByRole("button", { name: /VinUni → Keangnam/i });
      expect(tripChip).toBeInTheDocument();

      await user.click(tripChip);
      expect(onOpenTrip).toHaveBeenCalledWith("trip-777");
    });
  });

  describe("4. Input & Attachment Handling", () => {
    it("disables input and send button when not locked by me", async () => {
      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={false}
          placeholder="Claim case to chat with AI Copilot…"
        />
      );

      const input = await screen.findByPlaceholderText("Claim case to chat with AI Copilot…");
      expect(input).toBeDisabled();
    });

    it("resets chat when caseId changes", async () => {
      const { rerender } = render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      await screen.findByText("Hồ sơ vụ việc đã được xem xét kỹ lưỡng.");

      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "s-2",
        messages: [
          {
            id: "m-new",
            turn_id: "t-new",
            role: "assistant",
            content: "Hồ sơ vụ việc mới hoàn toàn khác.",
            created_at: "2026-10-16T11:00:00Z",
          },
        ],
      });

      rerender(
        <AnalystCopilotPanel
          caseId="case-200"
          isLockedByMe={true}
        />
      );

      await waitFor(() => {
        expect(screen.getByText("Hồ sơ vụ việc mới hoàn toàn khác.")).toBeInTheDocument();
        expect(screen.queryByText("Hồ sơ vụ việc đã được xem xét kỹ lưỡng.")).not.toBeInTheDocument();
      });
    });
  });

  describe("5. Tools, Citations, Suggestions & Rich Messages", () => {
    it("renders grouped tools collapsible row and expands on click", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "s-tools",
        messages: [
          {
            id: "m-tool-msg",
            turn_id: "t-1",
            role: "assistant",
            content: "Đã xử lý xong các bước kiểm tra.",
            created_at: "2026-10-16T10:00:00Z",
            parts: [
              {
                type: "tool-invocation",
                toolName: "fetch_corridor_historical_traffic",
                toolCallId: "tc-1",
                state: "result",
                output: {
                  source_type: "first_party_peer_telemetry",
                  peer_count: 3,
                  observed_speed_kmh: 30,
                  free_flow_speed_kmh: 60,
                  congestion_ratio: 0.5,
                  congested: true,
                  window_start: "2026-10-11T10:00:00Z",
                  window_end: "2026-10-11T10:30:00Z",
                  provider_payload: "must-not-render",
                },
              },
              {
                type: "tool-invocation",
                toolName: "query_traffic_incident_feed",
                toolCallId: "tc-2",
                state: "result",
                output: {
                  incident_count: 0,
                  congested: false,
                  observed_at: "2026-10-11T10:15:00Z",
                  historical_absence_proven: false,
                  retention: "memory_only",
                  api_key: "must-not-render",
                },
              },
              {
                type: "tool-invocation",
                toolName: "query_traffic_incident_feed",
                toolCallId: "tc-3",
                state: "result",
                output: {
                  status: "unavailable",
                  reason: "provider_not_configured",
                  historical_absence_proven: false,
                  retention: "memory_only",
                },
              },
              {
                type: "text",
                text: "Đã xử lý xong các bước kiểm tra.",
              },
            ],
          } as any,
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      // Verify collapsed summary
      const trigger = await screen.findByRole("button", { name: /Đã dùng 3 công cụ/i });
      expect(trigger).toBeInTheDocument();
      expect(screen.getByLabelText("Tool fetch_corridor_historical_traffic, done")).toBeVisible();
      expect(screen.getAllByLabelText("Tool query_traffic_incident_feed, done")).toHaveLength(2);

      // Click to expand
      fireEvent.click(trigger);

      // Verify Vietnamese done labels from tool-labels
      expect(await screen.findByText("Đã tải dữ liệu lịch sử giao thông tuyến đường")).toBeInTheDocument();
      expect(screen.getAllByText("Đã kiểm tra thông tin sự cố giao thông")).toHaveLength(2);
      expect(screen.getByText("first_party_peer_telemetry")).toBeInTheDocument();
      expect(screen.getByText(/3 chuyến đối chứng/)).toBeInTheDocument();
      expect(screen.getByText(/50%/)).toBeInTheDocument();
      expect(screen.getAllByText("memory_only")).toHaveLength(2);
      expect(screen.getByText("Không thể xác minh sự cố")).toBeInTheDocument();
      expect(screen.getByText("provider_not_configured")).toBeInTheDocument();
      expect(screen.getAllByText(/Không chứng minh được vắng sự cố lịch sử/)).toHaveLength(2);
      expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
    });

    it("renders policy:// superscript citation and collapsed sources list", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "s-cit",
        messages: [
          {
            id: "m-cit",
            turn_id: "t-1",
            role: "assistant",
            content: "Theo quy định hiện hành [1](policy://c1) của hệ thống.",
            created_at: "2026-10-16T10:00:00Z",
            parts: [
              {
                type: "text",
                text: "Theo quy định hiện hành [1](policy://c1) của hệ thống.",
              },
              {
                type: "data-citation",
                data: {
                  id: "c1",
                  source: "Quy chuẩn tài xế 2026",
                  section: "Điều 12",
                  content: "Nội dung quy định xử phạt vi phạm hành trình.",
                  score: 0.95,
                },
              },
            ],
          } as any,
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      // Verify superscript citation rendered
      expect(await screen.findByText("[1]")).toBeInTheDocument();

      // Verify Sources list trigger
      const sourcesBtn = screen.getByRole("button", { name: /sources|nguồn trích dẫn/i });
      expect(sourcesBtn).toBeInTheDocument();

      // Expand sources
      fireEvent.click(sourcesBtn);
      expect(await screen.findByText(/Quy chuẩn tài xế 2026/i)).toBeInTheDocument();
      expect(screen.getByText(/Điều 12/i)).toBeInTheDocument();
      expect(screen.getByText(/Nội dung quy định xử phạt vi phạm hành trình/i)).toBeInTheDocument();
    });

    it("renders suggestions from latest assistant message and clicking sends prompt", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "s-sugg",
        messages: [
          {
            id: "m-sugg",
            turn_id: "t-1",
            role: "assistant",
            content: "Bạn muốn làm gì tiếp theo?",
            created_at: "2026-10-16T10:00:00Z",
            parts: [
              {
                type: "text",
                text: "Bạn muốn làm gì tiếp theo?",
              },
              {
                type: "data-suggestions",
                data: {
                  items: [
                    { label: "Tóm tắt hồ sơ", prompt: "Hãy tóm tắt hồ sơ vụ việc này" },
                    { label: "Kiểm tra tài xế", prompt: "Xem lịch sử vi phạm tài xế" },
                  ],
                },
              },
            ],
          } as any,
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      const sugg1 = await screen.findByRole("button", { name: /Tóm tắt hồ sơ/i });
      const sugg2 = screen.getByRole("button", { name: /Kiểm tra tài xế/i });
      expect(sugg1).toBeInTheDocument();
      expect(sugg2).toBeInTheDocument();

      fireEvent.click(sugg1);
    });

    it("renders analyst user messages on cyan-soft with ink text", async () => {
      render(<AnalystCopilotPanel caseId="case-100" isLockedByMe={true} />);

      const message = await screen.findByText("Xin tóm tắt vụ việc");
      expect(message.parentElement).toHaveClass("!text-gs-ink-2");
      expect(message.parentElement).not.toHaveClass("!text-white");
    });

    it("renders user bubble with attachment thumbnail when message has file part", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "s-attach",
        messages: [
          {
            id: "m-user-file",
            turn_id: "t-1",
            role: "user",
            content: "Đính kèm ảnh hiện trường",
            created_at: "2026-10-16T10:00:00Z",
            parts: [
              {
                type: "file",
                url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                filename: "evidence.png",
              },
              {
                type: "text",
                text: "Đính kèm ảnh hiện trường",
              },
            ],
          } as any,
        ],
      });

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      const img = await screen.findByRole("img", { name: /evidence\.png/i });
      expect(img).toBeInTheDocument();
      expect(img).toHaveAttribute("src", expect.stringContaining("data:image/png;base64"));
      expect(screen.getByText("evidence.png")).toBeInTheDocument();
      expect(screen.getByText("Đính kèm ảnh hiện trường")).toBeInTheDocument();
    });

    it("tolerates missing or malformed breakdown in getAgentContext without crashing", async () => {
      vi.mocked(contextApi.getAgentContext).mockResolvedValueOnce({
        prompt_tokens: 100,
        completion_tokens: 50,
        total_tokens: 150,
        context_window: 10000,
      } as any);

      render(
        <AnalystCopilotPanel
          caseId="case-100"
          isLockedByMe={true}
        />
      );

      const trigger = await screen.findByRole("button", { name: /Ngữ cảnh AI Copilot/i });
      expect(trigger).toBeInTheDocument();
      fireEvent.click(trigger);
      expect(screen.getByText("System")).toBeInTheDocument();
      expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(5);
    });

    it("renders completed reasoning as collapsed Thinking with duration and supports reopening", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "thinking-session",
        messages: [{ id: "thinking-message", turn_id: "t-1", role: "assistant", content: "Answer", parts: [
          { type: "reasoning", text: "Check route evidence", state: "done", durationMs: 42 },
          { type: "text", text: "Answer" },
        ] }],
      } as any);
      render(<AnalystCopilotPanel caseId="case-100" isLockedByMe />);
      const trigger = await screen.findByRole("button", { name: /Thinking/i });
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByText("42 ms")).toBeInTheDocument();
      expect(screen.queryByText("Check route evidence")).not.toBeInTheDocument();
      fireEvent.click(trigger);
      expect(screen.getByText("Check route evidence")).toBeVisible();
    });

    it("does not render an empty Thinking block", async () => {
      vi.mocked(apiClient.fetchAgentSession).mockResolvedValueOnce({
        session_id: "empty-thinking", messages: [{ id: "empty", turn_id: "t-1", role: "assistant", parts: [{ type: "reasoning", text: "" }, { type: "text", text: "Answer" }] }],
      } as any);
      render(<AnalystCopilotPanel caseId="case-100" isLockedByMe />);
      await screen.findByText("Answer");
      expect(screen.queryByRole("button", { name: /Thinking/i })).not.toBeInTheDocument();
    });
  });
});
