import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MapLibreView } from "@/components/map/maplibre-view";
import { describe, expect, it } from "vitest";

describe("MapLibreView replay layout", () => {
  it("keeps speed and scrubber in replay toolbar while chips stay in map controls", () => {
    render(<MapLibreView currentSpeedMps={12.5} gpsLatencyMs={42} telemetrySamples={[
      { recorded_at: "2026-09-24T00:00:00Z", position: { coordinates: [105, 21] }, speed_mps: 12.5 },
      { recorded_at: "2026-09-24T00:01:00Z", position: { coordinates: [105.01, 21.01] } },
    ]} />);
    const toolbar = screen.getByTestId("trip-timeline-bar");
    expect(within(toolbar).getByTestId("speedometer-readout")).toBeInTheDocument();
    expect(within(toolbar).getByTestId("timeline-scrubber-slider")).toBeInTheDocument();
    const controls = screen.getByTestId("map-control-chips");
    expect(within(controls).getByTestId("gps-latency-indicator")).toBeInTheDocument();
    expect(within(toolbar).queryByTestId("gps-latency-indicator")).not.toBeInTheDocument();
  });
});

describe("MapLibreView traffic panel resilience", () => {
  it("renders a partial traffic corroboration payload without throwing", () => {
    expect(() =>
      render(<MapLibreView trafficCorroboration={{ verdict: "inconclusive" } as never} />),
    ).not.toThrow();
  });
});
