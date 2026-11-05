import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MapLibreView } from "../components/map/maplibre-view";
import { mockTrafficCorroboration } from "./fixtures/mock-data";

describe("MapLibreView - GIS Evidence States", () => {
  it("shows both routes missing explicitly when routeGeometry is provided but routes are absent", () => {
    render(<MapLibreView routeGeometry={{}} />);
    expect(screen.getByTestId("missing-route-both")).toBeInTheDocument();
  });

  it("shows only pickup route missing explicitly", () => {
    render(
      <MapLibreView
        routeGeometry={{
          destination_route: { coordinates: [[105, 21], [105.1, 21.1]] }
        }}
      />
    );
    expect(screen.getByTestId("missing-route-pickup")).toBeInTheDocument();
    expect(screen.queryByTestId("missing-route-both")).not.toBeInTheDocument();
  });

  it("shows only destination route missing explicitly", () => {
    render(
      <MapLibreView
        routeGeometry={{
          pickup_route: { coordinates: [[105, 21], [105.1, 21.1]] }
        }}
      />
    );
    expect(screen.getByTestId("missing-route-destination")).toBeInTheDocument();
    expect(screen.queryByTestId("missing-route-both")).not.toBeInTheDocument();
  });

  it("shows no missing route claims when both routes are provided", () => {
    render(
      <MapLibreView
        routeGeometry={{
          pickup_route: { coordinates: [[105, 21], [105.1, 21.1]] },
          destination_route: { coordinates: [[105.1, 21.1], [105.2, 21.2]] }
        }}
      />
    );
    expect(screen.queryByText(/Unavailable/)).not.toBeInTheDocument();
  });
});

  it("shows explicit GPS unavailable when telemetrySamples is an empty array", () => {
    const { getByTestId, queryByTestId } = render(
      <MapLibreView telemetrySamples={[]} />
    );
    expect(getByTestId("gps-unavailable-label")).toBeInTheDocument();
    expect(queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
  });

  it("shows explicit GPS unavailable when telemetrySamples has only invalid coordinates", () => {
    const { getByTestId, queryByTestId } = render(
      <MapLibreView telemetrySamples={[{ recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [NaN, 10] } }]} />
    );
    expect(getByTestId("gps-unavailable-label")).toBeInTheDocument();
    expect(queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
  });

  it("preserves legacy behavior when telemetrySamples is undefined", () => {
    const { queryByTestId } = render(
      <MapLibreView driverLocation={{ latitude: 21, longitude: 105 }} />
    );
    expect(queryByTestId("gps-unavailable-label")).not.toBeInTheDocument();
    expect(queryByTestId("driver-vehicle-marker")).toBeInTheDocument();
  });

  it("shows explicit missing traffic labels when trafficCorroboration is null", () => {
    const { getByTestId } = render(
      <MapLibreView trafficCorroboration={null} initialTraffic={true} />
    );
    expect(getByTestId("ambient-traffic-status")).toHaveTextContent("No data yet");
    expect(getByTestId("traffic-corroboration-panel")).toHaveTextContent("No traffic data");
  });

  it("fills the footer stall point and DAVI drift from measured case values, else No data yet", () => {
    const { rerender } = render(<MapLibreView stallDurationSeconds={19} daviScore={0.187} />);
    expect(screen.getByTestId("footer-stall-point")).toHaveTextContent("19s Stall");
    expect(screen.getByTestId("footer-davi-drift")).toHaveTextContent("0.187");
    rerender(<MapLibreView />);
    expect(screen.queryByTestId("footer-stall-point")).not.toBeInTheDocument();
    expect(screen.queryByTestId("footer-davi-drift")).not.toBeInTheDocument();
    expect(screen.getByText("Stall point:").parentElement).toHaveTextContent("Stall point:No data yet");
    expect(screen.getByText("DAVI drift:").parentElement).toHaveTextContent("DAVI drift:No data yet");
    expect(screen.getByTestId("ambient-traffic-status")).toHaveTextContent("No data yet");
  });

  it("preserves default empty state when trafficCorroboration is undefined", () => {
    const { queryByTestId, getByTestId } = render(
      <MapLibreView trafficCorroboration={undefined} />
    );
    expect(getByTestId("ambient-traffic-status")).toHaveTextContent("No data yet");
    expect(queryByTestId("traffic-corroboration-panel")).not.toBeInTheDocument();
  });


describe("recorded GPS coordinates", () => {
  it.each([
    [200, 100], [181, 21], [-181, 21], [105, 91], [105, -91],
  ])("rejects out-of-range GPS [%s, %s] without rendering a vehicle or origin", (longitude, latitude) => {
    render(<MapLibreView telemetrySamples={[{
      recorded_at: "2026-09-24T00:00:00Z",
      position: { coordinates: [longitude, latitude] },
    }]} />);
    expect(screen.getByTestId("gps-unavailable-label")).toHaveTextContent("No data yet");
    expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
    expect(screen.queryByTestId("driver-initial-marker")).not.toBeInTheDocument();
    expect(screen.queryByTestId("observed-gps-fix")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Center whole trip" })).toBeDisabled();
  });
});


it.each(["pickup", "destination"] as const)("keeps valid %s road geometry and checkpoints when the other leg has invalid coordinates", (validLeg) => {
  const validRoute = { coordinates: [[105, 21], [105.1, 21.1]] };
  const invalidLeg = validLeg === "pickup" ? "destination" : "pickup";
  const checkpoints = {
    driverInitialLocation: { longitude: 105, latitude: 21 },
    customerLocation: { longitude: 105.05, latitude: 21.05 },
    destinationLocation: { longitude: 105.1, latitude: 21.1 },
  };
  const { rerender } = render(<MapLibreView {...checkpoints} telemetrySamples={[]}
    routeGeometry={{ [`${validLeg}_route`]: validRoute }} />);
  const path = screen.getByTestId(`${validLeg}-route`).querySelector("path")?.getAttribute("d");
  const pickupPosition = screen.getByTestId("customer-pickup-marker").getAttribute("transform");
  rerender(<MapLibreView {...checkpoints} telemetrySamples={[]}
    routeGeometry={{
      [`${validLeg}_route`]: validRoute,
      [`${invalidLeg}_route`]: { coordinates: [[200, 100], [-181, 21], [105, -91]] },
    }} />);
  expect(screen.queryByTestId(`${invalidLeg}-route`)).not.toBeInTheDocument();
  expect(screen.getByTestId(`missing-route-${invalidLeg}`)).toHaveTextContent("No data yet");
  expect(screen.getByTestId(`${validLeg}-route`).querySelector("path")).toHaveAttribute("d", path);
  expect(screen.getByTestId("customer-pickup-marker")).toHaveAttribute("transform", pickupPosition);
  expect(screen.getByTestId("driver-initial-marker")).toBeInTheDocument();
  expect(screen.getByTestId("destination-marker")).toBeInTheDocument();
  expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
});


const legacyMilestones = [{
  id: "legacy-pickup", type: "pickup" as const,
  timestamp: "2026-09-24T00:00:00Z", title: "Pickup", description: "Recorded checkpoint",
  lat: 21, lon: 105, speed_mps: 42,
}];

it.each([
  { name: "empty GPS with legacy speed", samples: [], currentSpeedMps: 42 },
  { name: "empty GPS with milestone speed", samples: [], currentSpeedMps: undefined },
  { name: "invalid GPS with legacy speed", samples: [{
    recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [200, 100] }, speed_mps: 42,
  }], currentSpeedMps: 42 },
])("does not infer speed, vehicle or origin from $name", ({ samples, currentSpeedMps }) => {
  render(<MapLibreView telemetrySamples={samples} currentSpeedMps={currentSpeedMps}
    driverLocation={{ longitude: 105, latitude: 21 }} timelineMilestones={legacyMilestones}
    routeGeometry={{ pickup_route: { coordinates: [[105, 21], [105.1, 21.1]] } }} />);
  expect(screen.queryByTestId("speedometer-readout")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-initial-marker")).not.toBeInTheDocument();
  expect(screen.getByTestId("pickup-route")).toBeInTheDocument();
  expect(screen.getByTestId("milestone-pickup")).toHaveAccessibleName(/Pickup/);
});


it("removes the legacy vehicle when backend GPS becomes explicitly empty with unchanged legacy props", () => {
  const legacyProps = { driverLocation: { longitude: 105, latitude: 21 }, currentSpeedMps: 42 };
  const { rerender } = render(<MapLibreView {...legacyProps} />);
  expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
  expect(screen.getByTestId("speedometer-readout")).toHaveTextContent("151.2 km/h");
  rerender(<MapLibreView {...legacyProps} telemetrySamples={[]} />);
  expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-initial-marker")).not.toBeInTheDocument();
  expect(screen.getByTestId("gps-unavailable-label")).toHaveTextContent("No data yet");
  expect(screen.queryByTestId("speedometer-readout")).not.toBeInTheDocument();
  rerender(<MapLibreView {...legacyProps} />);
  expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
  expect(screen.getByTestId("speedometer-readout")).toHaveTextContent("151.2 km/h");
});


it.each([true, false])("exposes null traffic as inert unavailable status even when traffic visibility is %s", (initialTraffic) => {
  render(<MapLibreView trafficCorroboration={null} initialTraffic={initialTraffic} />);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("No traffic data");
  expect(within(status).queryByRole("button")).not.toBeInTheDocument();
  expect(status).not.toHaveAttribute("tabindex");
  const traffic = screen.getByRole("button", { name: /Traffic/ });
  const probe = screen.getByRole("button", { name: /Probe Check/ });
  expect(traffic).toBeDisabled();
  expect(probe).toBeDisabled();
  expect(traffic).toHaveAccessibleDescription(/Unavailable/);
  expect(probe).toHaveAccessibleDescription(/Unavailable/);
  fireEvent.mouseEnter(screen.getByTestId("traffic-corroboration-panel"));
  fireEvent.click(probe);
  expect(screen.queryByText(/MULTI-DRIVER TRAFFIC CORROBORATION/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Clear|Congested/)).not.toBeInTheDocument();
});


it("groups missing GPS, route and traffic in one stable accessible status while seeking", () => {
  render(<MapLibreView telemetrySamples={[]} routeGeometry={{}} trafficCorroboration={null}
    timelineMilestones={[...legacyMilestones, {
      ...legacyMilestones[0], id: "destination", type: "dropoff_destination",
      timestamp: "2026-09-24T00:01:00Z", title: "Destination",
    }]} />);
  const status = screen.getByRole("status");
  expect(within(status).getByTestId("gps-unavailable-label")).toBeVisible();
  expect(within(status).getByTestId("missing-route-both")).toBeVisible();
  expect(within(status).getByTestId("traffic-corroboration-panel")).toBeVisible();
  expect(status).toHaveAttribute("aria-atomic", "true");
  expect(within(status).queryByRole("button")).not.toBeInTheDocument();
  expect(within(status).queryByRole("slider")).not.toBeInTheDocument();
  const availabilityText = status.textContent;
  fireEvent.change(screen.getByTestId("timeline-scrubber-slider"), { target: { value: "60" } });
  expect(screen.getByTestId("active-timeline-status")).toHaveTextContent("Destination");
  expect(status.textContent).toBe(availabilityText);
});


it('resets replay on a new case while preserving replay during same-case refresh', () => {
  const milestones = [...legacyMilestones, {
    ...legacyMilestones[0], id: 'destination', type: 'dropoff_destination' as const,
    timestamp: '2026-09-24T00:01:00Z', title: 'Destination',
  }];
  const { rerender } = render(<MapLibreView caseId="first" timelineMilestones={milestones} />);
  fireEvent.change(screen.getByTestId('timeline-scrubber-slider'), { target: { value: '60' } });
  expect(screen.getByTestId('timeline-scrubber-slider')).toHaveValue('60');
  rerender(<MapLibreView caseId="first" timelineMilestones={[...milestones]} />);
  expect(screen.getByTestId('timeline-scrubber-slider')).toHaveValue('60');
  rerender(<MapLibreView caseId="second" timelineMilestones={milestones} />);
  expect(screen.getByTestId('timeline-scrubber-slider')).toHaveValue('0');
});

it.each([[0, 0], [-180, -90], [180, 90]])("retains source GPS [%s, %s] and exact zero speed", (longitude, latitude) => {
  render(<MapLibreView telemetrySamples={[{
    recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [longitude, latitude, 15] }, speed_mps: 0,
  }]} currentSpeedMps={42} timelineMilestones={legacyMilestones} />);
  expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-longitude", String(longitude));
  expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-latitude", String(latitude));
  expect(screen.getByTestId("speedometer-readout")).toHaveTextContent("0.0 km/h");
  expect(screen.queryByTestId("gps-unavailable-label")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-initial-marker")).not.toBeInTheDocument();
});

it.each([undefined, 42])("retains legacy speed and milestone position when backend GPS is omitted and speed is %s", (currentSpeedMps) => {
  render(<MapLibreView currentSpeedMps={currentSpeedMps} timelineMilestones={legacyMilestones} />);
  expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-longitude", "105");
  expect(screen.getByTestId("speedometer-readout")).toHaveTextContent("151.2 km/h");
  expect(screen.queryByTestId("gps-unavailable-label")).not.toBeInTheDocument();
});

it("restores the provided traffic card and its controls when traffic becomes available", () => {
  const { rerender } = render(<MapLibreView trafficCorroboration={null} />);
  rerender(<MapLibreView trafficCorroboration={mockTrafficCorroboration} />);
  const traffic = screen.getByRole("button", { name: /Traffic/ });
  const probe = screen.getByRole("button", { name: /Probe Check/ });
  expect(traffic).toBeEnabled();
  expect(probe).toBeEnabled();
  expect(screen.queryByText("No traffic data")).not.toBeInTheDocument();
  expect(screen.getByTestId("ambient-traffic-status")).toHaveTextContent(`${mockTrafficCorroboration.public_service.average_speed_kmh} km/h`);
  fireEvent.mouseEnter(screen.getByTestId("traffic-corroboration-panel"));
  expect(screen.getByText("MULTI-DRIVER TRAFFIC CORROBORATION")).toBeVisible();
  expect(screen.getByText(mockTrafficCorroboration.road_segment)).toBeVisible();
  fireEvent.mouseLeave(screen.getByTestId("traffic-corroboration-panel"));
  fireEvent.click(probe);
  expect(screen.getByText("MULTI-DRIVER TRAFFIC CORROBORATION")).toBeVisible();
  rerender(<MapLibreView trafficCorroboration={null} />);
  expect(screen.getByRole("status")).toHaveTextContent("No traffic data");
  expect(probe).toBeDisabled();
  expect(screen.queryByText("MULTI-DRIVER TRAFFIC CORROBORATION")).not.toBeInTheDocument();
});


it.each([
  { name: "empty", samples: [] },
  { name: "invalid", samples: [{
    recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [200, 100] },
  }] },
])("removes legacy measurements and bounds when backend GPS becomes $name", ({ samples }) => {
  const legacyProps = {
    driverBreadcrumbs: [[170, -60], [171, -61]] as [number, number][],
    driverLocation: { longitude: 171, latitude: -61 },
  };
  const { rerender } = render(<MapLibreView {...legacyProps} />);
  expect(screen.getByTestId("driver-trajectory")).toHaveAttribute("data-point-count", "2");
  expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Center whole trip" })).toBeEnabled();

  rerender(<MapLibreView {...legacyProps} telemetrySamples={samples} />);
  expect(screen.queryByTestId("driver-trajectory")).not.toBeInTheDocument();
  expect(screen.queryByTestId("observed-gps-fix")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-initial-marker")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Center whole trip" })).toBeDisabled();
  expect(screen.getByTestId("gps-unavailable-label")).toHaveTextContent("No data yet");

  rerender(<MapLibreView {...legacyProps} telemetrySamples={samples}
    driverInitialLocation={{ longitude: 105, latitude: 21 }}
    customerLocation={{ longitude: 105.1, latitude: 21.1 }}
    destinationLocation={{ longitude: 105.2, latitude: 21.2 }} />);
  expect(screen.getByTestId("driver-initial-marker")).toHaveAttribute("transform", "translate(40.0, 220.0)");
  expect(screen.getByTestId("customer-pickup-marker")).toHaveAttribute("transform", "translate(350.0, 125.0)");
  expect(screen.getByTestId("destination-marker")).toHaveAttribute("transform", "translate(660.0, 30.0)");
  expect(screen.getByRole("button", { name: "Center whole trip" })).toBeEnabled();
  expect(screen.queryByTestId("driver-trajectory")).not.toBeInTheDocument();
  expect(screen.queryByTestId("driver-vehicle-marker")).not.toBeInTheDocument();

  rerender(<MapLibreView {...legacyProps} />);
  expect(screen.getByTestId("driver-trajectory")).toHaveAttribute("data-point-count", "2");
  expect(screen.getByTestId("driver-vehicle-marker")).toBeInTheDocument();
});


it.each((["pickup", "destination"] as const).flatMap((invalidLeg) => [
  { invalidLeg, name: "out-of-range middle vertex", coordinates: [[170, -60], [200, 100], [171, -61]] },
  { invalidLeg, name: "non-finite middle vertex", coordinates: [[170, -60], [NaN, -60.5], [171, -61]] },
  { invalidLeg, name: "one-point route", coordinates: [[170, -60]] },
]))("rejects the entire $invalidLeg leg with a $name without bridging or changing other-leg bounds", ({ invalidLeg, coordinates }) => {
  const validLeg = invalidLeg === "pickup" ? "destination" : "pickup";
  const validRoute = { coordinates: [[105, 21], [105.1, 21.1]] };
  const checkpoints = {
    driverInitialLocation: { longitude: 105, latitude: 21 },
    customerLocation: { longitude: 105.05, latitude: 21.05 },
    destinationLocation: { longitude: 105.1, latitude: 21.1 },
  };
  const { rerender } = render(<MapLibreView {...checkpoints}
    routeGeometry={{ [`${validLeg}_route`]: validRoute }} />);
  const validPath = screen.getByTestId(`${validLeg}-route`).querySelector("path")?.getAttribute("d");

  rerender(<MapLibreView {...checkpoints} routeGeometry={{
    [`${validLeg}_route`]: validRoute,
    [`${invalidLeg}_route`]: { coordinates },
  }} />);
  expect(screen.getByTestId(`missing-route-${invalidLeg}`)).toHaveTextContent("No data yet");
  expect(screen.queryByTestId(`${invalidLeg}-route`)).not.toBeInTheDocument();
  expect(screen.getByTestId(`${validLeg}-route`).querySelector("path")).toHaveAttribute("d", validPath);
  expect(screen.getByTestId("driver-initial-marker")).toHaveAttribute("transform", "translate(40.0, 220.0)");
  expect(screen.getByTestId("customer-pickup-marker")).toHaveAttribute("transform", "translate(350.0, 125.0)");
  expect(screen.getByTestId("destination-marker")).toHaveAttribute("transform", "translate(660.0, 30.0)");
});
