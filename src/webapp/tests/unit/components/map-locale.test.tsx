import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MapLibreView } from "@/components/map/maplibre-view";
import { LocaleProvider, useLocale } from "@/lib/locale";

function LocaleSwitch() {
  const { setLocale } = useLocale();
  return <button type="button" onClick={() => setLocale("vi")}>switch vi</button>;
}

describe("MapLibreView locale", () => {
  it("uses English by default and translates visible fallback controls", () => {
    render(<MapLibreView telemetrySamples={[]} trafficCorroboration={null} />);

    expect(screen.getByRole("button", { name: "Center whole trip" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Traffic" })).toBeInTheDocument();
    expect(screen.getByText("No trip data")).toBeInTheDocument();
    expect(screen.getByText("No traffic data")).toBeInTheDocument();
  });

  it("updates visible labels in place when locale changes", () => {
    render(
      <LocaleProvider>
        <LocaleSwitch />
        <MapLibreView telemetrySamples={[]} trafficCorroboration={null} />
      </LocaleProvider>,
    );

    const map = screen.getByTestId("maplibre-view");
    fireEvent.click(screen.getByRole("button", { name: "switch vi" }));

    expect(screen.getByRole("button", { name: "Căn giữa toàn bộ chuyến đi" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Giao thông" })).toBeInTheDocument();
    expect(screen.getByText("Chưa có dữ liệu hành trình")).toBeInTheDocument();
    expect(map).toBeInTheDocument();
  });
});
