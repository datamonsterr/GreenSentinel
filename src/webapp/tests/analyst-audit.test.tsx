import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnalystProfileView } from "@/components/views/profile-view";
import * as api from "@/lib/api-client";
import { AnalystAuditProfileResponse } from "@/types/schemas";

const mockAuditProfile: AnalystAuditProfileResponse = {
  analyst_id: "analyst-001",
  display_name: "Nguyễn Hoàng Nam",
  roles: ["fraud_analyst", "analyst"],
  organization_id: "018f2f4e-0000-7000-8000-000000000001",
  metrics: {
    today_decisions_count: 42,
    thirty_day_decisions_count: 1420,
    average_mttr_seconds: 31.8,
    model_agreement_pct: 98.4,
    quality_overturn_pct: 0.8,
  },
  governance_limits: {
    dismiss_authority: "Unrestricted",
    warning_authority: "Authorized",
    direct_fine_limit_vnd: 2000000,
    suspension_authority: "24h / 48h Lockout",
    role: "fraud_analyst",
  },
  active_lease: {
    case_id: "case-active-01",
    case_code: "#FC-8921",
    severity: "P0",
    driver_name: "Nguyễn Văn Tuấn",
    vehicle_plate: "30A-123.45",
    expires_at: new Date(Date.now() + 48000).toISOString(),
    remaining_seconds: 48,
  },
  ledger: [
    {
      id: "ledger-01",
      case_id: "case-audit-01",
      case_code: "#FC-1001",
      timestamp: "2026-10-04T12:00:00Z",
      actor_id: "analyst-001",
      actor_name: "Nguyễn Hoàng Nam",
      actor_type: "analyst",
      action: "adjudicate",
      verdict: "AGREE",
      subject_entity: "Trần Đức Bình (29E-888.88)",
      triggered_violation: "ERR-02",
      sanction: "Direct Sanction Applied",
      rationale: "Stationary duration confirmed above threshold",
      snapshot_version: 2,
      request_hash: "sha256-abcdef123456",
    },
    {
      id: "ledger-02",
      case_id: "case-audit-02",
      case_code: "#FC-1002",
      timestamp: "2026-10-04T11:00:00Z",
      actor_id: "analyst-001",
      actor_name: "Nguyễn Hoàng Nam",
      actor_type: "analyst",
      action: "adjudicate",
      verdict: "DISAGREE",
      subject_entity: "Phạm Văn Cường (51A-999.99)",
      triggered_violation: "ERR-05",
      sanction: "Case Dismissed",
      rationale: "Traffic jam corroborated by peer telemetry",
      snapshot_version: 1,
      request_hash: "sha256-123456abcdef",
    },
  ],
  total_ledger_count: 2,
};

describe("AnalystProfileView", () => {
  it("renders 4-card metrics row from persisted decision audit data", async () => {
    vi.spyOn(api, "fetchAnalystAuditProfile").mockResolvedValue(mockAuditProfile);
    vi.spyOn(api, "fetchCurrentAnalyst").mockResolvedValue({
      id: "analyst-001",
      name: "Nguyễn Hoàng Nam",
      role: "fraud_analyst", roles: ["fraud_analyst"],
    });
    vi.spyOn(api, "fetchCases").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    render(<AnalystProfileView />);

    expect((await screen.findAllByText("Nguyễn Hoàng Nam")).length).toBeGreaterThan(0);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("+5% quota")).toBeInTheDocument();
    expect(screen.getByText("31.8s")).toBeInTheDocument();
    expect(screen.getByText("< 45s target")).toBeInTheDocument();
    expect(screen.getByText("0.8%")).toBeInTheDocument();
    expect(screen.getByText("1,420")).toBeInTheDocument();
    expect(screen.getByText("100% HITL")).toBeInTheDocument();
  });

  it("renders active review lock banner with countdown and resume action", async () => {
    vi.spyOn(api, "fetchAnalystAuditProfile").mockResolvedValue(mockAuditProfile);
    vi.spyOn(api, "fetchCurrentAnalyst").mockResolvedValue({
      id: "analyst-001",
      name: "Nguyễn Hoàng Nam",
      role: "fraud_analyst", roles: ["fraud_analyst"],
    });
    vi.spyOn(api, "fetchCases").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const resumeFn = vi.fn();
    render(<AnalystProfileView onResumeCase={resumeFn} />);

    expect(await screen.findByText("#FC-8921")).toBeInTheDocument();
    expect(screen.getByText(/P0 CRITICAL/)).toBeInTheDocument();
    expect(screen.getByText(/Nguyễn Văn Tuấn/)).toBeInTheDocument();
    expect(screen.getByText(/remaining/)).toBeInTheDocument();

    const resumeBtn = screen.getByRole("button", { name: /Resume Case/i });
    fireEvent.click(resumeBtn);
    expect(resumeFn).toHaveBeenCalledWith("case-active-01");
  });

  it("renders governance limits bar with authorized authorities", async () => {
    vi.spyOn(api, "fetchAnalystAuditProfile").mockResolvedValue(mockAuditProfile);
    vi.spyOn(api, "fetchCurrentAnalyst").mockResolvedValue({
      id: "analyst-001",
      name: "Nguyễn Hoàng Nam",
      role: "fraud_analyst", roles: ["fraud_analyst"],
    });
    vi.spyOn(api, "fetchCases").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    render(<AnalystProfileView />);

    expect(await screen.findByText("Governance Limits & Delegated Authority")).toBeInTheDocument();
    expect(screen.getByText("Unrestricted")).toBeInTheDocument();
    expect(screen.getByText("Authorized")).toBeInTheDocument();
    expect(screen.getByText("≤ 2M VND")).toBeInTheDocument();
    expect(screen.getByText("24h / 48h Lockout")).toBeInTheDocument();
    expect(screen.getByText("98.4%")).toBeInTheDocument();
  });

  it("renders verdict audit trail table with immutable items and search/filter interactions", async () => {
    const fetchSpy = vi.spyOn(api, "fetchAnalystAuditProfile").mockResolvedValue(mockAuditProfile);
    vi.spyOn(api, "fetchCurrentAnalyst").mockResolvedValue({
      id: "analyst-001",
      name: "Nguyễn Hoàng Nam",
      role: "fraud_analyst", roles: ["fraud_analyst"],
    });
    vi.spyOn(api, "fetchCases").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    render(<AnalystProfileView />);

    expect(await screen.findByText("Verdict Audit Trail")).toBeInTheDocument();
    expect(screen.getByText("#FC-1001")).toBeInTheDocument();
    expect(screen.getByText(/Trần Đức Bình/)).toBeInTheDocument();
    expect(screen.getByText("AGREE")).toBeInTheDocument();
    expect(screen.getByText("#FC-1002")).toBeInTheDocument();
    expect(screen.getAllByText("DISAGREE").length).toBeGreaterThan(0);

    // Trigger search
    const searchInput = screen.getByPlaceholderText("Search case, driver, plate...");
    fireEvent.change(searchInput, { target: { value: "29E-888" } });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ search: "29E-888" })
      );
    });

    // Trigger verdict filter
    const verdictSelect = screen.getByRole("combobox");
    fireEvent.change(verdictSelect, { target: { value: "DISAGREE" } });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ verdict: "DISAGREE" })
      );
    });
  });
});
