import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapsTab } from "@/components/adjudication/maps-tab";

vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: (props: Record<string, unknown>) => (
    <div data-testid="maplibre-view">{String(props.caseId)}</div>
  ),
}));
const localeState = vi.hoisted(() => ({ locale: "en" as "en" | "vi" }));
vi.mock("@/lib/locale", () => ({ useLocale: () => ({ locale: localeState.locale, setLocale: vi.fn() }) }));

const detail = {
  trip: { vehicle_type: "car" },
  candidate_routes: [],
  traffic_corroboration: null,
  timeline_milestones: [],
  missingness_alerts: [],
  route_geometry: null,
  forensic_brief: null,
  preliminary_judgment: null,
} as any;

const props = {
  caseDetail: detail,
  selectedCaseId: "CASE-368",
  mapTelemetry: [],
  isActive: true,
} as any;

describe("MapsTab", () => {
  it("renders the existing map only while active and passes the selected case", () => {
    const { rerender } = render(<MapsTab {...props} />);
    expect(screen.getByTestId("maplibre-view")).toBeInTheDocument();
    expect(screen.getByText("CASE-368")).toBeInTheDocument();
    rerender(<MapsTab {...props} isActive={false} />);
    expect(screen.queryByTestId("maplibre-view")).not.toBeInTheDocument();
  });

  it("labels missing corroboration with the designed empty state and never exposes an AI verdict", () => {
    render(<MapsTab {...props} />);
    expect(screen.getAllByText("No data yet").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^Unavailable$|undefined/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/agent violation detection|confidence|probability|risk score|classification/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/AI Agent|fraud score/i);
  });

  it("keeps factual traffic, sensor, and stall fields without inventing defaults", () => {
    render(<MapsTab {...props} caseDetail={{ ...detail, traffic_corroboration: {
      road_segment: "Segment 7", public_service: { average_speed_kmh: 21, congestion: "slow", provider: "TomTom" },
      peer_drivers: [{ vehicle_plate: "A-1", speed_kmh: 19 }],
    } } as any} mapTelemetry={[{ gps_accuracy_m: 4, mock_location_detected: false, ping_latency_ms: 80, battery_level_pct: 63, stall_duration_s: 12, davi_score: 0.4, drift_distance_m: 8 }]} />);
    fireEvent.click(screen.getByRole("button", { name: /platform and sensor reliability/i }));
    fireEvent.click(screen.getByRole("button", { name: /stall and drift telemetry/i }));
    expect(screen.getByText("Segment 7")).toBeInTheDocument();
    expect(screen.getByText(/21 km\/h/)).toBeInTheDocument();
    expect(screen.getByText("TomTom")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "GPS accuracy: 4 m" })).toHaveAttribute("title", "Observed GPS accuracy");
    expect(screen.getByText(/12s/)).toBeInTheDocument();
    expect(screen.queryByText(/35|50|92\.5|synthetic/i)).not.toBeInTheDocument();
  });

  it("groups Maps details into icon-left metric cards laid out by MetricGrid", () => {
    const { container } = render(<MapsTab {...props} caseDetail={{ ...detail, traffic_corroboration: {
      road_segment: "Segment 7", public_service: { average_speed_kmh: 21, congestion: "slow", provider: "TomTom" },
      peer_drivers: [{ vehicle_plate: "A-1", speed_kmh: 19 }],
    } } as any} mapTelemetry={[{ gps_accuracy_m: 4, mock_location_detected: false, ping_latency_ms: 80, battery_level_pct: 63, stall_duration_s: 12, davi_score: 0.4, drift_distance_m: 8 }]} />);
    fireEvent.click(screen.getByRole("button", { name: /platform and sensor reliability/i }));
    fireEvent.click(screen.getByRole("button", { name: /stall and drift telemetry/i }));
    const cards = [...container.querySelectorAll("[data-span] > [role=group]")];
    expect(cards.length).toBeGreaterThanOrEqual(14);
    expect(cards.every(card => card.firstElementChild?.querySelector("svg"))).toBe(true);
    expect(container.querySelectorAll(".material-symbols-outlined")).toHaveLength(0);
  });

  it("translates headings and missing states to Vietnamese", () => {
    localeState.locale = "vi";
    render(<MapsTab {...props} />);
    expect(screen.getByText("Đối soát giao thông")).toBeInTheDocument();
    expect(screen.getByText("Telemetry dừng và lệch tuyến")).toBeInTheDocument();
    localeState.locale = "en";
  });

  it("shows the compact trip strip with prominent fare and truncated copyable trip id", () => {
    render(<MapsTab {...props} caseDetail={{ ...detail, trip: {
      vehicle_type: "car", id: "TRIP-1234567890ABCDEF",
      pickup_address: "Hồ Hoàn Kiếm", dropoff_address: "Nội Bài",
      fare_amount_vnd: 50000, driver_status: "active", match_type: "now",
    } } as any} />);
    expect(screen.getByText("50,000 ₫")).toBeVisible();
    expect(screen.queryByText(/Driver start|Vị trí đầu/)).not.toBeInTheDocument();
    const copy = screen.getByRole("button", { name: "Trip ID: TRIP-1234567890ABCDEF" });
    expect(copy).toHaveTextContent("TRIP-123…CDEF");
    expect(copy).not.toHaveTextContent("TRIP-1234567890ABCDEF");
  });
});
