import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PresetRunDialog } from "@/components/test-console/presets/PresetRunDialog";
import * as testApiClient from "@/lib/testApiClient";

vi.mock("@/lib/testApiClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/testApiClient")>("@/lib/testApiClient");
  return {
    ...actual,
    fetchClerkLinkedDrivers: vi.fn(),
    createPresetBatchRun: vi.fn(),
  };
});

const mockPreset: testApiClient.TestPresetDetailResponse = {
  id: "test-preset-1",
  title: "Bộ dữ liệu Hà Nội",
  description: "Dữ liệu mẫu 100 chuyến",
  kind: "vietnam",
  available: true,
  unavailable_reason: null,
  source_label: "hanoi_road",
  selection_size: 100,
  available_trips: 100,
  trip_count: 100,
  metadata: {},
  metrics: {},
  sample_trips: [],
  distributions: {
    total_records: 100,
    by_label: { fraud: 20, no_violation: 80, insufficient_evidence: 0 },
    per_code: { "ERR-01": 20 },
    by_severity: { P1: 20 },
    by_scenario: { normal: 80, deviation: 20 },
    by_city: { "Hà Nội": 100 },
    by_cancellation_actor: { none: 100 },
  },
};

const mockDrivers: testApiClient.ClerkLinkedDriver[] = [
  { driver_id: "drv-001", display_name: "Nguyễn Văn A", email: "nva@test.com", principal_id: "p-01", license_plate: "29A-123.45" },
  { driver_id: "drv-002", display_name: "Trần Thị B", email: "ttb@test.com", principal_id: "p-02", license_plate: "29B-678.90" },
];

describe("PresetRunDialog & DriverChecklist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(testApiClient.fetchClerkLinkedDrivers).mockResolvedValue(mockDrivers);
    vi.mocked(testApiClient.createPresetBatchRun).mockResolvedValue({
      id: "batch-123",
      organization_id: "org-1",
      preset_id: "test-preset-1",
      params: {},
      status: "RUNNING",
      counters: { total: 10, queued: 10 },
      created_at: new Date().toISOString(),
      started_at: null,
      completed_at: null,
      cancelled_at: null,
    });
  });

  it("fetches drivers, selects all by default, and allows select all / none toggle", async () => {
    render(
      <PresetRunDialog
        open={true}
        onOpenChange={vi.fn()}
        preset={mockPreset}
        onRunSuccess={vi.fn()}
      />
    );

    // Verify drivers loaded and displayed
    expect(await screen.findByText("Nguyễn Văn A")).toBeDefined();
    expect(screen.getByText("Trần Thị B")).toBeDefined();
    expect(screen.getByTestId("driver-selected-count")).toHaveTextContent("Đã chọn: 2 / 2 tài xế");

    // Toggle "Chọn tất cả" to deselect all
    const selectAllCheckbox = screen.getByRole("checkbox", { name: "Chọn tất cả tài xế" });
    await act(async () => {
      fireEvent.click(selectAllCheckbox);
    });

    expect(screen.getByTestId("driver-selected-count")).toHaveTextContent("Đã chọn: 0 / 2 tài xế");

    // Run button must be disabled when 0 drivers selected
    const runBtn = screen.getByRole("button", { name: /Bắt đầu chạy/i });
    expect(runBtn).toBeDisabled();

    // Toggle back to select all
    await act(async () => {
      fireEvent.click(selectAllCheckbox);
    });
    expect(screen.getByTestId("driver-selected-count")).toHaveTextContent("Đã chọn: 2 / 2 tài xế");
    expect(runBtn).not.toBeDisabled();
  });

  it("handles trip count slider, 100% toggle, and rate limit inputs", async () => {
    render(
      <PresetRunDialog
        open={true}
        onOpenChange={vi.fn()}
        preset={mockPreset}
        onRunSuccess={vi.fn()}
      />
    );

    await screen.findByText("Nguyễn Văn A");

    // Change slider
    const slider = screen.getByLabelText("Số chuyến chạy");
    await act(async () => {
      fireEvent.change(slider, { target: { value: "25" } });
    });
    expect(screen.getByTestId("selected-trip-count")).toHaveTextContent("25 / 100");

    // Toggle 100%
    const toggle100 = screen.getByLabelText("Chạy 100% toàn bộ chuyến");
    await act(async () => {
      fireEvent.click(toggle100);
    });
    expect(screen.getByTestId("selected-trip-count")).toHaveTextContent("Toàn bộ (100)");

    // Change rate limit inputs
    const batchInput = screen.getByLabelText("Số chuyến mỗi đợt");
    const intervalInput = screen.getByLabelText("Khoảng cách giây");

    await act(async () => {
      fireEvent.change(batchInput, { target: { value: "3" } });
      fireEvent.change(intervalInput, { target: { value: "5" } });
    });

    expect(screen.getByText(/3 chuyến/i)).toBeDefined();
    expect(screen.getByText(/5 giây/i)).toBeDefined();
  });

  it("submits correct payload with driver_ids and handles API validation errors", async () => {
    const onRunSuccess = vi.fn();
    const onOpenChange = vi.fn();

    render(
      <PresetRunDialog
        open={true}
        onOpenChange={onOpenChange}
        preset={mockPreset}
        onRunSuccess={onRunSuccess}
      />
    );

    await screen.findByText("Nguyễn Văn A");

    const runBtn = screen.getByRole("button", { name: /Bắt đầu chạy/i });
    await act(async () => {
      fireEvent.click(runBtn);
    });

    expect(testApiClient.createPresetBatchRun).toHaveBeenCalledWith("test-preset-1", {
      trip_limit: 10,
      trips_per_batch: 1,
      interval_s: 2,
      driver_ids: ["drv-001", "drv-002"],
    });

    expect(onRunSuccess).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("displays validation error if createPresetBatchRun rejects", async () => {
    vi.mocked(testApiClient.createPresetBatchRun).mockRejectedValue(
      new Error("Tài xế drv-001 không thuộc tổ chức này")
    );

    render(
      <PresetRunDialog
        open={true}
        onOpenChange={vi.fn()}
        preset={mockPreset}
        onRunSuccess={vi.fn()}
      />
    );

    await screen.findByText("Nguyễn Văn A");

    const runBtn = screen.getByRole("button", { name: /Bắt đầu chạy/i });
    await act(async () => {
      fireEvent.click(runBtn);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Tài xế drv-001 không thuộc tổ chức này");
  });
});
