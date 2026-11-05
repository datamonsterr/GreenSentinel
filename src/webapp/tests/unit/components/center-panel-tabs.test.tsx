import { describe, it, expect, vi } from "vitest";
import { committedJudgment } from '../../fixtures/staged-adjudication';
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { CenterPanelTabs, type CenterTabType } from "@/components/adjudication/center-panel-tabs";
import { MapsTab } from "@/components/adjudication/maps-tab";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { WorkflowTab } from "@/components/adjudication/workflow-tab";

const mapMock = vi.hoisted(() => ({ mounts: 0, updates: 0 }));

// Mock MapLibreView to prevent webgl context errors in headless tests
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: (props: { caseId?: string }) => {
    React.useEffect(() => { mapMock.mounts += 1; }, []);
    React.useEffect(() => { mapMock.updates += 1; }, [props.caseId]);
    return <div data-testid="mock-maplibre-view" data-case-id={props.caseId}>MapLibre GIS Map</div>;
  },
}));

describe("CenterPanelTabs Navigation", () => {
  it("renders 6 view tabs with proper labels, no badge tags, and accessible roles", () => {
    const handleTabChange = vi.fn();
    render(
      <CenterPanelTabs
        activeTab="overview"
        onTabChange={handleTabChange}
      />
    );

    const tablist = screen.getByRole("tablist", { name: "Case views" });
    expect(tablist).toBeInTheDocument();

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    const mapsTab = screen.getByRole("tab", { name: "Maps" });
    const customerTab = screen.getByRole("tab", { name: "Customer" });
    const driverTab = screen.getByRole("tab", { name: "Driver" });
    const finalizationTab = screen.getByRole("tab", { name: "Complete" });

    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    for (const tab of [mapsTab, customerTab, driverTab, finalizationTab]) {
      expect(tab).toHaveAttribute("aria-selected", "false");
    }

    // Verify badges (evidence, turns, dossier) are completely removed
    expect(screen.queryByText(/evidence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/turns/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/dossier/i)).not.toBeInTheDocument();

    for (const [tab, id] of [[mapsTab, "maps"], [customerTab, "customer"], [driverTab, "driver"], [finalizationTab, "finalization"]] as const) {
      fireEvent.click(tab);
      expect(handleTabChange).toHaveBeenCalledWith(id);
    }
  });

  it("moves focus and selection through all tabs with arrows, wraparound, Home and End", () => {
    const handleTabChange = vi.fn();
    function ControlledTabs() {
      const [activeTab, setActiveTab] = React.useState<CenterTabType>('overview');
      return <CenterPanelTabs activeTab={activeTab} onTabChange={(tab) => { handleTabChange(tab); setActiveTab(tab); }} />;
    }
    render(<ControlledTabs />);
    const tabs = screen.getAllByRole('tab');
    tabs[0].focus();
    for (const [key, index, id] of [
      ['ArrowRight', 1, 'maps'], ['ArrowRight', 2, 'customer'],
      ['ArrowRight', 3, 'driver'], ['ArrowRight', 4, 'finalization'], ['ArrowRight', 0, 'overview'],
      ['ArrowLeft', 4, 'finalization'], ['Home', 0, 'overview'], ['End', 4, 'finalization'],
    ] as const) {
      fireEvent.keyDown(document.activeElement!, { key });
      expect(handleTabChange).toHaveBeenLastCalledWith(id);
      expect(tabs[index]).toHaveFocus();
      expect(tabs[index]).toHaveAttribute('aria-selected', 'true');
      expect(tabs[index]).toHaveAttribute('tabindex', '0');
      for (const other of tabs.filter((tab) => tab !== tabs[index])) {
        expect(other).toHaveAttribute('aria-selected', 'false');
        expect(other).toHaveAttribute('tabindex', '-1');
      }
    }
    handleTabChange.mockClear();
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(handleTabChange).not.toHaveBeenCalled();
  });
});

describe("MapsTab — GIS evidence and telemetry hub", () => {
  const mockCaseDetail: any = {
    preliminary_judgment: committedJudgment('case-001', 'analyst-001'),
    case: { id: "case-001", version: 1 },
    trip: { vehicle_type: "VF e34", past_warnings: 2 },
    telemetry_samples: [
      { davi_score: 0.82, mock_location_reported: false, gps_accuracy_m: 4.2 },
    ],
    features: { stall_duration_s: 420 },
    traffic_corroboration: {
      road_segment: "Hành lang Nguyễn Trãi - Khuất Duy Tiến",
      public_service: { average_speed_kmh: 32.0, congestion: "clear" },
      peer_drivers: [{ driver_id: "drv-2", vehicle_plate: "29A-111", speed_kmh: 31 }],
    },
  };

  it("renders the map and actual traffic, sensor, stall, and DAVI evidence", () => {
    render(
      <MapsTab
        caseDetail={mockCaseDetail}
        selectedCaseId="case-001"
        pickupLocation={{ latitude: 21.0, longitude: 105.8 }}
        initialDriverLocation={{ latitude: 21.01, longitude: 105.81 }}
        destinationLocation={{ latitude: 21.05, longitude: 105.85 }}
        mapTelemetry={mockCaseDetail.telemetry_samples}
      />
    );

    expect(screen.getByTestId("mock-maplibre-view")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Traffic corroboration" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Hành lang Nguyễn Trãi - Khuất Duy Tiến")).toBeInTheDocument();
    expect(screen.getByText("32 km/h")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Platform and Sensor Reliability" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Stall and Drift Telemetry" })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps GIS map mounted when selected case changes", () => {
    mapMock.mounts = 0;
    mapMock.updates = 0;
    const { rerender } = render(<MapsTab caseDetail={mockCaseDetail} selectedCaseId="case-001" mapTelemetry={[]} />);
    const initialMap = screen.getByTestId("mock-maplibre-view");
    rerender(<MapsTab caseDetail={mockCaseDetail} selectedCaseId="case-002" mapTelemetry={[]} />);
    expect(mapMock.mounts).toBe(1);
    expect(mapMock.updates).toBe(2);
    expect(screen.getByTestId("mock-maplibre-view")).toBe(initialMap);
    expect(screen.getByTestId("mock-maplibre-view")).toHaveAttribute("data-case-id", "case-002");
  });

  it("expands detailed probe diagram and speed comparison chart in traffic assessment toggle", () => {
    render(
      <MapsTab
        caseDetail={mockCaseDetail}
        selectedCaseId="case-001"
        pickupLocation={{ latitude: 21.0, longitude: 105.8 }}
        initialDriverLocation={{ latitude: 21.01, longitude: 105.81 }}
        destinationLocation={{ latitude: 21.05, longitude: 105.85 }}
        mapTelemetry={mockCaseDetail.telemetry_samples}
      />
    );

    const trafficToggle = screen.getByRole("button", { name: "Traffic corroboration" });
    expect(trafficToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Hành lang Nguyễn Trãi - Khuất Duy Tiến")).toBeInTheDocument();
    fireEvent.click(trafficToggle);
    expect(trafficToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Hành lang Nguyễn Trãi - Khuất Duy Tiến")).not.toBeInTheDocument();
  });

  it("expands sensor health multi-channel chart in sensor reliability toggle", () => {
    render(
      <MapsTab
        caseDetail={mockCaseDetail}
        selectedCaseId="case-001"
        pickupLocation={{ latitude: 21.0, longitude: 105.8 }}
        initialDriverLocation={{ latitude: 21.01, longitude: 105.81 }}
        destinationLocation={{ latitude: 21.05, longitude: 105.85 }}
        mapTelemetry={mockCaseDetail.telemetry_samples}
      />
    );

    const sensorToggle = screen.getByRole("button", { name: "Platform and Sensor Reliability" });
    expect(sensorToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(sensorToggle);
    expect(sensorToggle).toHaveAttribute("aria-expanded", "true");

    expect(screen.getByRole("group", { name: "GPS accuracy: 4.2 m" })).toHaveAttribute("title", "Observed GPS accuracy");
    expect(screen.getByText("4.2 m")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Mock location: No data yet" })).toBeInTheDocument();
  });

  it("renders non-invented missing evidence state (N/A) when telemetry and features are absent", () => {
    const emptyCaseDetail: any = {
      case: { id: "case-empty", version: 1 },
      trip: { vehicle_type: "VF e34" },
      telemetry_samples: [],
      features: {},
    };

    render(
      <MapsTab
        caseDetail={emptyCaseDetail}
        selectedCaseId="case-empty"
        pickupLocation={{ latitude: 21.0, longitude: 105.8 }}
        initialDriverLocation={{ latitude: 21.01, longitude: 105.81 }}
        destinationLocation={{ latitude: 21.05, longitude: 105.85 }}
        mapTelemetry={[]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Stall and Drift Telemetry" }));
    expect(screen.getByRole("group", { name: "Stall duration: No data yet" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "DAVI: No data yet" })).toBeInTheDocument();
    expect(screen.getAllByText("No data yet").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/Unavailable|undefined/)).not.toBeInTheDocument();
  });
});

describe("ConversationTab — Dialogue & Conflicting Dispositions", () => {
  const mockCaseDetail: any = {
    case: { id: "case-002" },
    trip: {
      driver_statement: "Kẹt xe hầm chui Kim Mã hơn 25 phút",
      passenger_statement: "Lái xe không di chuyển quá 5 phút tại đường vành đai",
    },
    conversation: [
      { role: "driver", text: "Tôi đang bị kẹt xe", occurred_at: "2026-09-26T08:00:00Z" },
    ],
  };

  const mockDispute: any = {
    dispute_status: "in_dispute",
    recommended_action: "Review",
    driver_statement: "Kẹt xe hầm chui Kim Mã hơn 25 phút",
    claim_type: "traffic_gridlock",
    traffic_corroboration: { ratio: 2.5, observed_speed: 6.2 },
    precedent_score: 0.88,
    transcript: [
      { role: "driver", text: "Tôi đang cố gắng nhích từng mét", timestamp: "2026-09-26T08:01:00Z" },
    ],
  };

  it("renders customer statements as a read-only evidence panel without driver statement in customer card", () => {
    render(
      <ConversationTab
        caseDetail={mockCaseDetail}
        disputeDossier={mockDispute}
      />
    );

    expect(screen.getByText("Customer")).toBeInTheDocument();
    expect(screen.getByTitle(/Customer statement:/)).toBeInTheDocument();
    expect(screen.queryByTitle(/Driver statement:/)).not.toBeInTheDocument();
    expect(screen.getByText("Lái xe không di chuyển quá 5 phút tại đường vành đai")).toBeInTheDocument();
    expect(screen.queryByLabelText("Request inquiry")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request inquiry" })).not.toBeInTheDocument();
  });
});

describe("WorkflowTab — Case Workflow Synthesis & LangGraph Trace", () => {
  const mockCaseDetail: any = {
    case: {
      id: "case-002",
      workflow_trace: {
        agent_tools_called: [
          { tool_name: "query_corridor_speed", status: "success", output_summary: "Tốc độ hành lang 32km/h" },
        ],
        related_policies: [
          { policy_code: "POL-04", clause: "Art 12.1", rationale: "Miễn trừ kẹt xe hành lang" },
        ],
        final_decision: {
          verdict: "disagree",
          decided_by: "AI Supervisor",
          rationale: "Dữ liệu đối soát OSRM xác nhận kẹt xe diện rộng",
        },
      },
    },
  };

  it("renders a local draft and only recorded workflow timeline and tools", () => {
    render(<WorkflowTab caseDetail={mockCaseDetail} />);

    expect(screen.getByRole("region", { name: "Workflow" })).toBeInTheDocument();
    expect(screen.getByText("Local draft — not saved")).toBeInTheDocument();
    expect(screen.getByLabelText("Workflow draft")).toBeInTheDocument();
    expect(screen.getByText("No recorded workflow events.")).toBeInTheDocument();
    expect(screen.queryByText(/FINAL VERDICT|Precedent Bank|LangGraph State/i)).not.toBeInTheDocument();
  });
});

describe("DriverInfoTab — Dossier & History Scorecard (live, issue #100)", () => {
  const mockCaseDetail: any = {
    case: { id: "case-003", driver_id: "DRV-84920" },
    trip: {
      driver_id: "DRV-84920",
      driver_name: "Nguyễn Văn Hùng",
      vehicle_plate: "30A-992.81",
      vehicle_type: "VF e34",
      rating: 4.82,
      acceptance_rate: 94,
      cancellation_rate: 4.2,
      total_trips: 1420,
      past_warnings: 2,
    },
  };

  const liveScorecard: any = {
    driver_id: "DRV-84920",
    violation_ratio_90d: 3.8,
    benchmark_violation_ratio: 5.0,
    fined_ratio: 50.0,
    repeat_offense_risk_score: 78,
    tenure_months: 16,
    past_incidents: [
      {
        trip_id: "TR-9123",
        occurred_at: "2026-09-21 08:35",
        violation_type: "Hành trình bất thường (DAVI Drift)",
        investigation_finding: "Độ lệch tuyến 2.1km do công trình hầm chui",
        action_taken: "Miễn trừ xử phạt (Exonerated)",
        status: "exonerated",
      },
      {
        trip_id: "TR-8455",
        occurred_at: "2026-09-02 17:15",
        violation_type: "Thời gian dừng chờ vượt ngưỡng (Stall 480s)",
        investigation_finding: "Dừng đón khách sai điểm định vị, không thông báo",
        action_taken: "Cảnh cáo & Khấu trừ 50k VND",
        status: "penalized",
      },
    ],
  };

  it("renders history KPI cards and past incident table alongside driver profile", () => {
    render(
      <DriverInfoTab
        caseDetail={mockCaseDetail}
        activeCase={{ driver_id: "DRV-84920", driver_name: "Nguyễn Văn Hùng" } as any}
        scorecard={liveScorecard}
      />
    );

    expect(screen.getByText(/Nguyễn Văn Hùng/)).toBeInTheDocument();
    expect(screen.getByText(/30A-992\.81/)).toBeInTheDocument();
    expect(screen.getByTitle("90-day violation ratio")).toBeInTheDocument();
    expect(screen.getByTitle("Fined ratio")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Repeat-offense risk" })).toBeInTheDocument();
    expect(screen.getByText("3.8%")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByTitle("Repeat-offense risk")).toHaveTextContent("78 / 100");
    expect(screen.getByText(/TR-9123/)).toBeInTheDocument();
  });

  it("renders empty state without broken layout when past_incidents is empty", () => {
    render(<DriverInfoTab caseDetail={mockCaseDetail} scorecard={{ ...liveScorecard, past_incidents: [] }} />);

    expect(screen.getByText("No past incidents recorded.")).toBeInTheDocument();
    expect(screen.queryByText("TR-9123")).not.toBeInTheDocument();
    expect(screen.getByTitle("90-day violation ratio")).toBeInTheDocument();
  });

  it("shows loading skeleton while fetching the live scorecard", () => {
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => undefined));
    render(<DriverInfoTab caseDetail={mockCaseDetail} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("fetches the live scorecard via the case alias route and renders KPIs", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => liveScorecard,
    });
    render(<DriverInfoTab caseDetail={mockCaseDetail} />);

    expect(await screen.findByRole("button", { name: "Trip ID: TR-9123" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/cases/case-003/driver-scorecard"),
      expect.anything()
    );
    vi.restoreAllMocks();
  });

  it("renders error state when the live scorecard request fails", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({ detail: "Scorecard database unavailable" }),
    });
    render(<DriverInfoTab caseDetail={mockCaseDetail} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Driver history unavailable.");
    vi.restoreAllMocks();
  });
});

describe("WorkflowTab — DB timeline ribbon (issue #100)", () => {
  const mockCaseDetail: any = { case: { id: "case-003" } };

  it("renders DB timeline events when workflow.timeline is populated", () => {
    render(
      <WorkflowTab
        caseDetail={mockCaseDetail}
        caseWorkflowTrace={
          {
            agent_tools_called: [],
            human_actions_performed: [],
            driver_response_summary: "",
            related_policies: [],
            timeline: [
              { event_type: "dispatched", occurred_at: "2026-10-01T14:20:00Z", label: "Điều phối" },
              { event_type: "driver_arriving", occurred_at: "2026-10-01T14:22:15Z", label: "Di chuyển đón" },
            ],
          } as any
        }
      />
    );

    expect(screen.getByText("2026-10-01T14:20:00Z")).toBeInTheDocument();
    expect(screen.getByText("2026-10-01T14:22:15Z")).toBeInTheDocument();
    expect(screen.queryByText("14:20:00")).not.toBeInTheDocument();
  });

  it("falls back to the static ribbon when timeline is empty", () => {
    render(<WorkflowTab caseDetail={mockCaseDetail} caseWorkflowTrace={null} />);

    expect(screen.getByText("No recorded workflow events.")).toBeInTheDocument();
    expect(screen.getByText("Local draft — not saved")).toBeInTheDocument();
  });
});
