import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { LocaleProvider } from "@/lib/locale";

describe("Driver tab history metrics labels and icons", () => {
  afterEach(() => {
    localStorage.clear();
  });
  const mockDetail: any = {
    case: { id: "case-drv-1" },
    trip: {
      driver_name: "Tran Van B",
      vehicle_plate: "30A-888.88",
      rating: 4.9,
      acceptance_rate: 98,
      cancellation_rate: 1.5,
      total_trips: 850,
    },
  };

  const mockScorecard: any = {
    violation_ratio_90d: 7.7,
    fined_ratio: 0.0,
    repeat_offense_risk_score: 75,
    benchmark_violation_ratio: 5.0,
    tenure_months: 22,
    past_incidents: [],
  };

  it("renders labeled English history cards with full metric tooltips", () => {
    render(
      <LocaleProvider>
        <DriverInfoTab caseDetail={mockDetail} scorecard={mockScorecard} />
      </LocaleProvider>
    );

    // Short muted inline labels
    expect(screen.getByText("90d violations")).toBeInTheDocument();
    expect(screen.getByText("Fined")).toBeInTheDocument();
    expect(screen.getByText("Repeat risk")).toBeInTheDocument();
    expect(screen.getByText("Benchmark")).toBeInTheDocument();
    expect(screen.getByText("Tenure")).toBeInTheDocument();

    // Values
    expect(screen.getByText("7.7%")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(within(screen.getByTitle("Repeat-offense risk")).getByText("75 / 100")).toBeInTheDocument();
    expect(screen.getByText("5%")).toBeInTheDocument();
    expect(screen.getByText("22 months")).toBeInTheDocument();

    // Tooltips / Aria preserved
    expect(screen.getByTitle("90-day violation ratio")).toBeInTheDocument();
    expect(screen.getByTitle("Fined ratio")).toBeInTheDocument();
    expect(screen.getByTitle("Repeat-offense risk")).toBeInTheDocument();
    expect(screen.getByTitle("Benchmark ratio")).toBeInTheDocument();
    expect(screen.getByTitle("Tenure")).toBeInTheDocument();

    // Driver info metrics keep icon+value with distinct tooltips
    expect(screen.getByTitle("Average rating")).toBeInTheDocument();
    expect(screen.getByTitle("Acceptance rate")).toBeInTheDocument();
    expect(screen.getByTitle("Cancellation rate")).toBeInTheDocument();
    expect(screen.getByTitle("Total trips")).toBeInTheDocument();
  });

  it("renders Vietnamese history card labels", () => {
    localStorage.setItem("greensentinel.locale", "vi");
    render(
      <LocaleProvider>
        <DriverInfoTab caseDetail={mockDetail} scorecard={mockScorecard} />
      </LocaleProvider>
    );

    expect(screen.getByText("Vi phạm 90 ngày")).toBeInTheDocument();
    expect(screen.getByText("Bị phạt")).toBeInTheDocument();
    expect(within(screen.getByTitle("Rủi ro tái phạm")).getByText("Rủi ro tái phạm")).toBeInTheDocument();
    expect(screen.getByText("Chuẩn")).toBeInTheDocument();
    expect(screen.getByText("Thâm niên")).toBeInTheDocument();

    expect(screen.getByText("22 tháng")).toBeInTheDocument();
  });
});
