import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import SimulationCockpitPage from "../app/test/page";

// Mock Clerk — test pages must not require ClerkProvider in unit tests
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => null, isLoaded: true, isSignedIn: true, orgId: "org-a" }),
  UserButton: () => <div data-testid="user-button" />,
  ClerkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock testApiClient so no real fetch is fired in tests
vi.mock("@/lib/testApiClient", () => ({
  setTestApiTokenProvider: vi.fn(),
  fetchTestCases: vi.fn().mockResolvedValue([]),
  fetchTestSamples: vi.fn().mockResolvedValue([]),
  triageCase: vi.fn(),
  postTest: vi.fn(async () => ({ id: "run-abc123456", total_steps: 30, title: "Chuyến thử" })),
  streamTest: vi.fn(async () => ({
    body: {
      getReader: () => ({
        read: async () => ({ done: true as const, value: undefined }),
      }),
    },
  })),
  searchGeocode: vi.fn().mockResolvedValue([]),
  resolveTestRoute: vi.fn().mockResolvedValue({
    route_geometry: {
      type: "LineString",
      coordinates: [
        [105.8524, 21.0285],
        [105.8497, 21.0118],
        [105.8342, 21.0345],
      ],
    },
    pickup_route: {
      coordinates: [
        [105.8524, 21.0285],
        [105.8497, 21.0118],
      ],
      distance_m: 2500,
      duration_s: 300,
      provider: "osrm",
    },
    destination_route: {
      coordinates: [
        [105.8497, 21.0118],
        [105.8342, 21.0345],
      ],
      distance_m: 3000,
      duration_s: 400,
      provider: "osrm",
    },
    provider: "osrm",
  }),
  publishSimulationToProduction: vi.fn().mockResolvedValue({
    status: "published",
    run_id: "run-abc123456",
    trip_id: "trip-1",
    case_id: "case-sim-1",
    destination: "/workplace?caseId=case-sim-1",
  }),
  fetchTestRuns: vi.fn().mockResolvedValue([]),
  fetchTestRunOverview: vi.fn().mockResolvedValue(null),
  fetchRunTrace: vi.fn().mockResolvedValue([]),
  updateTestRunTitle: vi.fn(async (_id: string, title: string) => ({ id: "run-abc123456", title })),
  controlTestRun: vi.fn(),
  cancelTestRun: vi.fn(),
  fetchTestPresets: vi.fn().mockResolvedValue({ presets: [], source: {} }),
  fetchTestActors: vi.fn().mockResolvedValue({ drivers: [{ id: "drv-sim-001", display_name: "Driver" }], passengers: [{ id: "pass-sim-001", display_name: "Passenger" }], vehicles: [{ id: "veh-sim-001", display_name: "Vehicle" }], policies: [{ id: "pol-sim-001", display_name: "Policy" }] }),
  searchClerkDrivers: vi.fn().mockResolvedValue([
    {
      driver_id: "drv-sim-001",
      display_name: "Driver 001",
      email: "driver001@example.com",
      principal_id: "principal-001",
      vehicle_id: null,
      license_plate: "30A-12345",
    },
  ]),
  fetchClerkLinkedDrivers: vi.fn().mockResolvedValue([
    {
      driver_id: "drv-sim-001",
      display_name: "Driver 001",
      email: "driver001@example.com",
      principal_id: "principal-001",
      vehicle_id: null,
      license_plate: "30A-12345",
    },
  ]),
}));

// Mock MapLibreView — requires browser canvas; capture props for honesty assertions
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: (props: { showKinematicFooter?: boolean }) => (
    <div
      data-testid="maplibre-view"
      data-show-kinematic-footer={String(props.showKinematicFooter)}
    />
  ),
}));

describe("Test console honesty regressions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("initial driver/passenger dialogue is neutral, never claims Hanoi CBD origin", async () => {
    render(<SimulationCockpitPage />);

    // Must never pre-claim a location before telemetry arrives
    expect(
      screen.queryByText(/Standing by at Hanoi CBD origin/i)
    ).toBeNull();
    expect(screen.queryByText(/Hanoi CBD origin/i)).toBeNull();
  });

  it("reset returns dialogue to the same neutral text", async () => {
    render(<SimulationCockpitPage />);

    // Drive to a non-IDLE state so the Reset button appears
    const startBtn = screen.getByRole("button", { name: /Chạy mô phỏng/i });
    await waitFor(() => expect(startBtn).not.toBeDisabled());

    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver 001");
    fireEvent.click(driverOption);

    await screen.findByRole("option", { name: "Passenger" });
    fireEvent.change(screen.getByLabelText("Khách"), { target: { value: "pass-sim-001" } });
    fireEvent.change(screen.getByLabelText("Xe"), { target: { value: "veh-sim-001" } });
    fireEvent.change(screen.getByLabelText("Chính sách"), { target: { value: "pol-sim-001" } });
    fireEvent.click(startBtn);

    const resetBtn = await screen.findByRole("button", { name: /Làm lại/i });
    fireEvent.click(resetBtn);

    await waitFor(() => {
      expect(
        screen.queryByText(/Standing by at Hanoi CBD origin/i)
      ).toBeNull();
    });
  });

  it("has no fake Trigger Dynamic Reroute button", async () => {
    render(<SimulationCockpitPage />);

    // Fake action must not exist
    expect(screen.queryByText(/Trigger Dynamic Reroute/i)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Trigger Dynamic Reroute/i })
    ).toBeNull();
  });

  it("hides kinematic footer on test console (showKinematicFooter=false, no ribbon duplicates)", async () => {
    render(<SimulationCockpitPage />);

    const mapView = await screen.findByTestId("maplibre-view");
    expect(
      mapView.getAttribute("data-show-kinematic-footer")
    ).toBe("false");

    // Rendered output must not contain footer ribbon duplicates
    expect(screen.queryByTestId("ambient-traffic-status")).toBeNull();
    expect(screen.queryByText(/Stall point:/i)).toBeNull();
    expect(screen.queryByText(/DAVI drift:/i)).toBeNull();
  });

  it("map loading overlay is neutral and never mentions satellite", async () => {
    // Bypass the file-level MapLibreView mock to exercise the real overlay
    const actual = await vi.importActual<
      typeof import("@/components/map/maplibre-view")
    >("@/components/map/maplibre-view");
    const RealMapLibreView = actual.MapLibreView;

    // Force the WebGL branch synchronously so the loading overlay renders.
    // jsdom has no WebGLRenderingContext; stub it + canvas getContext.
    const w = window as unknown as Record<string, unknown>;
    const prevWebGL = w.WebGLRenderingContext;
    const proto = HTMLCanvasElement.prototype as unknown as Record<
      string,
      unknown
    >;
    const prevGetContext = proto.getContext;
    w.WebGLRenderingContext = function () {};
    proto.getContext = () => ({}) as unknown as RenderingContext;

    try {
      const view = render(<RealMapLibreView />);
      const overlay = view.getByTestId("map-loading-overlay");
      expect(overlay.textContent).toMatch(/Loading map…/);
      expect(overlay.textContent).not.toMatch(/vệ tinh/i);
      view.unmount();
    } finally {
      if (prevWebGL === undefined) delete w.WebGLRenderingContext;
      else w.WebGLRenderingContext = prevWebGL;
      proto.getContext = prevGetContext as typeof HTMLCanvasElement.prototype.getContext;
    }
  });

  it("refreshes run trace after publishSimulationToProduction completes", async () => {
    const { fetchRunTrace, streamTest } = await import("@/lib/testApiClient");
    const payload = `data: ${JSON.stringify({ event_type: "run.completed", step_index: 30 })}\n\n`;
    vi.mocked(streamTest).mockImplementationOnce(async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode(payload)); controller.close(); },
    })));

    render(<SimulationCockpitPage />);

    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver 001");
    fireEvent.click(driverOption);
    await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(3));
    const actorSelects = screen.getAllByRole("combobox");
    ["pass-sim-001", "veh-sim-001", "pol-sim-001"].forEach((val, i) =>
      fireEvent.change(actorSelects[i], { target: { value: val } })
    );

    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    const publishBtn = await screen.findByRole("button", { name: /Hoàn tất & gửi chuyến/i });
    await waitFor(() => expect(publishBtn).not.toBeDisabled());

    vi.mocked(fetchRunTrace).mockClear();

    fireEvent.click(publishBtn);

    await waitFor(() => {
      expect(fetchRunTrace).toHaveBeenCalledWith("run-abc123456");
    });
  });
});
