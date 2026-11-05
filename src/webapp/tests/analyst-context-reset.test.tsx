import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import * as api from "@/lib/api-client";
import * as contextApi from "@/lib/copilot/context-api";

vi.mock("@/lib/api-client", () => ({
  fetchCases: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchForensicBrief: vi.fn(),
  fetchCasePolicy: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  fetchDriverScorecard: vi.fn(),
  claimCase: vi.fn(),
  releaseCase: vi.fn(),
  adjudicateCase: vi.fn(),
  recordCaseAction: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
  getDisputeDossier: vi.fn(),
  delegateAnalystInquiry: vi.fn(),
  getCaseWorkflowTrace: vi.fn(),
  applyPrecedentProcedure: vi.fn(),
  getApiBaseUrl: vi.fn(() => ""),
  authorizedHeaders: vi.fn(async () => ({ "Content-Type": "application/json" })),
}));

vi.mock("@/lib/copilot/context-api", () => ({
  getAgentContext: vi.fn(),
  clearAgentContext: vi.fn(),
}));

const mockItem = {
  id: "case-test-153",
  driver_name: "Nguyen Van A",
  vehicle_plate: "29E-12345",
  priority: "P1",
  priority_score: 1,
  status: "ready",
  version: 1,
};

const mockDetail = {
  case: mockItem,
  trip: {},
  conversation: [
    { role: "driver" as const, text: "Driver trip dispute context", occurred_at: "2026-09-25T01:00:00Z" },
  ],
  active_lease: {
    analyst_id: "analyst-1",
    expires_at: "2099-01-01T00:00:00Z",
  },
};

const mockUsage: contextApi.AgentContextResponse = {
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

describe("Issue #443 & #153: Context Ring and Clear Agent Context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [mockItem], total: 1, limit: 50, offset: 0 });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(mockDetail);
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: "analyst-1", name: "Analyst One", role: "analyst" });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({
      session_id: "session-153",
      messages: [
        {
          id: "m-1",
          turn_id: "t-1",
          role: "assistant",
          content: "Tin nhắn ngữ cảnh ban đầu.",
          created_at: "2026-10-16T10:00:00Z",
        },
      ],
    });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(null as any);
    vi.mocked(contextApi.getAgentContext).mockResolvedValue(mockUsage);
    vi.mocked(contextApi.clearAgentContext).mockResolvedValue({
      deleted_turns: 2,
      deleted_messages: 2,
    });
  });

  it("prioritizes case detail before starting secondary panel requests", async () => {
    let resolveDetail!: (detail: typeof mockDetail) => void;
    vi.mocked(api.fetchCaseDetail).mockReturnValue(
      new Promise((resolve) => {
        resolveDetail = resolve;
      })
    );
    render(<CockpitWorkspaceView />);
    await waitFor(() => expect(api.fetchCaseDetail).toHaveBeenCalledWith(mockItem.id));
    expect(api.getDisputeDossier).not.toHaveBeenCalled();
    expect(api.getCaseWorkflowTrace).not.toHaveBeenCalled();

    await act(async () => resolveDetail(mockDetail));
    await waitFor(() => {
      expect(api.getDisputeDossier).toHaveBeenCalledWith(mockItem.id);
      expect(api.getCaseWorkflowTrace).toHaveBeenCalledWith(mockItem.id);
    });
  });

  it("removes legacy context-reset checkbox and Single turn text completely", async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Customer' }));
    await screen.findByText('Driver trip dispute context');

    expect(screen.queryByTestId("reset-context-toggle")).not.toBeInTheDocument();
    expect(screen.queryByText("Reset context for this message")).not.toBeInTheDocument();
    expect(screen.queryByText("Single turn")).not.toBeInTheDocument();
  });

  it("renders context ring showing usage and opens popover with breakdown", async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Customer' }));
    await screen.findByText('Driver trip dispute context');

    const contextBtn = await screen.findByRole("button", { name: /ngữ cảnh/i });
    expect(contextBtn).toBeInTheDocument();
    expect(contextBtn).toHaveTextContent("15%");

    fireEvent.click(contextBtn);

    expect(await screen.findByText("Hồ sơ vụ việc")).toBeInTheDocument();
    expect(screen.getByText("Lịch sử hội thoại")).toBeInTheDocument();
    expect(screen.getByText("Kết quả công cụ")).toBeInTheDocument();
    expect(screen.getByText("Câu hỏi")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xóa ngữ cảnh" })).toBeInTheDocument();
  });

  it("executes clearAgentContext flow with confirmation, clears messages, and refetches usage", async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Customer' }));
    await screen.findByText('Driver trip dispute context');
    await screen.findByText('Tin nhắn ngữ cảnh ban đầu.');

    const contextBtn = await screen.findByRole("button", { name: /ngữ cảnh/i });
    fireEvent.click(contextBtn);

    const clearBtn = await screen.findByRole("button", { name: "Xóa ngữ cảnh" });
    fireEvent.click(clearBtn);

    // Confirmation step
    expect(await screen.findByText("Xác nhận xóa?")).toBeInTheDocument();
    const confirmBtn = screen.getByRole("button", { name: "Xác nhận" });
    expect(confirmBtn).toBeInTheDocument();

    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(contextApi.clearAgentContext).toHaveBeenCalledWith(mockItem.id);
      expect(contextApi.getAgentContext).toHaveBeenCalledTimes(2);
    });

    // Chat messages cleared
    expect(screen.queryByText("Tin nhắn ngữ cảnh ban đầu.")).not.toBeInTheDocument();
  });

  it("disables clear context button when case is not locked by current analyst", async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValueOnce({
      ...mockDetail,
      active_lease: {
        analyst_id: "other-analyst",
        expires_at: "2099-01-01T00:00:00Z",
      },
    });

    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Customer' }));
    await screen.findByText('Driver trip dispute context');

    const contextBtn = await screen.findByRole("button", { name: /ngữ cảnh/i });
    fireEvent.click(contextBtn);

    const clearBtn = await screen.findByRole("button", { name: "Xóa ngữ cảnh" });
    expect(clearBtn).toBeDisabled();
  });
});
