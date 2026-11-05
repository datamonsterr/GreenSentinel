import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ForensicBriefSummary } from "@/components/adjudication/forensic-brief-summary";
import { FinalizationTab } from "@/components/adjudication/finalization-tab";
import { committedJudgment } from "../../fixtures/staged-adjudication";
import type { CaseDetailResponse, ForensicBriefResponse } from "@/types/schemas";

vi.mock("@/components/map/maplibre-view", () => ({ MapLibreView: () => <div>Map</div> }));
const narrative = "Hành trình có tín hiệu định vị giả lập; cần đối chiếu trước khi kết luận về động cơ.";
const brief: ForensicBriefResponse = {
  generated_at: "2026-10-10T08:00:00Z",
  case_id: "case-motivation", abnormalities: [], abnormality_count: 0, evidence_sources: [], summary_text: "Dữ liệu hành trình đã ghi nhận.",
  motivation_assessment: { economic_incentive_reward: 15000, intent_profile: "possible_intentional_exploit", natural_vietnamese_narrative: narrative },
};

describe("motivation assessment", () => {
  it("renders direct narrative and VND reward in forensic summary", () => {
    render(<ForensicBriefSummary brief={brief} />);
    expect(screen.getByText(narrative)).toBeInTheDocument();
    expect(screen.getByText(/15.000/)).toBeInTheDocument();
    expect(screen.getByText("Có thể khai thác để hưởng lợi")).toBeInTheDocument();
  });
  it("distinguishes missing assessment from measured zero", () => {
    render(<ForensicBriefSummary />);
    expect(screen.getByText("Chưa xác định")).toBeInTheDocument();
  });
  it("renders the same narrative and reward in gated Complete", () => {
    const detail: CaseDetailResponse = { case: { id: "case-motivation", status: "open", priority: "P1", priority_score: 50, version: 1 }, preliminary_judgment: committedJudgment("case-motivation", "analyst-001"), trip: {}, telemetry_samples: [], forensic_brief: brief };
    render(<FinalizationTab caseDetail={detail} isActive canWrite={false} busy={false} choice="" onChoice={vi.fn()} note="" onNote={vi.fn()} savingJudgment={false} onSaveJudgment={vi.fn()} rationale="" onRationale={vi.fn()} onDecision={vi.fn()} delta="0" />);
    expect(screen.getByRole("region", { name: "AI results" })).toBeInTheDocument();
    expect(screen.getByText(narrative)).toBeInTheDocument();
    expect(screen.getByText("Economic incentive: 15,000 ₫")).toBeInTheDocument();
  });
});
