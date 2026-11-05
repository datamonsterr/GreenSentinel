import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { HistoryTable } from "@/components/test-console/HistoryTable";
import type { TestRunSummary } from "@/lib/testApiClient";

describe("HistoryTable", () => {
  const sampleRuns: TestRunSummary[] = [
    {
      id: "run-1",
      title: "Chuyến thử nghiệm 1",
      status: "COMPLETED",
      trip_id: "trip-alpha-001",
      created_at: "2026-10-16T10:00:00Z",
      completed_at: "2026-10-16T10:15:00Z",
      cancellation_actor: null,
      cancellation_reason: null,
      source: "manual",
      driver_name: "Nguyễn Văn A",
      license_plate: "29A-12345",
      case_id: "case-001",
      origin_address: "Số 1 Tràng Tiền, Hoàn Kiếm, Hà Nội",
      pickup_address: "Số 10 Hai Bà Trưng, Hoàn Kiếm, Hà Nội",
      destination_address: "Số 100 Nguyễn Chí Thanh, Đống Đa, Hà Nội",
      predicted_label: "ERR-01",
      expected_label: "ERR-01",
      error_type: "GPS_SPOOFING",
      confidence: 0.952,
    },
    {
      id: "run-2",
      title: null,
      status: "COMPLETED",
      trip_id: "trip-beta-002",
      created_at: "2026-10-16T11:00:00Z",
      completed_at: "2026-10-16T11:20:00Z",
      cancellation_actor: "driver",
      cancellation_reason: "Hỏng xe đột xuất",
      source: "preset",
      driver_name: "Trần Văn B",
      license_plate: "30E-67890",
      case_id: "case-002",
      origin_address: "Bến xe Mỹ Đình, Nam Từ Liêm, Hà Nội",
      pickup_address: "Keangnam Landmark, Cầu Giấy, Hà Nội",
      destination_address: "Sân bay Nội Bài, Sóc Sơn, Hà Nội",
      predicted_label: "ERR-02",
      expected_label: "LEGITIMATE",
      error_type: "WRONG_DROPOFF",
      confidence: 0.824,
    },
    {
      id: "run-3",
      title: "Chuyến không nhãn",
      status: "CANCELLED",
      trip_id: "trip-gamma-003",
      created_at: "2026-10-16T12:00:00Z",
      completed_at: null,
      cancellation_actor: "customer",
      cancellation_reason: "Đổi ý không đi nữa",
      source: "preset_batch",
      driver_name: "Lê Văn C",
      license_plate: "51F-99999",
      case_id: null,
      origin_address: "Quận 1, TP.HCM",
      pickup_address: "Quận 3, TP.HCM",
      destination_address: "Quận 7, TP.HCM",
      predicted_label: "NORMAL",
      expected_label: null,
      error_type: null,
      confidence: 0.45,
    },
    {
      id: "run-4",
      title: "Chuyến lỗi nhưng không có case_id",
      status: "COMPLETED",
      trip_id: "trip-delta-004",
      created_at: "2026-10-16T13:00:00Z",
      completed_at: "2026-10-16T13:30:00Z",
      cancellation_actor: null,
      cancellation_reason: null,
      source: "manual",
      driver_name: "Phạm Văn D",
      license_plate: "43A-11111",
      case_id: null,
      origin_address: "Hải Châu, Đà Nẵng",
      pickup_address: "Sơn Trà, Đà Nẵng",
      destination_address: "Ngũ Hành Sơn, Đà Nẵng",
      predicted_label: "ERR-03",
      expected_label: "ERR-03",
      error_type: "ROUTE_DEVIATION",
      confidence: 0.99,
    },
  ];

  it("renders one-line identity fields for each row", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // Row 1 checks
    expect(screen.getByText("Chuyến thử nghiệm 1")).toBeInTheDocument();
    expect(screen.getAllByText("Thủ công").length).toBeGreaterThan(0); // source badge: manual
    expect(screen.getByText("Nguyễn Văn A")).toBeInTheDocument();
    expect(screen.getByText("29A-12345")).toBeInTheDocument();
    expect(screen.getByText("case-001")).toBeInTheDocument();
    expect(screen.getByText("GPS_SPOOFING")).toBeInTheDocument();
    expect(screen.getByText("95.2%")).toBeInTheDocument();

    // Row 2 title fallback to trip_id
    expect(screen.getByText("trip-beta-002")).toBeInTheDocument();
    expect(screen.getAllByText("Mẫu có sẵn").length).toBeGreaterThan(0); // source badge: preset
    expect(screen.getByText("Trần Văn B")).toBeInTheDocument();
    expect(screen.getByText("30E-67890")).toBeInTheDocument();
    expect(screen.getByText("case-002")).toBeInTheDocument();
    expect(screen.getByText("WRONG_DROPOFF")).toBeInTheDocument();
    expect(screen.getByText("82.4%")).toBeInTheDocument();

    // Truncated route with tooltip title
    const routeElements = screen.getAllByTestId("route-flow");
    expect(routeElements.length).toBe(4);
    expect(routeElements[0]).toHaveAttribute(
      "title",
      "Số 1 Tràng Tiền, Hoàn Kiếm, Hà Nội → Số 10 Hai Bà Trưng, Hoàn Kiếm, Hà Nội → Số 100 Nguyễn Chí Thanh, Đống Đa, Hà Nội"
    );
  });

  it("renders correctness pill: match, mismatch, no label", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // Row 1: predicted ERR-01 == expected ERR-01 -> Khớp (match)
    // Row 2: predicted ERR-02 != expected LEGITIMATE -> Lệch (mismatch)
    // Row 3: expected_label is null -> Chưa có nhãn (no label)
    expect(screen.getAllByText("Khớp").length).toBe(2); // run-1 and run-4 both match
    expect(screen.getByText("Lệch")).toBeInTheDocument();
    expect(screen.getByText("Chưa có nhãn")).toBeInTheDocument();
  });

  it("toggles row expansion to show timestamps, cancellation actor/reason, and full addresses", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // Initially details are not visible
    expect(screen.queryByText(/Hỏng xe đột xuất/)).not.toBeInTheDocument();

    // Toggle expand button for row 2
    const expandButtons = screen.getAllByRole("button", { name: /chi tiết/i });
    fireEvent.click(expandButtons[1]);

    // Now cancellation reason & full addresses should be visible in expanded container
    expect(screen.getByText(/Hỏng xe đột xuất/)).toBeInTheDocument();
    expect(screen.getByTestId("cancel-actor-detail")).toHaveTextContent("Tài xế");
    expect(screen.getAllByText(/Bến xe Mỹ Đình, Nam Từ Liêm, Hà Nội/).length).toBe(2);
    expect(screen.getAllByText(/Sân bay Nội Bài, Sóc Sơn, Hà Nội/).length).toBe(2);

    // Toggle off
    fireEvent.click(expandButtons[1]);
    expect(screen.queryByText(/Hỏng xe đột xuất/)).not.toBeInTheDocument();
  });

  it("renders workplace link ONLY for ERR-* rows with a case_id", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // run-1 has ERR-01 and case-001 -> link to /workplace?caseId=case-001
    const run1Link = screen.getByRole("link", { name: /case-001/i });
    expect(run1Link).toBeInTheDocument();
    expect(run1Link).toHaveAttribute("href", "/workplace?caseId=case-001");

    // run-2 has ERR-02 and case-002 -> link to /workplace?caseId=case-002
    const run2Link = screen.getByRole("link", { name: /case-002/i });
    expect(run2Link).toBeInTheDocument();
    expect(run2Link).toHaveAttribute("href", "/workplace?caseId=case-002");

    // run-3 has NORMAL and no case_id -> no link
    expect(screen.queryByRole("link", { name: /trip-gamma-003/i })).not.toBeInTheDocument();

    // run-4 has ERR-03 but NO case_id -> no workplace link
    expect(screen.queryByRole("link", { name: /case-004/i })).not.toBeInTheDocument();
    const allLinks = screen.getAllByRole("link");
    expect(allLinks.length).toBe(2);
  });

  it("calculates summary accuracy math and per-class counts over loaded rows", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // Summary calculations:
    // Total runs: 4
    // Labelled (expected_label !== null): 3 (run-1, run-2, run-4)
    // Matches: 2 (run-1, run-4)
    // Mismatches: 1 (run-2)
    // Accuracy: 2 / 3 = 66.7%
    // Per-class predicted counts:
    // ERR-01: 1, ERR-02: 1, NORMAL: 1, ERR-03: 1
    const summary = screen.getByTestId("history-summary-header");
    expect(within(summary).getByTestId("summary-total")).toHaveTextContent("4");
    expect(within(summary).getByTestId("summary-labelled")).toHaveTextContent("3");
    expect(within(summary).getByTestId("summary-accuracy")).toHaveTextContent("66.7%");
    expect(within(summary).getByTestId("summary-mismatches")).toHaveTextContent("1");
    expect(within(summary).getByTestId("summary-matches")).toHaveTextContent("2");
  });

  it("filters rows by source, predicted label, and mismatches only", () => {
    render(<HistoryTable runs={sampleRuns} />);

    // Filter by source: preset
    const sourceSelect = screen.getByLabelText(/Lọc nguồn/i);
    fireEvent.change(sourceSelect, { target: { value: "preset" } });

    expect(screen.queryByText("Chuyến thử nghiệm 1")).not.toBeInTheDocument();
    expect(screen.getByText("trip-beta-002")).toBeInTheDocument();

    // Reset source filter
    fireEvent.change(sourceSelect, { target: { value: "all" } });

    // Filter by predicted label: ERR-01
    const labelSelect = screen.getByLabelText(/Lọc nhãn dự đoán/i);
    fireEvent.change(labelSelect, { target: { value: "ERR-01" } });
    expect(screen.getByText("Chuyến thử nghiệm 1")).toBeInTheDocument();
    expect(screen.queryByText("trip-beta-002")).not.toBeInTheDocument();

    // Reset label filter
    fireEvent.change(labelSelect, { target: { value: "all" } });

    // Filter by mismatches only
    const mismatchCheckbox = screen.getByLabelText(/Chỉ chuyến lệch nhãn/i);
    fireEvent.click(mismatchCheckbox);

    // Only run-2 has mismatch
    expect(screen.queryByText("Chuyến thử nghiệm 1")).not.toBeInTheDocument();
    expect(screen.getByText("trip-beta-002")).toBeInTheDocument();
    expect(screen.queryByText("Chuyến không nhãn")).not.toBeInTheDocument();
    expect(screen.queryByText("Chuyến lỗi nhưng không có case_id")).not.toBeInTheDocument();
  });
});
