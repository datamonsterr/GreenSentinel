import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import SimulationCockpitPage from "../app/test/page";
import TestWorkplacePage from "../app/test/workplace/page";
import type { RouteResolveResponse } from "@/lib/testApiClient";

const authScope = vi.hoisted(() => ({ orgId: "org-a" }));

// Mock Clerk — test pages must not require ClerkProvider in unit tests
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => null, isLoaded: true, isSignedIn: true, orgId: authScope.orgId }),
  UserButton: () => <div data-testid="user-button" />,
  ClerkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const { routeResponse } = vi.hoisted(() => ({
  routeResponse: {
    route_geometry: {
      type: "LineString",
      coordinates: [
        [105.8524, 21.0285],
        [105.8497, 21.0118],
        [105.7838, 21.0173],
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
        [105.7838, 21.0173],
      ],
      distance_m: 6000,
      duration_s: 900,
      provider: "osrm",
    },
    provider: "osrm",
  } as RouteResolveResponse,
}));

vi.mock("@/lib/testApiClient", () => ({
  setTestApiTokenProvider: vi.fn(),
  fetchTestCases: vi.fn().mockResolvedValue([]),
  fetchTestSamples: vi.fn().mockResolvedValue([]),
  triageCase: vi.fn(),
  postTest: vi.fn(async () => ({ id: "run-1", total_steps: 30, title: "Chuyến thử" })),
  streamTest: vi.fn(async () => ({
    body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
  })),
  searchGeocode: vi.fn().mockResolvedValue([
    { formatted: "Hồ Hoàn Kiếm, Hà Nội", lat: 21.0285, lon: 105.8524, address_line1: "Hồ Hoàn Kiếm", city: "Hà Nội" },
    { formatted: "Keangnam Landmark 72, Hà Nội", lat: 21.0173, lon: 105.7838, address_line1: "Keangnam", city: "Hà Nội" },
  ]),
  resolveTestRoute: vi.fn().mockResolvedValue(routeResponse),
  publishSimulationToProduction: vi.fn().mockResolvedValue({
    status: "published",
    run_id: "run-1",
    trip_id: "trip-1",
    case_id: "case-sim-1",
    destination: "/workplace?caseId=case-sim-1",
  }),
  fetchTestRuns: vi.fn().mockResolvedValue([
    {
      id: "run-1",
      title: "Chuyến đêm Hà Nội",
      status: "COMPLETED",
      trip_id: "trip-1",
      created_at: "2026-10-14T10:00:00Z",
      completed_at: "2026-10-14T10:10:00Z",
      cancellation_actor: null,
      cancellation_reason: null,
    },
  ]),
  fetchTestRunOverview: vi.fn().mockResolvedValue({
    run_id: "run-1",
    status: "COMPLETED",
    trips_input: 1,
    trips_processed: 1,
    trips_classified: 1,
    classification_counts: { "ERR-05": 1 },
    stages: [
      { key: "input", label: "Trips input", count: 1, state: "done" },
      { key: "models", label: "Trips through models", count: 1, state: "done" },
      { key: "classified", label: "Trips classified", count: 1, state: "done" },
    ],
  }),
  updateTestRunTitle: vi.fn(async (_id: string, title: string) => ({ id: "run-1", title })),
  controlTestRun: vi.fn().mockResolvedValue({ status: "accepted", command: "PAUSE" }),
  cancelTestRun: vi.fn().mockResolvedValue({ status: "accepted", command: "CANCEL" }),
  planTestPreset: vi.fn(),
  fetchTestPresets: vi.fn().mockResolvedValue({
    presets: [
      {
        id: "default",
        title: "Default",
        description: "Balanced mix",
        kind: "default",
        available: true,
        unavailable_reason: null,
        source_label: null,
        selection_size: 40000,
        available_trips: 40000,
        metadata: {},
        metrics: { sample_size: 2 },
        sample_trips: [],
      },
      {
        id: "vietnam-road-1k",
        title: "Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)",
        description: "1.000 chuyến hành trình thực tế tại Việt Nam",
        kind: "vietnam",
        available: true,
        unavailable_reason: null,
        source_label: "vietnam_road",
        selection_size: 1000,
        available_trips: 1000,
        metadata: {},
        metrics: {},
        sample_trips: [
          {
            trip_ref: "vn_trip_0001",
            label: "Bình thường",
            telemetry_points: 120,
            pickup_name: "Hồ Hoàn Kiếm",
            dropoff_name: "Keangnam",
          },
        ],
      },
      {
        id: "all-normal",
        title: "All normal trips",
        description: "No violation",
        kind: "normal",
        available: true,
        unavailable_reason: null,
        source_label: "no_violation",
        selection_size: 28000,
        available_trips: 28000,
        metadata: {},
        metrics: {},
        sample_trips: [],
      },
      {
        id: "wrong-direction",
        title: "Driver going wrong direction",
        description: "Route deviation",
        kind: "wrong_direction",
        available: false,
        unavailable_reason: "Chưa xác minh",
        source_label: "ERR-03",
        selection_size: 2500,
        available_trips: 2500,
        metadata: {},
        metrics: {},
        sample_trips: [],
      },
    ],
    source: { revision: "914a3656" },
  }),
  fetchTestActors: vi.fn().mockResolvedValue({ drivers: [{ id: "drv-sim-001", display_name: "Driver" }], passengers: [{ id: "pass-sim-001", display_name: "Passenger" }], vehicles: [{ id: "veh-sim-001", display_name: "Vehicle" }], policies: [{ id: "pol-sim-001", display_name: "Policy" }] }),
  fetchTestPresetDetail: vi.fn().mockImplementation(async (id: string) => ({
    id,
    title: id === "vietnam-road-1k" ? "Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)" : "Preset",
    description: "1.000 chuyến hành trình thực tế tại Việt Nam",
    kind: "vietnam",
    available: true,
    trip_count: 1000,
    available_trips: 1000,
    source_release: "synthesized_vietnam_trip",
    revision: "e1a90c01",
    trips_sha256: "abc",
    license: "ODbL",
    distributions: {
      total_records: 1000,
      by_label: {
        fraud: 300,
        no_violation: 700,
        insufficient_evidence: 0,
        grouped: {},
        per_code: { "ERR-01": 75 },
      },
      per_code: { "ERR-01": 75 },
      by_severity: { P1: 100 },
      by_scenario: { deviation: 100 },
      by_city: { "Hà Nội": 1000 },
      by_cancellation_actor: { none: 1000 },
    },
    metrics: {},
    sample_trips: [
      {
        trip_ref: "vn_trip_0001",
        label: "Bình thường",
        telemetry_points: 120,
        pickup_name: "Hồ Hoàn Kiếm",
        dropoff_name: "Keangnam",
      },
    ],
  })),
  fetchClerkLinkedDrivers: vi.fn().mockResolvedValue([
    { driver_id: "drv-001", display_name: "Tài xế 1", email: "drv1@test.com", principal_id: "p-001" },
    {
      driver_id: "drv-sim-001",
      display_name: "Driver 001",
      email: "driver001@example.com",
      principal_id: "principal-001",
      vehicle_id: null,
      license_plate: "30A-12345",
    },
  ]),
  createPresetBatchRun: vi.fn().mockResolvedValue({
    id: "batch-1",
    organization_id: "org-a",
    preset_id: "vietnam-road-1k",
    params: {},
    status: "RUNNING",
    counters: { total: 10, queued: 9, running: 1, completed: 0, failed: 0 },
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: null,
    cancelled_at: null,
  }),
  fetchPresetBatchRunDetail: vi.fn().mockResolvedValue({
    id: "batch-1",
    organization_id: "org-a",
    preset_id: "vietnam-road-1k",
    params: {},
    status: "RUNNING",
    counters: { total: 1, completed: 0 },
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: null,
    cancelled_at: null,
    trips: [],
  }),
  cancelPresetBatchRun: vi.fn().mockResolvedValue({
    id: "batch-1",
    status: "CANCELLED",
  }),
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
}));

// MapLibreView requires browser canvas. Expose a drag trigger so we can exercise onStopDrag.
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: (props: {
    showKinematicFooter?: boolean;
    draggableStops?: boolean;
    onStopDrag?: (kind: string, coords: { latitude: number; longitude: number }) => void;
    onMapClick?: (coords: { latitude: number; longitude: number }) => void;
  }) => (
    <div
      data-testid="maplibre-view"
      data-show-kinematic-footer={String(props.showKinematicFooter)}
      data-draggable-stops={String(props.draggableStops)}
    >
      <button
        data-testid="drag-initial"
        onClick={() => props.onStopDrag?.("initial", { latitude: 21.055, longitude: 105.81 })}
      >
        drag
      </button>
      <button
        data-testid="map-click-waypoint-one"
        onClick={() => props.onMapClick?.({ latitude: 21.0118, longitude: 105.8497 })}
      >
        map click one
      </button>
      <button
        data-testid="map-click-waypoint-two"
        onClick={() => props.onMapClick?.({ latitude: 21.0173, longitude: 105.7838 })}
      >
        map click two
      </button>
    </div>
  ),
}));

describe("Tester console redesign", () => {
  beforeEach(() => {
    authScope.orgId = "org-a";
    vi.clearAllMocks();
  });

  it("renders the redesigned console without the removed authoring controls", async () => {
    render(<SimulationCockpitPage />);

    // Header + dual conversation perspectives
    expect(screen.getByText(/Bảng mô phỏng chuyến đi/i)).toBeDefined();
    expect(screen.getByText(/Màn hình Tài xế/i)).toBeDefined();
    expect(screen.getByText(/Màn hình Khách hàng/i)).toBeDefined();

    // Stops use icons/labels and the map is draggable before a run
    expect(screen.getByLabelText(/Vị trí xuất phát của tài xế/i)).toBeDefined();
    expect(screen.getByLabelText(/Điểm đón khách/i)).toBeDefined();
    expect(screen.getByLabelText(/Điểm đến/i)).toBeDefined();
    const mapView = await screen.findByTestId("maplibre-view");
    expect(mapView.getAttribute("data-draggable-stops")).toBe("true");

    // Run control and processing dock
    expect(screen.getByRole("button", { name: /Chạy mô phỏng/i })).toBeDefined();
    expect(screen.getByRole("button", { name: "Log" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Overview" })).toBeDefined();

    // Removed technology/authoring features must be gone
    expect(screen.queryByText(/Nhập tọa độ/i)).toBeNull();
    expect(screen.queryByText(/Hướng xe/i)).toBeNull();
    expect(screen.queryByText(/Kiểu lộ trình/i)).toBeNull();
    expect(screen.queryByText(/Chế độ lái/i)).toBeNull();
    expect(screen.queryByText(/Bật Click trên bản đồ/i)).toBeNull();
    expect(screen.queryByText(/Redis/i)).toBeNull();
    expect(screen.queryByText(/Hoàn tất nhanh/i)).toBeNull();
    expect(screen.queryByText(/tọa độ GPS/i)).toBeNull();
  });

  it("shows no coordinate authoring inputs anywhere", () => {
    render(<SimulationCockpitPage />);
    expect(document.querySelectorAll('input[type="number"]').length).toBe(1); // only speed
    expect(screen.queryByLabelText(/Vĩ độ/i)).toBeNull();
    expect(screen.queryByLabelText(/Kinh độ/i)).toBeNull();
  });

  it("searches addresses for a stop and lists suggestions on typing", async () => {
    render(<SimulationCockpitPage />);
    const originInput = screen.getByLabelText(/Vị trí xuất phát của tài xế/i);

    await act(async () => {
      fireEvent.focus(originInput);
      fireEvent.change(originInput, { target: { value: "Keangnam" } });
    });

    expect(await screen.findByText(/Keangnam Landmark 72, Hà Nội/i)).toBeDefined();
  });

  it("dragging a stop updates its address and re-resolves the route", async () => {
    const { resolveTestRoute } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);

    await act(async () => {
      fireEvent.click(await screen.findByTestId("drag-initial"));
    });

    expect(screen.getByLabelText(/Vị trí xuất phát của tài xế/i)).toBeDefined();
    expect(screen.getByDisplayValue(/Hồ Hoàn Kiếm, Hà Nội/i)).toBeDefined();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 350));
    });
    await waitFor(() => expect(resolveTestRoute).toHaveBeenCalled());
    const { searchGeocode } = await import("@/lib/testApiClient");
    expect(searchGeocode).toHaveBeenCalledWith(expect.stringMatching(/^21\.\d+,105\.\d+$/), 1);
  });

  it("invalidates the old road route immediately while the next lookup is debouncing", async () => {
    const { resolveTestRoute, searchGeocode } = await import("@/lib/testApiClient");
    let resolveOld: ((value: RouteResolveResponse) => void) | undefined;
    let resolveNew: ((value: RouteResolveResponse) => void) | undefined;
    vi.mocked(resolveTestRoute)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    vi.mocked(searchGeocode).mockImplementationOnce(() => new Promise(() => {}));
    render(<SimulationCockpitPage />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
    expect(resolveOld).toBeDefined();
    fireEvent.click(await screen.findByTestId("drag-initial"));
    await act(async () => { resolveOld?.(routeResponse); });
    expect(screen.queryByText("8.50 km")).toBeNull();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
    expect(resolveNew).toBeDefined();
    await act(async () => { resolveNew?.({ ...routeResponse, pickup_route: { ...routeResponse.pickup_route, distance_m: 1000 }, destination_route: { ...routeResponse.destination_route, distance_m: 1000 } }); });
    expect(await screen.findByText("2.00 km")).toBeVisible();
  });

  it("shows the preset library with truthful availability", async () => {
    const { fetchTestPresets } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Chuyến mẫu/i }));
    });

    expect(fetchTestPresets).toHaveBeenCalled();
    expect(await screen.findByText("All normal trips")).toBeDefined();
    expect(screen.getByText(/Tạm chưa mở/i)).toBeDefined();
  });

  it("shows organization history", async () => {
    const { fetchTestRuns } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Lịch sử/i }));
    });

    expect(fetchTestRuns).toHaveBeenCalled();
    expect(await screen.findByText("Chuyến đêm Hà Nội")).toBeDefined();
  });

  it("edits speed in km/h while sending m/s to the simulation API", async () => {
    const { postTest } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);
    const speed = screen.getByLabelText(/Vận tốc \(km\/h\)/i);
    expect(speed).toHaveValue(43.2);
    fireEvent.change(speed, { target: { value: "43.2" } });
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver 001");
    fireEvent.click(driverOption);
    await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(3));
    const actorSelects = screen.getAllByRole("combobox");
    ["pass-sim-001", "veh-sim-001", "pol-sim-001"].forEach((value, index) => fireEvent.change(actorSelects[index], { target: { value } }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 400)); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i })); });
    await waitFor(() => expect(postTest).toHaveBeenCalledWith("/definitions", expect.objectContaining({ driver_config: expect.objectContaining({ speed_mps: 12 }) })));
  });

  it("sends speed changes to a running test and updates the displayed factor", async () => {
    const { controlTestRun, postTest } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);

    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    fireEvent.click(await screen.findByText("Driver 001"));
    await screen.findByRole("option", { name: "Passenger" });
    screen.getAllByRole("combobox").forEach((select, index) => {
      fireEvent.change(select, { target: { value: ["pass-sim-001", "veh-sim-001", "pol-sim-001"][index] } });
    });
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));

    await waitFor(() => expect(postTest).toHaveBeenCalledWith("/runs", expect.any(Object)));
    await screen.findByRole("button", { name: /Tạm dừng/i });
    expect(screen.getByTestId("speed-factor-display").textContent === "1x").toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Tốc độ 5x" }));

    await waitFor(() => expect(controlTestRun).toHaveBeenCalledWith("run-1", "SET_SPEED_FACTOR", { speed_factor: 5 }));
    expect(screen.getByTestId("speed-factor-display").textContent === "5x").toBe(true);
  });

  it("resolves numbered waypoints in order with their selected route legs", async () => {
    const { resolveTestRoute } = await import("@/lib/testApiClient");
    render(<SimulationCockpitPage />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
    vi.mocked(resolveTestRoute).mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Bật chế độ nhấp bản đồ để thêm điểm rẽ" }));
    fireEvent.click(screen.getByTestId("map-click-waypoint-one"));
    fireEvent.click(screen.getByTestId("map-click-waypoint-two"));
    await waitFor(() => expect(screen.getByTestId("waypoint-item-2")).toBeDefined());

    const waypointLegs = screen.getAllByRole("combobox", { name: /Chặng của điểm rẽ/ });
    fireEvent.change(waypointLegs[0], { target: { value: "pickup" } });
    fireEvent.change(waypointLegs[1], { target: { value: "destination" } });

    await waitFor(() => expect(resolveTestRoute).toHaveBeenCalled());
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
    const latestCall = vi.mocked(resolveTestRoute).mock.calls.at(-1);
    expect(latestCall?.[3]).toEqual([
      { lat: 21.0118, lon: 105.8497, leg: "pickup" },
      { lat: 21.0173, lon: 105.7838, leg: "destination" },
    ]);
  });

  it("freezes stop editing while run creation is pending", async () => {
    const { postTest } = await import("@/lib/testApiClient");
    vi.mocked(postTest).mockImplementationOnce(() => new Promise(() => {}));
    render(<SimulationCockpitPage />);
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver 001");
    fireEvent.click(driverOption);
    await screen.findByRole("option", { name: "Passenger" });
    const selects = screen.getAllByRole("combobox");
    ["pass-sim-001", "veh-sim-001", "pol-sim-001"].forEach((value, index) => fireEvent.change(selects[index], { target: { value } }));
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    await waitFor(() => expect(screen.getByLabelText(/Vị trí xuất phát của tài xế/i)).toBeDisabled());
    expect((await screen.findByTestId("maplibre-view")).getAttribute("data-draggable-stops")).toBe("false");
  });

  it("ignores a run creation response after switching organization", async () => {
    const { postTest } = await import("@/lib/testApiClient");
    let finishRun: ((value: unknown) => void) | undefined;
    vi.mocked(postTest)
      .mockReturnValueOnce(Promise.resolve({ id: "plan-a" }))
      .mockReturnValueOnce(Promise.resolve({ id: "definition-a" }))
      .mockReturnValueOnce(new Promise((resolve) => { finishRun = resolve; }));
    const { rerender } = render(<SimulationCockpitPage />);
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver 001");
    fireEvent.click(driverOption);
    await screen.findByRole("option", { name: "Passenger" });
    screen.getAllByRole("combobox").forEach((select, index) => fireEvent.change(select, { target: { value: ["pass-sim-001", "veh-sim-001", "pol-sim-001"][index] } }));
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    await waitFor(() => expect(postTest).toHaveBeenCalledTimes(3));
    authScope.orgId = "org-b";
    rerender(<SimulationCockpitPage />);
    await act(async () => { finishRun?.({ id: "run-a", total_steps: 5, title: "Private organization A run" }); });
    expect(screen.queryByText("Private organization A run")).toBeNull();
  });

  it("ignores history responses from an organization that is no longer active", async () => {
    const { fetchTestRuns } = await import("@/lib/testApiClient");
    let finishOld: ((value: Awaited<ReturnType<typeof fetchTestRuns>>) => void) | undefined;
    vi.mocked(fetchTestRuns).mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    const { rerender } = render(<SimulationCockpitPage />);
    fireEvent.click(screen.getByRole("button", { name: /Lịch sử/i }));
    await waitFor(() => expect(fetchTestRuns).toHaveBeenCalled());
    authScope.orgId = "org-b";
    rerender(<SimulationCockpitPage />);
    await act(async () => { finishOld?.([{ id: "foreign", title: "Foreign org history", status: "COMPLETED", created_at: new Date().toISOString(), trip_id: null, completed_at: null, cancellation_actor: null, cancellation_reason: null }]); });
    expect(screen.queryByText("Foreign org history")).toBeNull();
  });

  it("selecting Vietnam preset plans trip via API and enables execution with planned definition", async () => {
    const { fetchTestPresets, planTestPreset, postTest } = await import("@/lib/testApiClient");
    vi.mocked(planTestPreset).mockResolvedValueOnce({
      plan: {
        id: "plan-vn-mock-1",
        name: "Chuyến Hà Nội - vn_trip_0001",
        description: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      definition: {
        id: "def-vn-mock-1",
        plan_id: "plan-vn-mock-1",
        revision_number: 1,
        route_geometry: {
          type: "LineString",
          coordinates: [
            [105.8524, 21.0285],
            [105.8497, 21.0118],
            [105.7838, 21.0173],
          ],
        },
        driver_config: { speed_mps: 12, update_cadence_s: 1, driver_id: "drv-vn-001" },
        passenger_config: { passenger_id: "pass-vn-001", name: "Nguyễn Văn A" },
        fault_configs: [],
        messages: [
          { sender_role: "PASSENGER", content: "Tôi đang ở sảnh chính", offset_seconds: 0 },
          { sender_role: "DRIVER", content: "Tôi đang tới nơi", offset_seconds: 5 },
        ],
        initial_snapshot: {
          location: { latitude: 21.0285, longitude: 105.8524 },
          address: "Hồ Hoàn Kiếm, Hà Nội",
        },
        pickup_snapshot: {
          location: { latitude: 21.0118, longitude: 105.8497 },
          address: "Công viên Thống Nhất, Hà Nội",
        },
        destination_snapshot: {
          location: { latitude: 21.0173, longitude: 105.7838 },
          address: "Keangnam Landmark, Hà Nội",
        },
      },
      preset_id: "vietnam-road-1k",
      trip_ref: "vn_trip_0001",
      label: "Bình thường",
      distance_m: 8500,
      telemetry_points: 120,
      initial_snapshot: {
        location: { latitude: 21.0285, longitude: 105.8524 },
        address: "Hồ Hoàn Kiếm, Hà Nội",
      },
      pickup_snapshot: {
        location: { latitude: 21.0118, longitude: 105.8497 },
        address: "Công viên Thống Nhất, Hà Nội",
      },
      destination_snapshot: {
        location: { latitude: 21.0173, longitude: 105.7838 },
        address: "Keangnam Landmark, Hà Nội",
      },
      telemetry: [],
    });

    render(<SimulationCockpitPage />);

    // Switch to presets tab
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Chuyến mẫu/i }));
    });
    expect(fetchTestPresets).toHaveBeenCalled();

    // Find and select the Vietnam preset card: selects preset and stays on Presets tab
    const presetBtn = await screen.findByText("Tập dữ liệu đường bộ Việt Nam (1.000 chuyến)");
    await act(async () => {
      fireEvent.click(presetBtn);
    });

    // PresetDetail is shown on Presets tab, card click does NOT switch tab or plan yet
    expect(planTestPreset).not.toHaveBeenCalled();
    expect(await screen.findByTestId("preset-detail-container")).toBeDefined();

    // Switch to Samples tab in PresetDetail and click secondary action "Mở trong bảng thủ công"
    const samplesTabTrigger = screen.getByTestId("tab-trigger-samples");
    await act(async () => {
      fireEvent.click(samplesTabTrigger);
    });

    const openManualBtn = await screen.findByTestId("open-manual-vn_trip_0001");
    await act(async () => {
      fireEvent.click(openManualBtn);
    });

    // Verify preset was planned via API with correct preset ID and trip ref
    expect(planTestPreset).toHaveBeenCalledWith("vietnam-road-1k", "vn_trip_0001");

    // Returned to manual tab with populated route and chat
    expect(await screen.findAllByText("Tôi đang ở sảnh chính")).toHaveLength(2);
    expect(await screen.findByText("8.50 km")).toBeDefined();

    // Verify execution controls: operator triggers run explicitly
    const runBtn = screen.getByRole("button", { name: /Chạy mô phỏng/i });
    expect(runBtn).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(runBtn);
    });

    // Must call /runs with planned definition_revision_id directly
    expect(postTest).toHaveBeenCalledWith(
      "/runs",
      expect.objectContaining({
        definition_revision_id: "def-vn-mock-1",
        title: "Chuyến Hà Nội - vn_trip_0001",
      })
    );
  });

  it("renders 6.6 Test Workplace View with Sentinel app switcher, filter bar, and empty-state", () => {
    render(<TestWorkplacePage />);
    expect(screen.getByRole("button", { name: "GreenSentinel app catalog" })).toBeDefined();
    expect(screen.getByText(/ALL STATUSES/i)).toBeDefined();
    expect(screen.getByText("JUMP")).toBeDefined();
    expect(screen.getByText("OFFSET_NOISE")).toBeDefined();
    expect(screen.getByText("DROPOUT")).toBeDefined();
    expect(screen.getByText(/Select a case from the queue to begin triage/i)).toBeDefined();
  });
});
