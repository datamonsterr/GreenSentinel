import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SimulationCockpitPage from "@/app/test/page";

const api = vi.hoisted(() => ({
  postTest: vi.fn(async (path: string) => path === "/plans" ? { id: "p" } : path === "/definitions" ? { id: "d" } : { id: "r", total_steps: 2 }),
  streamTest: vi.fn(async (): Promise<Response> => new Response(new ReadableStream({ start(controller) { controller.close(); } }))),
  searchGeocode: vi.fn().mockResolvedValue([]),
  resolveTestRoute: vi.fn().mockResolvedValue({ route_geometry: { type: "LineString", coordinates: [[1, 1], [2, 2]] }, pickup_route: { coordinates: [[1, 1], [2, 2]], distance_m: 1, duration_s: 1 }, destination_route: { coordinates: [[2, 2], [3, 3]], distance_m: 1, duration_s: 1 } }),
  cancelTestRun: vi.fn().mockResolvedValue({ status: "accepted" }),
  publishSimulationToProduction: vi.fn().mockResolvedValue({ status: "published", destination: "/workplace" }),
  fetchTestActors: vi.fn().mockResolvedValue({ drivers: [{ id: "d", display_name: "D" }], passengers: [{ id: "p", display_name: "P" }], vehicles: [{ id: "v", display_name: "V" }], policies: [{ id: "q", display_name: "Q" }] }),
  searchClerkDrivers: vi.fn().mockResolvedValue([{ driver_id: "d", display_name: "Driver D", email: "driver.d@example.com", principal_id: "principal-d", vehicle_id: null, license_plate: "30A-12345" }]),
  fetchClerkLinkedDrivers: vi.fn().mockResolvedValue([{ driver_id: "d", display_name: "Driver D", email: "driver.d@example.com", principal_id: "principal-d", vehicle_id: null, license_plate: "30A-12345" }]),
  fetchTestRunStatus: vi.fn().mockResolvedValue({ id: "r", status: "RUNNING", current_step: 0, total_steps: 2 }),
  fetchTestSamples: vi.fn().mockResolvedValue([]),
  fetchTestRuns: vi.fn().mockResolvedValue([]), fetchTestPresets: vi.fn().mockResolvedValue({ presets: [], source: {} }), fetchTestRunOverview: vi.fn().mockResolvedValue(null), updateTestRunTitle: vi.fn(), setTestApiTokenProvider: vi.fn(),
}));
vi.mock("@/lib/testApiClient", () => api);
vi.mock("@/components/map/maplibre-view", () => ({ MapLibreView: () => <div data-testid="map" /> }));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => null, isLoaded: true, orgId: "org" }) }));

describe("cancellation DoD", () => {
  it("dismisses with Escape and focuses whitespace reason", async () => {
    render(<SimulationCockpitPage />);
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver D");
    fireEvent.click(driverOption);
    await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(3));
    screen.getAllByRole("combobox").forEach((select, i) => fireEvent.change(select, { target: { value: ["p", "v", "q"][i] } }));
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Khách huỷ chuyến/i })).toBeVisible());
    fireEvent.click(screen.getByRole("button", { name: /Khách huỷ chuyến/i }));
    const reason = screen.getByLabelText("Lý do huỷ chuyến");
    fireEvent.change(reason, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/i }));
    expect(reason).toHaveFocus();
    const close = screen.getAllByRole("button", { name: "Đóng" })[0];
    close.focus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: /Xác nhận/i })).toHaveFocus();
    fireEvent.keyDown(reason, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("preserves reason and running state when cancellation API fails", async () => {
    api.cancelTestRun.mockRejectedValueOnce(new Error("cancel failed"));
    render(<SimulationCockpitPage />);
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver D");
    fireEvent.click(driverOption);
    await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(3));
    screen.getAllByRole("combobox").forEach((select, i) => fireEvent.change(select, { target: { value: ["p", "v", "q"][i] } }));
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Khách huỷ chuyến/i })).toBeVisible());
    fireEvent.click(screen.getByRole("button", { name: /Khách huỷ chuyến/i }));
    const reason = screen.getByLabelText("Lý do huỷ chuyến");
    fireEvent.change(reason, { target: { value: "Passenger changed mind" } });
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/i }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
    expect(reason).toHaveValue("Passenger changed mind");
    expect(screen.queryByRole("button", { name: /Gửi chuyến đã huỷ/i })).toBeNull();
  });

  it("exposes cancelled processing only after terminal SSE evidence", async () => {
    const payload = `data: ${JSON.stringify({ event_id: "evt-1", event_type: "run.cancelled", step_index: 1, cancellation_actor: "passenger", cancellation_reason: "Passenger changed mind", run_id: "r", organization_id: "org", trip_id: "trip-real", simulation_clock: "2026-10-15T01:00:00Z", state_before: "PAUSED" })}\n\n`;
    api.streamTest.mockImplementationOnce(async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode(payload)); controller.close(); },
    })));
    render(<SimulationCockpitPage />);
    const driverInput = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(driverInput, { target: { value: "driver" } });
    const driverOption = await screen.findByText("Driver D");
    fireEvent.click(driverOption);
    await waitFor(() => expect(screen.getAllByRole("combobox")).toHaveLength(3));
    screen.getAllByRole("combobox").forEach((select, i) => fireEvent.change(select, { target: { value: ["p", "v", "q"][i] } }));
    fireEvent.click(screen.getByRole("button", { name: /Chạy mô phỏng/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Gửi chuyến đã huỷ/i })).toBeVisible());
    fireEvent.click(screen.getByRole("button", { name: /Gửi chuyến đã huỷ/i }));
    await waitFor(() => expect(api.publishSimulationToProduction).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Khách\/Tài xế huỷ chuyến/i }));
    expect(screen.getByText(/"event_id": "evt-1"/)).toHaveTextContent('"trip_id": "trip-real"');
    expect(screen.getByText(/"event_id": "evt-1"/)).toHaveTextContent('"state_before": "PAUSED"');
  });
});
