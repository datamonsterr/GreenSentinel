import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MapLibreView } from "@/components/map/maplibre-view";

const start = Date.parse("2026-09-24T00:00:00Z");
const iso = (second: number) => new Date(start + second * 1000).toISOString();
const sample = (second: number, coordinates: number[], speed = 0) => ({
  recorded_at: iso(second),
  position: { coordinates },
  speed_mps: speed,
  leg: "pickup",
});

const midTripGap = {
  alert_id: "gap-mid",
  start_time: iso(20),
  end_time: iso(70),
  gap_duration_s: 50,
  reason: "Mạng di động (Network offline): mất tín hiệu telemetry kết nối trong 50s",
  severity: "warning" as const,
};

const terminalGap = {
  alert_id: "gap-terminal",
  start_time: iso(60),
  end_time: iso(105),
  gap_duration_s: 45,
  reason: "Tín hiệu GPS không khả dụng trong 45s",
  severity: "warning" as const,
};

interface MockLayer { id: string; type: string; paint?: Record<string, unknown> }
interface MockGeo { type: string; coordinates: unknown }
interface MockFeature { properties: Record<string, unknown>; geometry: MockGeo }
interface MockData { features?: MockFeature[]; geometry?: MockGeo }
interface MockSource { data: MockData; setData(data: MockData): void }

const map = vi.hoisted(() => ({
  sources: new Map<string, MockSource>(), layers: new Map<string, MockLayer>(),
  addSource: vi.fn(function (id: string, source: Omit<MockSource, "setData">) { map.sources.set(id, { ...source, setData(data: MockData) { this.data = data; } }); }),
  addLayer: vi.fn(function (layer: MockLayer) { map.layers.set(layer.id, layer); }),
  getSource: (id: string) => map.sources.get(id), getLayer: (id: string) => map.layers.get(id),
  on: vi.fn((event: string, callback: () => void) => { if (event === "load") queueMicrotask(callback); }),
  resize: vi.fn(), triggerRepaint: vi.fn(), remove: vi.fn(), setStyle: vi.fn(), setLayoutProperty: vi.fn(), setPaintProperty: vi.fn(), fitBounds: vi.fn(),
}));
vi.mock("maplibre-gl", () => ({
  setWorkerUrl: vi.fn(),
  Map: class { constructor() { return map; } },
  Marker: class { setLngLat() { return this; } addTo() { return this; } remove() {} },
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("MapLibreView gap indicators", () => {
  it("renders a red dashed band with explanatory timestamps and reason for each gap", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(10, [105.001, 21]), sample(80, [105.002, 21.001])]}
      missingnessAlerts={[midTripGap]}
    />);

    const band = screen.getByTestId("timeline-gap-band");
    expect(band).toBeVisible();
    expect(band).toHaveAttribute("aria-label", expect.stringContaining("00:00:20"));
    expect(band).toHaveAttribute("aria-label", expect.stringContaining("00:01:10"));
    expect(band).toHaveAttribute("aria-label", expect.stringContaining("50s"));
    expect(band).toHaveAttribute("aria-label", expect.stringContaining("Network offline"));
    expect(band).toHaveStyle({ borderTop: "2px dashed #dc2626", borderBottom: "2px dashed #dc2626" });
    expect(band.style.background).toContain("repeating-linear-gradient");
    expect(band.closest('[data-testid="timeline-gap-bands"]')).toHaveClass("pointer-events-none");
  });

  it("hides every gap indicator when no gap exists", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(10, [105.001, 21]), sample(80, [105.002, 21.001])]}
    />);

    expect(screen.queryByTestId("timeline-gap-bands")).not.toBeInTheDocument();
    expect(screen.queryByTestId("timeline-gap-band")).not.toBeInTheDocument();
    expect(screen.queryByTestId("timeline-gap-info")).not.toBeInTheDocument();
    expect(screen.queryByTestId("timeline-gap-tooltip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("gap-warning-marker")).not.toBeInTheDocument();
    expect(screen.getByTestId("timeline-scrubber-slider")).not.toHaveAttribute("aria-describedby");
  });

  it("exposes gap timestamps, duration and reason through an accessible tooltip", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(60, [105.002, 21.001])]}
      missingnessAlerts={[terminalGap]}
    />);

    const tooltip = screen.getByTestId("timeline-gap-tooltip");
    expect(tooltip).not.toHaveAttribute("role", "status");
    expect(tooltip).toHaveAttribute("id", "gap-info-gap-terminal");
    expect(tooltip).toHaveTextContent("00:01:00");
    expect(tooltip).toHaveTextContent("00:01:45");
    expect(tooltip).toHaveTextContent("45s");
    expect(tooltip).toHaveTextContent("Tín hiệu GPS không khả dụng");
    expect(tooltip).not.toHaveAttribute("tabindex");
    expect(screen.getByTestId("timeline-scrubber-slider")).toHaveAttribute("aria-describedby", "gap-info-gap-terminal");
  });

  it("describes the native scrubber with one persistent passive explanation", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(60, [105.002, 21.001])]}
      missingnessAlerts={[terminalGap]}
    />);

    const explanation = screen.getByTestId("timeline-gap-tooltip");
    const scrubber = screen.getByTestId("timeline-scrubber-slider");
    expect(explanation).toHaveAttribute("id", "gap-info-gap-terminal");
    expect(scrubber).toHaveAttribute("aria-describedby", "gap-info-gap-terminal");
    expect(explanation).not.toHaveAttribute("role", "status");
    expect(explanation).not.toHaveAttribute("tabindex");
    for (const id of screen.getByTestId("timeline-scrubber-slider").getAttribute("aria-describedby")!.split(" ")) {
      expect(document.getElementById(id)).toBe(explanation);
    }
  });

  it("keeps mobile gap labels compact while exposing the full reason accessibly", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(60, [105.002, 21.001])]}
      missingnessAlerts={[terminalGap]}
    />);

    const explanation = screen.getByTestId("timeline-gap-tooltip");
    expect(screen.getByTestId("timeline-scrubber-slider")).toHaveAttribute("aria-describedby", "gap-info-gap-terminal");
    expect(screen.getByTestId("timeline-gap-info")).toHaveClass("min-w-0", "max-w-full", "overflow-hidden");
    expect(explanation).toHaveTextContent("00:01:00–00:01:45 · 45s");
    expect(explanation).toHaveTextContent("Tín hiệu GPS không khả dụng");
    expect(explanation.querySelector(".sm\\:sr-only")).toHaveTextContent("00:01:00");
    expect(explanation.querySelector(".sr-only.sm\\:not-sr-only")).toHaveTextContent("Tín hiệu GPS không khả dụng");
  });

  it("uses duration and source-safe wording without overstating short or unknown gaps", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(10, [105.002, 21.001])]}
      missingnessAlerts={[{
        ...terminalGap,
        alert_id: "short-gap",
        start_time: iso(0),
        end_time: iso(10),
        gap_duration_s: 10,
        reason: "Nguồn dữ liệu không rõ",
      }]}
    />);

    const explanation = screen.getByTestId("timeline-gap-tooltip");
    expect(explanation).toHaveTextContent("10s");
    expect(explanation).not.toHaveTextContent("Mất kết nối");
    expect(explanation).not.toHaveTextContent(">30s");
  });

  it("preserves fractional durations and source timestamps while skipping invalid gaps", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(80, [105.002, 21.001])]}
      missingnessAlerts={[
        { ...midTripGap, alert_id: "fraction", start_time: iso(20), end_time: iso(50.001), gap_duration_s: 30.001 },
        { ...midTripGap, alert_id: "reversed", start_time: iso(60), end_time: iso(50), gap_duration_s: 10 },
        { ...midTripGap, alert_id: "zero", start_time: iso(70), end_time: iso(70), gap_duration_s: 0 },
        { ...midTripGap, alert_id: "invalid", start_time: "bad", end_time: iso(30), gap_duration_s: 10 },
      ]}
    />);

    expect(screen.getByTestId("timeline-gap-tooltip")).toHaveTextContent("30.001s");
    expect(screen.getByTestId("timeline-gap-tooltip")).toHaveTextContent("00:00:20");
    expect(screen.getByTestId("timeline-gap-tooltip")).toHaveTextContent("00:00:50");
    expect(screen.getByTestId("timeline-gap-band")).toHaveAttribute("aria-label", expect.stringContaining("30.001s"));
    expect(screen.getAllByTestId("timeline-gap-tooltip")).toHaveLength(1);
    expect(screen.getAllByTestId("timeline-gap-band")).toHaveLength(1);
  });

  it("never renders the gap band or markers as part of the measured trail", () => {
    const samples = [sample(0, [105, 21]), sample(10, [105.001, 21]), sample(80, [105.002, 21.001])];
    const route = { pickup_route: { coordinates: [[105, 21], [105.001, 21], [105.002, 21.001]] } };
    const { rerender } = render(<MapLibreView telemetrySamples={samples} routeGeometry={route} />);
    fireEvent.change(screen.getByTestId("timeline-scrubber-slider"), { target: { value: "10" } });
    const pathWithoutGap = screen.getByTestId("driver-trajectory").querySelector("path")?.getAttribute("d");
    expect(pathWithoutGap).toBeDefined();

    rerender(<MapLibreView telemetrySamples={samples} routeGeometry={route} missingnessAlerts={[midTripGap]} />);
    const trailWithGap = screen.getByTestId("driver-trajectory");
    expect(trailWithGap.querySelector("path")?.getAttribute("d")).toBe(pathWithoutGap);
    expect(trailWithGap.querySelector('[data-testid="timeline-gap-band"]')).toBeNull();
    expect(trailWithGap.querySelector('[data-testid="gap-warning-marker"]')).toBeNull();
    expect(screen.getByTestId("timeline-gap-band")).toBeInTheDocument();
  });

  it("marks gap endpoints at recorded fixes with tooltips, without bridging geometry", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(10, [105.001, 21]), sample(80, [105.002, 21.001])]}
      routeGeometry={{ pickup_route: { coordinates: [[105, 21], [105.001, 21], [105.002, 21.001]] } }}
      missingnessAlerts={[midTripGap]}
    />);
    fireEvent.change(screen.getByTestId("timeline-scrubber-slider"), { target: { value: "10" } });

    const markers = screen.getAllByTestId("gap-warning-marker");
    expect(markers).toHaveLength(2);
    for (const marker of markers) {
      const circle = marker.querySelector("circle");
      expect(circle).toHaveAttribute("stroke", "#dc2626");
      expect(circle).toHaveAttribute("stroke-dasharray", "3 2");
      expect(marker.querySelector("title")).toHaveTextContent("00:00:20");
      expect(marker.querySelector("title")).toHaveTextContent("00:01:10");
      expect(marker.querySelector("title")).toHaveTextContent("Network offline");
    }
    expect(screen.getByTestId("driver-trajectory").querySelectorAll("path")).toHaveLength(1);
  });

  it("extends the timeline over a terminal gap and holds the last recorded fix inside it", () => {
    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(60, [105.002, 21.001])]}
      missingnessAlerts={[terminalGap]}
    />);

    const scrubber = screen.getByTestId("timeline-scrubber-slider") as HTMLInputElement;
    expect(scrubber.max).toBe("105");
    expect(screen.getByTestId("timeline-end-time")).toHaveTextContent("00:01:45");
    expect(screen.getByTestId("timeline-gap-band")).toBeInTheDocument();

    fireEvent.change(scrubber, { target: { value: "80" } });
    expect(screen.getByTestId("playback-quality")).toHaveAttribute("data-mode", "gap");
    expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-longitude", "105.002");
    expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-latitude", "21.001");
    expect(screen.getByTestId("driver-vehicle-marker")).toHaveAttribute("data-playback-mode", "gap");
  });
});

describe("MapLibreView gap warnings map layer", () => {
  afterEach(() => {
    map.sources.clear();
    map.layers.clear();
  });

  it("uses a dedicated source and layer for gap warnings, separate from the trajectory line", async () => {
    vi.stubGlobal("WebGLRenderingContext", class {});
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as RenderingContext);

    render(<MapLibreView
      telemetrySamples={[sample(0, [105, 21]), sample(10, [105.001, 21]), sample(80, [105.002, 21.001])]}
      routeGeometry={{ pickup_route: { coordinates: [[105, 21], [105.001, 21], [105.002, 21.001]] } }}
      missingnessAlerts={[midTripGap]}
    />);

    await waitFor(() => expect(map.getSource("gap-warnings-source")).toBeDefined());
    const gapLayer = map.getLayer("gap-warnings");
    expect(gapLayer).toBeDefined();
    if (!gapLayer) throw new Error("gap-warnings layer was not created");
    expect(gapLayer.type).toBe("circle");
    expect(gapLayer.paint).toMatchObject({ "circle-stroke-color": "#dc2626", "circle-stroke-width": 2 });
    const gapSource = map.getSource("gap-warnings-source");
    expect(gapSource).toBeDefined();
    if (!gapSource) throw new Error("gap-warnings source was not created");
    const features = gapSource.data.features ?? [];
    expect(features).toHaveLength(2);
    expect(features.map((feature) => feature.properties?.gap_role).sort()).toEqual(["gap_end", "gap_start"]);
    for (const feature of features) {
      expect(feature.geometry.type).toBe("Point");
      expect(feature.properties?.alert_id).toBe("gap-mid");
      expect(feature.properties?.reason).toContain("Network offline");
      expect([[105.001, 21], [105.002, 21.001]]).toEqual(expect.arrayContaining([feature.geometry.coordinates]));
    }
    expect(features.every((feature) => feature.geometry.type === "Point")).toBe(true);

    fireEvent.change(screen.getByTestId("timeline-scrubber-slider"), { target: { value: "10" } });
    const trajectorySource = map.getSource("driver-trajectory-source");
    expect(trajectorySource).toBeDefined();
    if (!trajectorySource) throw new Error("driver trajectory source was not created");
    const trajectory = trajectorySource.data.geometry!;
    expect(trajectory.coordinates).toEqual([[105, 21], [105.001, 21]]);
    expect(JSON.stringify(trajectory)).not.toContain("105.002");
  });
});
