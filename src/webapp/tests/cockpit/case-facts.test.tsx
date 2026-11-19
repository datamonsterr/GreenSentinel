import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CaseLevelFacts, DisputeFacts } from "@/components/cockpit/case-facts";
import type { CaseDetailResponse } from "@/types/schemas";

const detail = { case: { id: "c1", status: "in_review", priority: "high", priority_score: 80, assigned_analyst_name: "Hà", sla_countdown_s: 0, dispute_status: "open" }, case_policy: { policy_version: "v3", applicable_action_rule: { action: "Warn" } } } as unknown as CaseDetailResponse;

describe("case facts", () => {
  it("shows localized status, not raw in_review, and policy fields", () => {
    render(<CaseLevelFacts caseDetail={detail} />);
    const el = screen.getByTestId("case-level-facts");
    expect(el.textContent).not.toContain("in_review");
    expect(el.textContent).toContain("v3");
    expect(el.textContent).toContain("Warn");
  });
  it("skips empty dispute facts", () => {
    render(<DisputeFacts caseDetail={{ case: { id: "c1" } } as unknown as CaseDetailResponse} />);
    expect(screen.queryByTestId("dispute-facts")).toBeNull();
  });
});
