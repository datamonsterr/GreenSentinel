import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import * as api from "@/lib/api-client";
import { committedJudgment } from '../../fixtures/staged-adjudication';
import { DisputeDossierResponse, WorkflowTrace, PrecedentSimilarityMatch } from "@/types/schemas";

vi.mock("@/lib/api-client", () => ({
  fetchCases: vi.fn(),
  fetchCaseDetail: vi.fn(),
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
  matchCasePrecedent: vi.fn(),
  listPrecedents: vi.fn(),
  getPrecedent: vi.fn(),
}));

const mockCase = {
  id: "case-precedent-001",
  driver_name: "Nguyễn Văn Precedent",
  vehicle_plate: "29A-12345",
  priority: "P1",
  priority_score: 1,
  status: "driver_disputed",
  version: 2,
};

const mockWorkflowTrace: WorkflowTrace = {
  agent_tools_called: [
    {
      tool_name: "corroborate_traffic_conditions",
      input_summary: "corridor=Kim Ma, ratio=2.7x",
      output_summary: "speed=2.1 km/h, congestion=heavy",
      status: "success",
    },
    {
      tool_name: "query_driver_policy",
      input_summary: "query=traffic leeway",
      output_summary: "GSM-POL-042 clause 3.2 allows exoneration",
      status: "success",
    },
  ],
  human_actions_performed: [
    {
      actor_role: "driver",
      action_type: "dispute_statement",
      summary: "Kẹt xe tại đường Liễu Giai - Kim Mã",
    },
  ],
  driver_response_summary: "Kẹt xe tại đường Liễu Giai - Kim Mã trên 20 phút.",
  related_policies: [
    {
      policy_code: "GSM-POL-042",
      clause: "3.2 (Bất khả kháng do giao thông đô thị)",
      rationale: "Miễn trừ trễ đón khách khi vận tốc dưới 5 km/h",
      relevance_score: 0.98,
    },
  ],
  final_decision: {
    verdict: "exonerated",
    penalty_amount: 0,
    rationale: "Xác thực kẹt xe Kim Mã tự động từ viễn thông thực tế. Miễn trừ chế tài.",
    decided_by: "system_autonomous_agent",
    decided_at: "2026-09-26T20:00:00Z",
  },
};

const mockPrecedentMatch: PrecedentSimilarityMatch = {
  precedent_id: "018f2f4e-9100-7000-8000-000000000001",
  precedent_case_id: "case-seeded-01",
  title: "Ùn tắc giao thông nghiêm trọng giờ cao điểm đường Kim Mã",
  similarity_score: 0.94,
  matching_factors: [
    "Độ tin cậy Jev Decision AI: 94%",
    "Trùng khớp mã vi phạm: ERR-02",
    "Tương đồng tình huống khiếu nại: traffic_gridlock",
  ],
  recommended_procedure: ["corroborate_traffic_conditions", "query_driver_policy"],
  precedent_verdict: "exonerated",
  confidence_rationale: "Mô hình TypeSafe Jev nhận diện độ tương đồng cao với án lệ Kim Mã.",
  model_used: "jev",
  precedent_workflow: mockWorkflowTrace,
};

const mockDossier: DisputeDossierResponse = {
  case_id: "case-precedent-001",
  driver_id: "drv-001",
  driver_name: "Nguyễn Văn Precedent",
  dispute_status: "in_dispute",
  driver_statement: "Tôi bị kẹt xe cứng ở Kim Mã gần 30 phút",
  claim_type: "traffic_gridlock",
  traffic_corroboration: {
    ratio: 2.7,
    observed_speed: 2.1,
    congestion_level: "heavy",
    corroborated: true,
  },
  precedent_score: 0.94,
  recommended_action: "Auto-Dismiss",
  transcript: [
    {
      role: "driver",
      content: "Tôi bị kẹt xe cứng ở Kim Mã",
      timestamp: "2026-09-26T18:00:00Z",
    },
  ],
  matched_precedent: mockPrecedentMatch,
  matching_factors: mockPrecedentMatch.matching_factors,
  workflow_trace: mockWorkflowTrace,
};

describe("Cockpit Precedent Workflow & Jev Similarity Integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({
      items: [mockCase as any],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({
      case: mockCase as any,
      preliminary_judgment: committedJudgment(mockCase.id, 'analyst-001'),
      active_lease: { analyst_id: 'analyst-001', expires_at: '2099-01-01' },
      trip: {},
      conversation: [],
    });
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({
      id: "analyst-001",
      name: "Chuyên viên Thẩm định",
      role: "analyst", roles: ["analyst"],
    });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({
      session_id: "session-p-1",
      messages: [],
    });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(mockDossier);
    vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue(mockWorkflowTrace);
  });

  it("renders Jev AI Precedent Match card with match percentage, factors, and procedure", async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole("tab", { name: /complete|hoàn tất/i }));

    // Verify Jev Precedent Card appears
    expect(await screen.findByRole("region", { name: /matched precedent/i })).toBeInTheDocument();
    expect(screen.getByText("Similarity: 94%")).toBeInTheDocument();
    expect(
      screen.getByText("Ùn tắc giao thông nghiêm trọng giờ cao điểm đường Kim Mã")
    ).toBeInTheDocument();

    // Verify matching factors badges
    expect(screen.getByText(/Độ tin cậy Jev Decision AI: 94%/)).toBeInTheDocument();
    expect(screen.getByText(/Trùng khớp mã vi phạm: ERR-02/)).toBeInTheDocument();

    // Verify recommended procedure tools
    expect(screen.getAllByText(/corroborate_traffic_conditions/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/query_driver_policy/).length).toBeGreaterThan(0);
  });

  it("applies precedent procedure on 1-click button click and pre-fills rationale", async () => {
    vi.mocked(api.applyPrecedentProcedure).mockResolvedValue({
      case_id: "case-precedent-001",
      precedent_id: "018f2f4e-9100-7000-8000-000000000001",
      precedent_title: "Ùn tắc giao thông nghiêm trọng giờ cao điểm đường Kim Mã",
      recommended_verdict: "exonerated",
      recommended_penalty_amount: 0,
      recommended_rationale:
        "[Áp dụng quy trình án lệ #018f2f4e - 'Ùn tắc Kim Mã'] Xác thực kẹt xe tự động. Miễn trừ chế tài.",
      policy_citations: [],
      recommended_tools: ["corroborate_traffic_conditions"],
      applied_at: "2026-09-26T21:00:00Z",
    });

    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole("tab", { name: /complete|hoàn tất/i }));

    const applyBtn = await screen.findByRole(
      "button",
      { name: /Apply matched procedure|Áp dụng quy trình án lệ/i },
      { timeout: 5000 }
    );
    expect(applyBtn).toBeInTheDocument();

    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(api.applyPrecedentProcedure).toHaveBeenCalledWith(
        "case-precedent-001",
        "018f2f4e-9100-7000-8000-000000000001"
      );
    });

    // Verify decision rationale textarea was pre-filled
    const textarea = screen.getByLabelText("Decision rationale") as HTMLTextAreaElement;
    expect(textarea.value).toContain("[Áp dụng quy trình án lệ #018f2f4e");
    expect(textarea.value).toContain("Miễn trừ chế tài.");

    // Verify feedback indicator appears
    expect(screen.getByText(/Applied precedent/)).toBeInTheDocument();
  });

  it("renders Case Workflow Synthesis card with executed tools, policy leeway, and final verdict", async () => {
    render(<CockpitWorkspaceView />);
    fireEvent.click(await screen.findByRole("tab", { name: /complete|hoàn tất/i }));

    expect(await screen.findByRole("heading", { name: "Workflow" })).toBeInTheDocument();
    expect(screen.getByText("Policies")).toBeInTheDocument();

    // Verify tool execution badges
    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("speed=2.1 km/h, congestion=heavy")).toBeInTheDocument();

    // Verify Policy leeway
    expect(screen.getByText("Final decision")).toBeInTheDocument();
    expect(screen.getByText(/GSM-POL-042 · 3.2/)).toBeInTheDocument();

    // Verify Final Verdict
    expect(screen.getByText(/exonerated · Xác thực kẹt xe Kim Mã/)).toBeInTheDocument();
  });
});
