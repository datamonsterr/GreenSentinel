import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import DriverDisputePage from "@/app/driver/(tabs)/chat/[caseId]/page";
import DriverPortalPage from "@/app/driver/(tabs)/cases/page";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import * as api from "@/lib/api-client";
import { committedJudgment } from '../../fixtures/staged-adjudication';
import {
  DriverDisputeContextResponse,
  DisputeDossierResponse,
} from "@/types/schemas";

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "An" }, isLoaded: true }),
}));

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ caseId: "case-test-101" }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
}));

// Mock api-client
vi.mock("@/lib/api-client", () => ({
  getDriverDisputeContext: vi.fn(),
  streamDriverChat: vi.fn(),
  sendDriverChat: vi.fn(),
  getDisputeDossier: vi.fn(),
  delegateAnalystInquiry: vi.fn(),
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
  getCaseWorkflowTrace: vi.fn().mockResolvedValue(null),
  applyPrecedentProcedure: vi.fn(),
  fetchDriverCases: vi.fn(),
  fetchDriverSession: vi.fn(),
}));

const mockContext: DriverDisputeContextResponse = {
  case_id: "case-test-101",
  driver_id: "drv-999",
  driver_name: "Nguyễn Văn A",
  trip_id: "trip-777",
  violation_code: "ERR-02",
  violation_title: "Tài xế cố tình hủy chuyến để nhận phí hỗ trợ",
  alleged_time: "2026-09-26T08:30:00Z",
  alleged_location: "Ngã tư Kim Mã - Liễu Giai, Ba Đình",
  dispute_deadline: new Date(Date.now() + 48 * 3600 * 1000).toISOString(),
  dispute_status: "not_disputed",
  allowed_claim_types: ["traffic_gridlock", "gps_issue", "passenger_wait", "breakdown"],
};

const mockDossier: DisputeDossierResponse = {
  case_id: "case-cockpit-1",
  driver_id: "drv-999",
  driver_name: "Nguyễn Văn A",
  dispute_status: "in_dispute",
  driver_statement: "Kẹt xe nghiêm trọng tại hầm chui Kim Mã hơn 25 phút",
  claim_type: "traffic_gridlock",
  traffic_corroboration: {
    ratio: 3.4,
    observed_speed: 4.8,
    congestion_level: "heavy",
    corroborated: true,
  },
  precedent_score: 0.94,
  recommended_action: "Auto-Dismiss",
  transcript: [
    {
      id: "turn-1",
      role: "driver",
      text: "Tôi bị kẹt xe cứng nhắc ở ngã tư, không thể tới điểm đón đúng giờ.",
      occurred_at: "2026-09-26T08:35:00Z",
    },
    {
      id: "turn-2",
      role: "agent",
      text: "Hệ thống đang đối soát dữ liệu viễn thông và tình trạng giao thông.",
      occurred_at: "2026-09-26T08:35:10Z",
    },
  ],
};

describe("Driver Case Chat Page (/driver/chat/[caseId])", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getDriverDisputeContext).mockResolvedValue(mockContext);
    vi.mocked(api.fetchDriverSession).mockResolvedValue({ messages: [] } as any);
  });

  it("renders the back button and header title once context loads", async () => {
    render(<DriverDisputePage />);

    expect(await screen.findByTestId("case-back-button")).toBeInTheDocument();
    expect(await screen.findByText(/Lái xe lệch tuyến, kéo dài hoặc di chuyển sai hướng/i)).toBeInTheDocument();
  });
});

describe("Driver Cases route (/driver/cases)", () => {
  // Detailed card, segmentation and navigation coverage lives in
  // tests/unit/components/driver/cases.test.tsx and tests/e2e/browser/driver-cases.spec.ts.
  it("renders the redesigned cases view", async () => {
    vi.spyOn(api, "fetchDriverCases").mockResolvedValue({ items: [] } as never);
    render(<DriverPortalPage />);
    await waitFor(() => expect(api.fetchDriverCases).toHaveBeenCalled());
  });
});

describe("Cockpit View Integration - Driver Dispute Synthesis & A2A Delegation", () => {
  const caseItem = {
    id: "case-cockpit-1",
    driver_name: "Nguyễn Văn A",
    vehicle_plate: "29A-12345",
    priority: "P1",
    priority_score: 85,
    status: "ready",
    version: 2,
    dispute_status: "in_dispute",
  };

  const caseDetail = {
    case: caseItem,
    preliminary_judgment: committedJudgment(caseItem.id, 'analyst-007'),
    trip: { pickup_address: "123 Cầu Giấy", dropoff_address: "456 Kim Mã", fare_amount_vnd: 85000 },
    conversation: [{ role: "driver" as const, text: "Tôi đang di chuyển đến", occurred_at: "2026-09-26T08:00:00Z" }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchCases).mockResolvedValue({ items: [caseItem], total: 1, limit: 50, offset: 0 });
    vi.mocked(api.fetchCaseDetail).mockResolvedValue(caseDetail as any);
    vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: "analyst-007", name: "Trần Chuyên Viên", role: "analyst", roles: ["analyst"] });
    vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: "sess-1", messages: [] });
    vi.mocked(api.getDisputeDossier).mockResolvedValue(mockDossier);
    vi.mocked(api.delegateAnalystInquiry).mockResolvedValue({ status: "inquiry_delegated", case_id: "case-cockpit-1" });
  });

  it("fetches and renders embedded conversation chat in the conversation panel", async () => {
    render(<CockpitWorkspaceView />);

    // Switch to Conversation tab
    const conversationTab = await screen.findByRole("tab", { name: /customer/i });
    fireEvent.click(conversationTab);

    // Verify embedded chat feed and header
    expect(await screen.findByTestId("conversation-chat-feed")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Driver–customer conversation" })).toBeInTheDocument();
    expect(screen.getAllByText(/Tôi đang di chuyển đến/).length).toBeGreaterThan(0);
    expect(screen.queryByTitle(/Driver statement:/)).not.toBeInTheDocument();

    // Model recommendations belong in Complete, never the customer evidence feed.
    expect(screen.queryByText("Rec: Auto-Dismiss")).not.toBeInTheDocument();
  });

  it("renders the embedded customer conversation as a read-only feed", async () => {
    render(<CockpitWorkspaceView />);

    // Switch to Conversation tab
    const conversationTab = await screen.findByRole("tab", { name: /customer/i });
    fireEvent.click(conversationTab);

    const feed = await screen.findByTestId("conversation-chat-feed");
    expect(feed).toBeInTheDocument();
    expect(within(feed).getByText("Tôi đang di chuyển đến")).toBeInTheDocument();

    // Read-only feed: no composer, no send action, no delegation side effects.
    const conversation = screen.getByRole("region", { name: "Driver–customer conversation" });
    expect(within(conversation).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(conversation).queryByTestId("conversation-chat-input")).not.toBeInTheDocument();
    expect(within(conversation).queryByRole("button", { name: /Gửi|Send/i })).not.toBeInTheDocument();
    expect(api.delegateAnalystInquiry).not.toHaveBeenCalled();
  });

  it("preserves delegateAnalystInquiry API client endpoint for future agent delegation", async () => {
    const res = await api.delegateAnalystInquiry("case-cockpit-1", {
      case_id: "case-cockpit-1",
      analyst_id: "analyst-007",
      instruction: "Anh có hình ảnh chụp tắc đường không?",
    });

    expect(res).toEqual({ status: "inquiry_delegated", case_id: "case-cockpit-1" });
    expect(api.delegateAnalystInquiry).toHaveBeenCalledWith("case-cockpit-1", {
      case_id: "case-cockpit-1",
      analyst_id: "analyst-007",
      instruction: "Anh có hình ảnh chụp tắc đường không?",
    });
  });
});
