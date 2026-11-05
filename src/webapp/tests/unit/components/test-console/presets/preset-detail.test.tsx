import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PresetDetail } from "@/components/test-console/presets/PresetDetail";
import * as testApiClient from "@/lib/testApiClient";

vi.mock("@/lib/testApiClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/testApiClient")>("@/lib/testApiClient");
  return {
    ...actual,
    fetchTestPresetDetail: vi.fn(),
    fetchClerkLinkedDrivers: vi.fn().mockResolvedValue([]),
    fetchPresetBatchRunDetail: vi.fn().mockResolvedValue({
      id: "batch-1",
      organization_id: "org-1",
      preset_id: "preset-vietnam",
      params: {},
      status: "COMPLETED",
      counters: { total: 1, completed: 1 },
      created_at: new Date().toISOString(),
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      trips: [],
    }),
  };
});

const mockDetail: testApiClient.TestPresetDetailResponse = {
  id: "preset-vietnam",
  title: "Tập dữ liệu đường bộ Việt Nam",
  description: "Dữ liệu 1000 chuyến đường bộ tại Việt Nam",
  kind: "vietnam",
  available: true,
  unavailable_reason: null,
  source_label: "vietnam_road",
  selection_size: 1000,
  available_trips: 1000,
  trip_count: 1000,
  source_release: "synthesized_vietnam_trip",
  revision: "rev-vn-001",
  trips_sha256: "hash-sha256-abc12345",
  license: "ODbL (OpenStreetMap contributors)",
  metadata: { version: "1.0.0" },
  metrics: { accuracy_target: 0.95 },
  distributions: {
    total_records: 1000,
    by_label: {
      fraud: 300,
      no_violation: 650,
      insufficient_evidence: 50,
      grouped: { fraud: 300, no_violation: 650, insufficient_evidence: 50 },
      per_code: { "ERR-01": 150, "ERR-02": 150 },
    },
    per_code: { "ERR-01": 150, "ERR-02": 150 },
    by_severity: { P1: 200, P2: 100, none: 700 },
    by_scenario: { deviation: 300, normal: 700 },
    by_city: { "Hà Nội": 700, "Đà Nẵng": 300 },
    by_cancellation_actor: { none: 900, driver: 70, passenger: 30 },
  },
  sample_trips: [
    {
      trip_ref: "vn_trip_001",
      label: "no_violation",
      severity: "none",
      scenario: "normal",
      city: "Hà Nội",
      driver_display_name: "Nguyễn Văn A",
      license_plate: "29A-123.45",
      pickup_name: "Hồ Gươm",
      dropoff_name: "Keangnam",
      distance_m: 8500,
      duration_s: 1200,
      telemetry_points: 150,
      cancellation_actor: null,
      cancellation_reason: null,
      source: null,
    },
  ],
};

describe("PresetDetail component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(testApiClient.fetchTestPresetDetail).mockResolvedValue(mockDetail);
  });

  it("renders Info tab with description, source, revision, hash, license, and trip count", async () => {
    render(<PresetDetail presetId="preset-vietnam" onOpenInManual={vi.fn()} />);

    expect(await screen.findByText("Tập dữ liệu đường bộ Việt Nam")).toBeDefined();
    expect(screen.getByText("synthesized_vietnam_trip")).toBeDefined();
    expect(screen.getByText("rev-vn-001")).toBeDefined();
    expect(screen.getByText("hash-sha256-abc12345")).toBeDefined();
    expect(screen.getByText("ODbL (OpenStreetMap contributors)")).toBeDefined();
    expect(screen.getByText("1000 chuyến")).toBeDefined();
  });

  it("renders Samples tab with table and explicit 'Mở trong bảng thủ công' secondary button", async () => {
    const onOpenInManual = vi.fn();
    render(<PresetDetail presetId="preset-vietnam" onOpenInManual={onOpenInManual} />);

    await screen.findByText("Tập dữ liệu đường bộ Việt Nam");

    // Click Samples tab trigger
    const samplesTabTrigger = screen.getByTestId("tab-trigger-samples");
    await act(async () => {
      fireEvent.click(samplesTabTrigger);
    });

    expect(await screen.findByText("vn_trip_001")).toBeDefined();
    expect(screen.getByText("Nguyễn Văn A")).toBeDefined();
    expect(screen.getByText("29A-123.45")).toBeDefined();
    expect(screen.getByText("Hồ Gươm → Keangnam")).toBeDefined();
    expect(screen.getByText("8.50 km · 20 phút")).toBeDefined();

    // Click secondary action "Mở trong bảng thủ công"
    const openManualBtn = screen.getByTestId("open-manual-vn_trip_001");
    await act(async () => {
      fireEvent.click(openManualBtn);
    });

    expect(onOpenInManual).toHaveBeenCalledWith(
      expect.objectContaining({ id: "preset-vietnam" }),
      expect.objectContaining({ trip_ref: "vn_trip_001" })
    );
  });

  it("renders Distribution tab with count pills, ERR codes, severity, scenario, city, cancellation actor", async () => {
    render(<PresetDetail presetId="preset-vietnam" onOpenInManual={vi.fn()} />);

    await screen.findByText("Tập dữ liệu đường bộ Việt Nam");

    // Click Distribution tab trigger
    const distTabTrigger = screen.getByTestId("tab-trigger-distribution");
    await act(async () => {
      fireEvent.click(distTabTrigger);
    });

    // Check high-level count pills
    expect(await screen.findByText(/Gian lận: 300/i)).toBeDefined();
    expect(screen.getByText(/Không vi phạm: 650/i)).toBeDefined();
    expect(screen.getByText(/Thiếu bằng chứng: 50/i)).toBeDefined();

    // Check ERR codes
    expect(screen.getByText("ERR-01")).toBeDefined();
    expect(screen.getByText("ERR-02")).toBeDefined();

    // Check Severity section
    expect(screen.getByText("P1:")).toBeDefined();

    // Check Scenario section (initially collapsed, click to expand)
    const scenarioSectionToggle = screen.getByText("Kịch bản phát sinh (Scenario)");
    await act(async () => {
      fireEvent.click(scenarioSectionToggle);
    });
    expect(screen.getByText("deviation:")).toBeDefined();

    // Check City section
    const citySectionToggle = screen.getByText("Khu vực địa lý (City)");
    await act(async () => {
      fireEvent.click(citySectionToggle);
    });
    expect(screen.getByText("Hà Nội:")).toBeDefined();
  });
});
