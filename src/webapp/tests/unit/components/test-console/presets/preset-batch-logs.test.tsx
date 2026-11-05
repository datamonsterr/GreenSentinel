import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PresetBatchLogs } from "@/components/test-console/presets/PresetBatchLogs";
import * as testApiClient from "@/lib/testApiClient";
import * as batchStream from "@/lib/preset-batch-stream";

vi.mock("@/lib/testApiClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/testApiClient")>("@/lib/testApiClient");
  return {
    ...actual,
    fetchPresetBatchRunDetail: vi.fn(),
    cancelPresetBatchRun: vi.fn(),
  };
});

vi.mock("@/lib/preset-batch-stream", () => ({
  observePresetBatchRun: vi.fn(),
}));

const mockBatchDetail: testApiClient.PresetBatchRunDetailResponse = {
  id: "batch-abc-123",
  organization_id: "org-1",
  preset_id: "vietnam-1k",
  params: { trips_per_batch: 1, interval_s: 2, driver_ids: ["drv-01"] },
  status: "RUNNING",
  counters: { total: 2, completed: 1, running: 1 },
  created_at: "2026-10-17T00:00:00Z",
  started_at: "2026-10-17T00:00:05Z",
  completed_at: null,
  cancelled_at: null,
  trips: [
    {
      id: "trip-uuid-1",
      batch_id: "batch-abc-123",
      trip_ref: "vn_trip_001",
      order: 0,
      status: "COMPLETED",
      driver_id: "drv-01",
      driver_name: "Tài xế An",
      expected_label: "no_violation",
      predicted_label: "no_violation",
      confidence: 0.92,
      case_id: null,
      run_id: "run-uuid-1",
      error: null,
      created_at: "2026-10-17T00:00:00Z",
      started_at: "2026-10-17T00:00:01Z",
      completed_at: "2026-10-17T00:00:03Z",
      snapshot: {
        driver_name: "Tài xế An",
        conversation: [
          { role: "customer", text: "Tôi đang ở sảnh khách sạn" },
          { role: "driver", text: "Tôi đang đến trong 2 phút" },
        ],
        gps_summary: {
          points: 120,
          mock_location_count: 0,
          max_accuracy_m: 4.5,
          bbox: { min_lat: 21.0, max_lat: 21.05, min_lon: 105.8, max_lon: 105.85 },
        },
        speed_stats: {
          min_mps: 0.0,
          avg_mps: 11.5,
          max_mps: 18.2,
        },
      },
    },
    {
      id: "trip-uuid-2",
      batch_id: "batch-abc-123",
      trip_ref: "vn_trip_002",
      order: 1,
      status: "RUNNING",
      driver_id: "drv-01",
      driver_name: "Tài xế An",
      expected_label: "ERR-01",
      predicted_label: null,
      confidence: null,
      case_id: null,
      run_id: null,
      error: null,
      created_at: "2026-10-17T00:00:00Z",
      started_at: "2026-10-17T00:00:04Z",
      completed_at: null,
      snapshot: {
        driver_name: "Tài xế An",
        conversation: [],
        gps_summary: { points: 50, mock_location_count: 1, max_accuracy_m: 10.0 },
        speed_stats: { min_mps: 0.0, avg_mps: 14.0, max_mps: 22.0 },
      },
    },
  ],
};

describe("PresetBatchLogs component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(testApiClient.fetchPresetBatchRunDetail).mockResolvedValue(mockBatchDetail);
    vi.mocked(testApiClient.cancelPresetBatchRun).mockResolvedValue({
      ...mockBatchDetail,
      status: "CANCELLED",
    });
  });

  it("restores latest batch state from localStorage and displays grouped trips in processing order", async () => {
    localStorage.setItem("preset_latest_batch_vietnam-1k", "batch-abc-123");

    render(<PresetBatchLogs presetId="vietnam-1k" />);

    expect(await screen.findByText("Đợt #batch-ab")).toBeDefined();
    expect(testApiClient.fetchPresetBatchRunDetail).toHaveBeenCalledWith("batch-abc-123");

    // Group rows in processing order
    expect(screen.getByText("vn_trip_001")).toBeDefined();
    expect(screen.getByText("vn_trip_002")).toBeDefined();

    // Verify trip 1 details
    expect(screen.getByText("Kỳ vọng: no_violation")).toBeDefined();
    expect(screen.getByText(/Dự đoán: no_violation/i)).toBeDefined();
    expect(screen.getByText(/(92.0%)/i)).toBeDefined();
    expect(screen.getByText("Classifier: Có")).toBeDefined();
    expect(screen.getAllByText("Tài xế An").length).toBeGreaterThan(0);
  });

  it("expands a trip group to reveal event timeline, conversation history, GPS summary, and speed stats", async () => {
    render(<PresetBatchLogs presetId="vietnam-1k" activeBatchId="batch-abc-123" />);

    await screen.findByText("vn_trip_001");

    // Click to expand trip 1
    const tripHeader = screen.getByTestId("trip-header-vn_trip_001");
    await act(async () => {
      fireEvent.click(tripHeader);
    });

    const details = await screen.findByTestId("trip-details-vn_trip_001");
    expect(details).toBeDefined();

    // Verify conversation
    expect(screen.getByText("Tôi đang ở sảnh khách sạn")).toBeDefined();
    expect(screen.getByText("Tôi đang đến trong 2 phút")).toBeDefined();

    // Verify GPS summary
    expect(screen.getByText("120")).toBeDefined(); // points
    expect(screen.getByText("4.5 m")).toBeDefined(); // accuracy

    // Verify speed stats
    expect(screen.getByText("11.5 m/s")).toBeDefined();
    expect(screen.getByText("18.2 m/s")).toBeDefined();
  });

  it("calls cancelPresetBatchRun when cancel button is clicked", async () => {
    render(<PresetBatchLogs presetId="vietnam-1k" activeBatchId="batch-abc-123" />);

    const cancelBtn = await screen.findByRole("button", { name: /Hủy đợt chạy/i });
    await act(async () => {
      fireEvent.click(cancelBtn);
    });

    expect(testApiClient.cancelPresetBatchRun).toHaveBeenCalledWith("batch-abc-123");
  });

  it("subscribes to SSE stream and applies live events in order", async () => {
    let capturedObserver: batchStream.PresetBatchObserver | undefined;

    vi.mocked(batchStream.observePresetBatchRun).mockImplementation(
      async (_id, _signal, observer) => {
        capturedObserver = observer;
      }
    );

    render(<PresetBatchLogs presetId="vietnam-1k" activeBatchId="batch-abc-123" />);
    await screen.findByText("vn_trip_002");

    expect(capturedObserver).toBeDefined();

    // Emit live SSE event: trip.classifier_received for vn_trip_002
    await act(async () => {
      capturedObserver?.onEvent({
        event_id: "evt-01",
        event_type: "trip.classifier_received",
        batch_id: "batch-abc-123",
        trip_ref: "vn_trip_002",
        reached_classifier: true,
        occurred_at: new Date().toISOString(),
      });
    });

    // Emit live SSE event: trip.classified for vn_trip_002
    await act(async () => {
      capturedObserver?.onEvent({
        event_id: "evt-02",
        event_type: "trip.classified",
        batch_id: "batch-abc-123",
        trip_ref: "vn_trip_002",
        label: "ERR-01",
        confidence: 0.88,
        reached_classifier: true,
        occurred_at: new Date().toISOString(),
      });
    });

    // vn_trip_002 is now COMPLETED with predicted label ERR-01
    expect(await screen.findByText(/Dự đoán: ERR-01/i)).toBeDefined();
    expect(screen.getByText(/(88.0%)/i)).toBeDefined();
  });
});
