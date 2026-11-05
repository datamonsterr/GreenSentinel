import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import * as api from "@/lib/api-client";
import type { CaseDetailResponse, FraudCaseSummary } from "@/types/schemas";

vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: () => <div data-testid="mock-maplibre-view" />,
}));

vi.mock("@/lib/api-client", () => ({
  fetchCases: vi.fn(),
  fetchCaseHistory: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchForensicBrief: vi.fn(),
  fetchCasePolicy: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  claimCase: vi.fn(),
  releaseCase: vi.fn(),
  adjudicateCase: vi.fn(),
  recordCaseAction: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
  streamPolicyChat: vi.fn(),
  getDisputeDossier: vi.fn(),
  delegateAnalystInquiry: vi.fn(),
  getCaseWorkflowTrace: vi.fn(),
  applyPrecedentProcedure: vi.fn(),
  getApiBaseUrl: vi.fn(() => ""),
  authorizedHeaders: vi.fn(async () => ({ "Content-Type": "application/json" })),
}));

const mockCaseItem: FraudCaseSummary = {
  id: "case-380",
  driver_id: "driver-380",
  driver_name: "Trần Văn Test",
  vehicle_plate: "29A-38000",
  priority: "P1",
  priority_score: 90,
  status: "ready",
  version: 1,
};

const baseCaseDetail: CaseDetailResponse = {
  case: mockCaseItem,
  trip: {
    pickup_address: "Hanoi Central",
    dropoff_address: "VinUni Campus",
  },
  conversation: [],
};

describe("Issue #380: Copilot chat ownership gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [mockCaseItem], total: 1, limit: 50, offset: 0 });
    vi.mocked(api.fetchCaseHistory).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({
      id: "analyst-me-380",
      name: "Analyst Me",
      role: "analyst",
    });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: "session-380", messages: [] });
    vi.mocked(api.fetchForensicBrief).mockResolvedValue({
      case_id: "case-380",
      generated_at: "2026-10-15T01:00:00Z",
      abnormalities: [],
      abnormality_count: 0,
      evidence_sources: [],
      summary_text: "",
    });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(null as any);
    vi.mocked(api.getCaseWorkflowTrace).mockRejectedValue(new Error("No trace"));
    vi.mocked(api.streamPolicyChat).mockImplementation(() => () => {});
  });

  afterEach(() => {
    cleanup();
  });

  it("disables chat input and send action when case is unclaimed", async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...baseCaseDetail,
      active_lease: null,
    });

    render(<CockpitWorkspaceView />);

    const input = await screen.findByPlaceholderText(/Claim case to chat with AI Copilot…/i);
    expect(input).toBeDisabled();

    const sendBtn = screen.getByRole("button", { name: "Send message" });
    expect(sendBtn).toBeDisabled();

    // Verify submission is blocked
    fireEvent.change(input, { target: { value: "Hello agent" } });
    fireEvent.click(sendBtn);
    expect(api.streamPolicyChat).not.toHaveBeenCalled();
  });

  it("disables chat input when case is claimed by another analyst", async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...baseCaseDetail,
      active_lease: {
        analyst_id: "analyst-other-999",
        expires_at: new Date(Date.now() + 300000).toISOString(),
      },
    });

    render(<CockpitWorkspaceView />);

    const input = await screen.findByPlaceholderText(/Case claimed by another analyst/i);
    expect(input).toBeDisabled();

    const sendBtn = screen.getByRole("button", { name: "Send message" });
    expect(sendBtn).toBeDisabled();
    expect(api.streamPolicyChat).not.toHaveBeenCalled();
  });

  it("disables chat input when lease is expired", async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...baseCaseDetail,
      active_lease: {
        analyst_id: "analyst-me-380",
        expires_at: new Date(Date.now() - 10000).toISOString(), // expired in past
      },
    });

    render(<CockpitWorkspaceView />);

    const input = await screen.findByPlaceholderText(/lease expired/i);
    expect(input).toBeDisabled();

    const sendBtn = screen.getByRole("button", { name: "Send message" });
    expect(sendBtn).toBeDisabled();
    expect(api.streamPolicyChat).not.toHaveBeenCalled();
  });

  it("enables chat input and allows sending when case is claimed by current analyst", async () => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      ...baseCaseDetail,
      active_lease: {
        analyst_id: "analyst-me-380",
        expires_at: new Date(Date.now() + 300000).toISOString(),
      },
    });

    render(<CockpitWorkspaceView />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Ask Agents about this case…")).toBeEnabled();
    });
    const input = screen.getByPlaceholderText("Ask Agents about this case…");

    const user = userEvent.setup();
    await user.type(input, "Review pickup evidence");
    const sendBtn = screen.getByRole("button", { name: "Send message" });
    expect(sendBtn).toBeEnabled();

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                'data: {"event": "run.completed"}\n\n'
              )
            );
            controller.close();
          },
        })
      )
    );

    fireEvent.submit(input.closest("form")!);
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/policy/chat/stream"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"query":"Review pickup evidence"'),
        })
      );
    });
    fetchSpy.mockRestore();
  });

  it("claiming an eligible case enables chat, and releasing disables it", async () => {
    const unclaimedDetail = { ...baseCaseDetail, active_lease: null };
    const claimedDetail = {
      ...baseCaseDetail,
      active_lease: {
        analyst_id: "analyst-me-380",
        expires_at: new Date(Date.now() + 300000).toISOString(),
      },
    };

    vi.mocked(api.fetchCaseDetail)
      .mockResolvedValueOnce(unclaimedDetail)
      .mockResolvedValueOnce(claimedDetail)
      .mockResolvedValueOnce(unclaimedDetail);

    vi.mocked(api.claimCase).mockResolvedValue({
      case_id: "case-380",
      analyst_id: "analyst-me-380",
      status: "claimed",
      lease_expires_at: new Date(Date.now() + 300000).toISOString(),
    });

    vi.mocked(api.releaseCase).mockResolvedValue({
      case_id: "case-380",
      analyst_id: "analyst-me-380",
      status: "released",
      released_at: new Date().toISOString(),
    });

    render(<CockpitWorkspaceView />);

    // 1. Initial: unclaimed -> disabled
    const input = await screen.findByPlaceholderText(/Claim case to chat with AI Copilot…/i);
    expect(input).toBeDisabled();

    // 2. Click Claim button on the queue card
    const claimBtn = await screen.findByRole("button", { name: "Claim" });
    fireEvent.click(claimBtn);

    // 3. Now claimed -> enabled
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Ask Agents about this case…")).toBeEnabled();
    });

    // 4. Click Release button on the queue card
    const releaseBtn = await screen.findByRole("button", { name: "Release" });
    fireEvent.click(releaseBtn);

    // 5. Released -> disabled again
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Claim case to chat with AI Copilot…/i)).toBeDisabled();
    });
  });
});
