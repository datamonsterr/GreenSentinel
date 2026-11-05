import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MapLibreView } from "@/components/map/maplibre-view";

describe("Maps toolbar chips", () => {
  it("hides ping chip and speed chip when latency and speed values are unavailable", () => {
    render(<MapLibreView currentSpeedMps={undefined} gpsLatencyMs={undefined} telemetrySamples={[]} />);
    expect(screen.queryByTestId("gps-latency-indicator")).not.toBeInTheDocument();
    expect(screen.queryByTestId("speedometer-readout")).not.toBeInTheDocument();
  });

  it("renders ping chip and speed chip when values are provided", () => {
    render(<MapLibreView currentSpeedMps={10} gpsLatencyMs={45} />);
    expect(screen.getByTestId("gps-latency-indicator")).toBeInTheDocument();
    expect(screen.getByTestId("gps-latency-indicator")).toHaveTextContent("45ms");
    expect(screen.getByTestId("speedometer-readout")).toBeInTheDocument();
    expect(screen.getByTestId("speedometer-readout")).toHaveTextContent("36.0 km/h");
  });
});
