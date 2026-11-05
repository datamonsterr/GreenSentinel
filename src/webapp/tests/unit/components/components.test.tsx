import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MapLibreView } from "@/components/map/maplibre-view";
import { mockTrafficCorroboration } from "@/tests/fixtures/mock-data";

describe("MapLibreView", () => {
  const spatialFixture = {
    pickupRoute: [[105.84, 21.01], [105.85, 21.02]] as [number, number][],
    driverBreadcrumbs: [[105.84, 21.01], [105.845, 21.015]] as [number, number][],
    hotspots: [{ longitude: 105.845, latitude: 21.015 }],
    trafficCorroboration: mockTrafficCorroboration,
  };
  it("renders GIS fallback overlay safely in headless environment with all spatial layers and markers", () => {
    render(
      <MapLibreView
        {...spatialFixture}
        driverLocation={{
          latitude: 21.0268,
          longitude: 105.852,
          bearing: 178,
          status: "stalled",
        }}
        stallPoint={{
          latitude: 21.0268,
          longitude: 105.852,
          duration_seconds: 210,
          davi_score: -0.84,
          label: "210s Stall",
        }}
      />
    );

    // Map container & fallback
    expect(screen.getByTestId("maplibre-view")).toBeInTheDocument();
    expect(screen.getByTestId("maplibre-fallback")).toBeInTheDocument();

    // Route & breadcrumbs
    expect(screen.getByTestId("pickup-route")).toBeInTheDocument();
    expect(screen.getByTestId("driver-trajectory")).toBeInTheDocument();

    // Vehicle marker and recorded status badge
    expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
    expect(screen.getByTestId("driver-vehicle-marker").querySelector('svg')).toBeInTheDocument();
    const statusBadge = screen.getByTestId("trip-status-badge");
    expect(statusBadge).toHaveTextContent("stalled");

    // Stall point indicator with 210s Stall and DAVI alert
    const stallIndicator = screen.getByTestId("stall-point-indicator");
    expect(stallIndicator).toBeInTheDocument();
    expect(stallIndicator).toHaveTextContent(/210s Stall/);
    expect(stallIndicator).toHaveTextContent(/DAVI alert/);

    // Telemetry footer
    expect(screen.getAllByText(/210s Stall/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/-0.84/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/33.2 km\/h/).length).toBeGreaterThan(0);
  });

  it("handles layer toggling for traffic, breadcrumbs, route, and hotspots", () => {
    render(
      <MapLibreView
        {...spatialFixture}
        initialTraffic={true}
        initialBreadcrumbs={true}
        initialRoute={true}
        initialHotspots={true}
      />
    );

    // Initially all layers present
    expect(screen.getByTestId("traffic-corroboration-panel")).toBeInTheDocument();
    expect(screen.getByTestId("driver-trajectory")).toBeInTheDocument();
    expect(screen.getByTestId("pickup-route")).toBeInTheDocument();
    expect(screen.getByTestId("hotspot-indicator")).toBeInTheDocument();

    // Toggle Traffic off
    const trafficBtn = screen.getByRole("button", { name: /Traffic/i });
    fireEvent.click(trafficBtn);
    expect(screen.queryByTestId("traffic-corroboration-panel")).not.toBeInTheDocument();

    // Toggle Hotspots off
    const hotspotsBtn = screen.getByRole("button", { name: /Hotspots/i });
    fireEvent.click(hotspotsBtn);
    expect(screen.queryByTestId("hotspot-indicator")).not.toBeInTheDocument();

    // Toggle Breadcrumbs off
    const breadcrumbsBtn = screen.getByRole("button", { name: /Breadcrumbs/i });
    fireEvent.click(breadcrumbsBtn);
    expect(screen.queryByTestId("driver-trajectory")).not.toBeInTheDocument();

    // Toggle Route off
    const routeBtn = screen.getByRole("button", { name: /Road route/i });
    fireEvent.click(routeBtn);
    expect(screen.queryByTestId("pickup-route")).not.toBeInTheDocument();
  });

  it("extracts dynamic coordinates from routeGeometry and telemetrySamples props", () => {
    const customRoute = {
      route: {
        coordinates: [
          [105.84, 21.01],
          [105.85, 21.02],
        ],
      },
    };
    const customTelemetry = [
      { recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [105.842, 21.012] }, bearing_deg: 90 },
      { recorded_at: "2026-09-24T00:01:00Z", position: { coordinates: [105.845, 21.015] }, bearing_deg: 120 },
    ];

    render(
      <MapLibreView
        customerLocation={{ longitude: 105.85, latitude: 21.02 }}
        routeGeometry={customRoute}
        telemetrySamples={customTelemetry}
      />
    );

    expect(screen.getByTestId("maplibre-view")).toBeInTheDocument();
    expect(screen.getByTestId("pickup-route")).toBeInTheDocument();
    expect(screen.getByTestId("driver-trajectory")).toBeInTheDocument();
    expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
    expect(screen.getByTestId("customer-pickup-marker")).toBeInTheDocument();
  });
});
