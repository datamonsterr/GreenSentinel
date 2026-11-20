import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { LocaleProvider } from "@/lib/locale";
import type { CaseDetailResponse, DriverScorecardResponse } from "@/types/schemas";

const detail = {
  case: { id: "driver-dashboard" },
  trip: {
    driver_name: "Tran Van B", vehicle_plate: "30A-888.88", vehicle_model: "VF e34",
    driver_status: "active", driver_statement: "Tôi đợi khách tại điểm đón.",
    rating: 4.9, acceptance_rate: 92, cancellation_rate: 8, total_trips: 850,
  },
} as unknown as CaseDetailResponse;
const scorecard: DriverScorecardResponse = {
  driver_id: "driver-1", violation_ratio_90d: 0.5, fined_ratio: 0.5,
  repeat_offense_risk_score: 75, benchmark_violation_ratio: 0.5,
  tenure_months: 22, past_incidents: [],
};
function show(trip: Record<string, unknown> = {}, history = scorecard) {
  return render(<LocaleProvider><DriverInfoTab caseDetail={{ ...detail, trip: { ...detail.trip, ...trip } } as CaseDetailResponse} scorecard={history} /></LocaleProvider>);
}
function value(label: string, text: string) {
  return within(screen.getByTitle(label)).getByText(text);
}
afterEach(() => localStorage.clear());

describe("Driver profile dashboard", () => {
  it("renders driver identity, evidence and all four labeled KPI values", () => {
    show();
    expect(screen.getByTitle("Name")).toHaveTextContent("Tran Van B");
    expect(screen.getByTitle("Vehicle plate")).toHaveTextContent("30A-888.88");
    expect(screen.getByTitle("Vehicle plate")).toHaveClass("font-mono");
    expect(screen.getByText("VF e34")).toBeVisible();
    expect(screen.getByText("TV")).toBeVisible();
    expect(screen.getByText("Active")).toHaveClass("text-gs-green-ink");
    expect(screen.getByText("Tôi đợi khách tại điểm đón.")).toBeVisible();
    for (const [label, expected] of [["Average rating", "4.9"], ["Acceptance rate", "92%"], ["Cancellation rate", "8%"], ["Total trips", "850"]]) {
      expect(value(label, expected)).toHaveClass("font-bold", "tabular-nums");
      expect(within(screen.getByTitle(label)).getByText(label)).toBeVisible();
    }
  });

  it.each([8, 0.08])("colors cancellation %s red after percentage normalization", cancellation_rate => {
    show({ cancellation_rate });
    expect(value("Cancellation rate", "8%")).toHaveClass("text-gs-red");
  });

  it.each([92, 0.92])("keeps healthy acceptance %s uncolored after percentage normalization (color only for severity)", acceptance_rate => {
    show({ acceptance_rate });
    expect(value("Acceptance rate", "92%")).toHaveClass("text-slate-900");
  });

  it.each([84, 0.84])("colors low acceptance %s amber", acceptance_rate => {
    show({ acceptance_rate });
    expect(value("Acceptance rate", "84%")).toHaveClass("text-gs-amber-ink");
  });

  it("respects exact rate thresholds and valid zero values", () => {
    show({ acceptance_rate: 85, cancellation_rate: 5, rating: 0, total_trips: 0 });
    expect(value("Acceptance rate", "85%")).not.toHaveClass("text-gs-amber-ink");
    expect(value("Cancellation rate", "5%")).not.toHaveClass("text-gs-red");
    expect(value("Average rating", "0")).not.toHaveClass("text-slate-500");
    expect(value("Total trips", "0")).not.toHaveClass("text-slate-500");
  });

  it.each([[0, "bg-gs-green"], [39, "bg-gs-green"], [40, "bg-gs-amber"], [69, "bg-gs-amber"], [70, "bg-gs-red"], [100, "bg-gs-red"]])("exposes risk %s with its semantic progress band", (risk, color) => {
    show({}, { ...scorecard, repeat_offense_risk_score: Number(risk) });
    const progress = screen.getByRole("progressbar", { name: "Repeat-offense risk" });
    expect(progress).toHaveAttribute("aria-valuemin", "0");
    expect(progress).toHaveAttribute("aria-valuemax", "100");
    expect(progress).toHaveAttribute("aria-valuenow", String(risk));
    expect(progress.firstElementChild).toHaveClass(String(color));
  });

  it("preserves history percentage units below one percent", () => {
    show();
    for (const label of ["90-day violation ratio", "Fined ratio", "Benchmark ratio"]) {
      expect(value(label, "0.5%")).toBeVisible();
      expect(screen.getByTitle(label)).not.toHaveTextContent("50%");
    }
  });

  it.each([null, undefined, Number.NaN])("renders missing or invalid metrics (%s) as the designed empty value", absent => {
    show({ rating: absent, acceptance_rate: absent, cancellation_rate: absent, total_trips: absent }, {
      ...scorecard, repeat_offense_risk_score: absent,
    } as unknown as DriverScorecardResponse);
    for (const label of ["Average rating", "Acceptance rate", "Cancellation rate", "Total trips", "Repeat-offense risk"]) {
      expect(value(label, "No data yet")).toHaveClass("text-slate-500");
    }
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("localizes Vietnamese KPI, history and driver status labels while preserving evidence", () => {
    localStorage.setItem("greensentinel.locale", "vi");
    show({ driver_status: "suspended" });
    expect(value("Điểm đánh giá trung bình", "4,9")).toBeVisible();
    expect(value("Tỷ lệ nhận chuyến", "92%")).toBeVisible();
    expect(value("Tỷ lệ huỷ chuyến", "8%")).toBeVisible();
    expect(value("Tổng số chuyến", "850")).toBeVisible();
    expect(screen.getByText("Lịch sử tài xế")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Rủi ro tái phạm" })).toHaveAttribute("aria-valuenow", "75");
    expect(screen.getByText("Đình chỉ")).toHaveClass("text-gs-red");
    expect(screen.getByText("22 tháng")).toBeVisible();
    expect(screen.getByText("Tôi đợi khách tại điểm đón.")).toBeVisible();
  });
});
