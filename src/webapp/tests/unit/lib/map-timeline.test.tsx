import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  MapLibreView,
  OPENFREEMAP_LIBERTY_STYLE,
  OPENFREEMAP_POSITRON_STYLE,
  OSM_RASTER_FALLBACK_STYLE,
} from "@/components/map/maplibre-view";
import {
  mockCandidateRoutes,
  mockTrafficCorroboration,
  mockTimelineMilestones,
  mockMissingnessAlerts,
  mockDestination,
  mockDriverInitial,
} from "@/tests/fixtures/mock-data";

describe("MapLibreView - Map Full Features (TDD)", () => {
  it("0. Unblocks Vercel environment without requiring any Map API key and uses keyless OpenFreeMap style", () => {
    expect(OPENFREEMAP_LIBERTY_STYLE).toContain("openfreemap.org");
    expect(OPENFREEMAP_POSITRON_STYLE).toContain("openfreemap.org");
    expect(OSM_RASTER_FALLBACK_STYLE.sources.osm).toBeDefined();

    const { unmount } = render(<MapLibreView mapStyle={OPENFREEMAP_LIBERTY_STYLE} />);
    expect(screen.getByTestId("maplibre-view")).toBeInTheDocument();
    // Does not render any blocking 'API key required' dialog, modal, or watermark warning
    expect(screen.queryByText(/enter map api key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/missing mapbox token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/api key required/i)).not.toBeInTheDocument();
    unmount();
  });

  it("1. Displays Shortest path (Route 1) from Driver initial position to Pickup point", () => {
    render(
      <MapLibreView
        candidateRoutes={mockCandidateRoutes}
        driverInitialLocation={mockDriverInitial}
      />
    );

    // Route 1 exists in the route layers / SVG fallback
    expect(screen.getByTestId("candidate-route-1")).toBeInTheDocument();
    expect(screen.getAllByText(/Tuyến 1: Ngắn nhất/i).length).toBeGreaterThanOrEqual(1);
  });

  it("2 & 7. Renders interactive Timeline bar under map with second precision, small marks, and clean start/end times", () => {
    render(
      <MapLibreView
        timelineMilestones={mockTimelineMilestones}
        destinationLocation={mockDestination}
      />
    );

    const timeline = screen.getByTestId("trip-timeline-bar");
    expect(timeline).toBeInTheDocument();

    // Preserve millisecond GPS precision while displaying second-level timestamps
    const scrubber = screen.getByTestId("timeline-scrubber-slider");
    expect(scrubber).toBeInTheDocument();
    expect(scrubber).toHaveAttribute("step", "0.001");
    expect(scrubber).toHaveAttribute("min", "0");

    // Scrubbing to second 210 (08:13:30) updates current timepoint and milestone readout
    fireEvent.change(scrubber, { target: { value: "210" } });
    expect(screen.getByTestId("active-timeline-status")).toHaveTextContent(/Bất thường dừng đỗ/i);
    expect(screen.getByTestId("active-timeline-status")).toHaveTextContent(/08:13:30/);

    // 2. Checkpoints are small marks directly along the timeline, not large buttons
    const startMark = screen.getByTestId("milestone-start_match");
    const stallMark = screen.getByTestId("milestone-stall_anomaly");
    const pickupMark = screen.getByTestId("milestone-pickup");
    const dropoffMark = screen.getByTestId("milestone-dropoff_destination");

    expect(startMark).toBeInTheDocument();
    expect(stallMark).toBeInTheDocument();
    expect(pickupMark).toBeInTheDocument();
    expect(dropoffMark).toBeInTheDocument();

    // Informational marks do not seek; use the native scrubber for navigation.
    expect(pickupMark.tagName).toBe('SPAN');
    fireEvent.change(scrubber, { target: { value: '390' } });
    expect(screen.getByTestId("active-timeline-status")).toHaveTextContent(/Điểm đón khách/i);
    expect(screen.getByTestId("active-timeline-status")).toHaveTextContent(/08:16:30/);

    // 3. Clean start/end times: leftmost is matching time, rightmost is finish time
    expect(screen.getByTestId("timeline-start-time")).toHaveTextContent("08:10:00");
    expect(screen.getByTestId("timeline-end-time")).toHaveTextContent("08:35:00");

    // Redundant text like "Trục thời gian điều tra", "Chấp nhận cuốc", and "Khớp chuyến (Matching)" tag are completely removed
    expect(screen.queryByText(/Trục thời gian điều tra/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Chấp nhận cuốc/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Khớp chuyến/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/matching/i)).not.toBeInTheDocument();

    // Destination marker on map
    expect(screen.getByTestId("destination-marker")).toBeInTheDocument();
  });

  it("3. Displays mock traffic jam, traffic signals, and multi-driver corroboration widget with auto-hide hover", () => {
    render(
      <MapLibreView
        trafficCorroboration={mockTrafficCorroboration}
        initialTraffic={true}
      />
    );

    const panel = screen.getByTestId("traffic-corroboration-panel");
    expect(panel).toBeInTheDocument();
    expect(screen.getByText(/Traffic claim refuted/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Google Maps Traffic Mock/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/34.0 km\/h/i)).toBeInTheDocument(); // Peer speed

    // Collapsed initially showing compact pill
    expect(screen.getByText(/Corroboration 3 vehicles/i)).toBeInTheDocument();

    // Hover expands into full header
    fireEvent.mouseEnter(panel);
    expect(screen.getByText(/MULTI-DRIVER TRAFFIC CORROBORATION/i)).toBeInTheDocument();

    // Leave collapses back
    fireEvent.mouseLeave(panel);
    expect(screen.getByText(/Corroboration 3 vehicles/i)).toBeInTheDocument();
  });

  it("4. Shows 3 top routes with DAVI, SDD, distance, ETA, signals on hover and displays speed & latency", () => {
    render(
      <MapLibreView
        candidateRoutes={mockCandidateRoutes}
        currentSpeedMps={8.5}
        gpsLatencyMs={42}
      />
    );

    // Speedometer and Latency indicators
    expect(screen.getByTestId("speedometer-readout")).toHaveTextContent(/30.6 km\/h/i);
    expect(screen.getByTestId("gps-latency-indicator")).toHaveTextContent(/42ms/i);

    // Route 1 pill button
    const route1Btn = screen.getByRole("button", { name: /Tuyến 1/i });
    expect(route1Btn).toBeInTheDocument();

    // Hover / click on route shows detailed metrics card
    fireEvent.click(route1Btn);
    const metricsCard = screen.getByTestId("route-inspection-card");
    expect(metricsCard).toBeInTheDocument();
    expect(metricsCard).toHaveTextContent(/DAVI: \+0.04/i);
    expect(metricsCard).toHaveTextContent(/SDD: 1.02/i);
    expect(metricsCard).toHaveTextContent(/680m/i);
    expect(metricsCard).toHaveTextContent(/Signals: 2/i);

    // Moving mouse out of the card auto-hides it
    fireEvent.mouseLeave(metricsCard);
    expect(screen.queryByTestId("route-inspection-card")).not.toBeInTheDocument();
    // Loaded-runner budget: fully mocked, flaked at 6630ms vs 5s in CI (Oct 9).
  }, 10_000);

  it("5. Displays alert for telemetry missingness / network error on analyst watch", () => {
    render(
      <MapLibreView
        missingnessAlerts={mockMissingnessAlerts}
      />
    );

    const alertBanner = screen.getByTestId("data-missingness-alert-banner");
    expect(alertBanner).toBeInTheDocument();
    expect(alertBanner).toHaveTextContent(/45s/i);
    expect(alertBanner).toHaveAttribute("title", expect.stringMatching(/Network degraded/i));
  });

  it("6. Displays actual driven route in distinct high-contrast color", () => {
    render(
      <MapLibreView
        driverBreadcrumbs={[
          [105.8512, 21.025],
          [105.852, 21.0268],
          [105.853, 21.032],
        ]}
      />
    );

    const actualRoute = screen.getByTestId("driver-trajectory");
    expect(actualRoute).toBeInTheDocument();
    // Actual route path element uses #ea580c (orange) stroke
    const path = actualRoute.querySelector("path");
    expect(path).toHaveAttribute("stroke", "#ea580c");
  });
});
