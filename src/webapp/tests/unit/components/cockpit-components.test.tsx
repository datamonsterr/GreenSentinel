import React from "react";
import { render, screen, within } from "@testing-library/react";
import { Activity } from "lucide-react";
import { describe, expect, it } from "vitest";
import { LocaleProvider } from "@/lib/locale";
import { MetricGrid, metricGridSpans } from "@/components/cockpit/metric-grid";
import { MetricCard } from "@/components/cockpit/metric-card";
import { EmptyState } from "@/components/cockpit/empty-state";
import { TripStatusRow } from "@/components/cockpit/trip-status-row";
import { ChatThread } from "@/components/cockpit/chat-thread";
import { EventTimeline } from "@/components/cockpit/event-timeline";

describe("metricGridSpans", () => {
  it("fills full rows of three with equal thirds", () => {
    expect(metricGridSpans(3)).toEqual([4, 4, 4]);
    expect(metricGridSpans(6)).toEqual([4, 4, 4, 4, 4, 4]);
  });

  it("stretches a trailing row of two to half width each", () => {
    expect(metricGridSpans(5)).toEqual([4, 4, 4, 6, 6]);
    expect(metricGridSpans(2)).toEqual([6, 6]);
  });

  it("stretches a single trailing card to full width", () => {
    expect(metricGridSpans(4)).toEqual([4, 4, 4, 12]);
    expect(metricGridSpans(1)).toEqual([12]);
  });

  it("supports a four-up row for driver top stats", () => {
    expect(metricGridSpans(4, 4)).toEqual([3, 3, 3, 3]);
    expect(metricGridSpans(6, 4)).toEqual([3, 3, 3, 3, 6, 6]);
  });

  it("returns nothing for an empty grid", () => {
    expect(metricGridSpans(0)).toEqual([]);
  });
});

describe("MetricGrid", () => {
  it("applies the computed span to every cell", () => {
    render(
      <MetricGrid>
        {["a", "b", "c", "d", "e"].map(key => <div key={key}>{key}</div>)}
      </MetricGrid>,
    );
    const spans = ["a", "b", "c", "d", "e"].map(key => screen.getByText(key).parentElement?.getAttribute("data-span"));
    expect(spans).toEqual(["4", "4", "4", "6", "6"]);
  });

  it("ignores null children when computing rows", () => {
    render(<MetricGrid>{[<div key="a">a</div>, null, <div key="b">b</div>]}</MetricGrid>);
    expect(screen.getByText("a").parentElement).toHaveAttribute("data-span", "6");
    expect(screen.getByText("b").parentElement).toHaveAttribute("data-span", "6");
  });
});

describe("MetricCard", () => {
  it("puts the value beside the icon with the label under the value", () => {
    render(<MetricCard icon={Activity} label="Total trips" value="1,730" hint="Lifetime completed trips" />);
    const card = screen.getByRole("group", { name: "Total trips: 1,730" });
    expect(card).toHaveAttribute("title", "Lifetime completed trips");
    expect(within(card).getByText("1,730")).toHaveClass("tabular-nums");
    expect(within(card).getByText("Total trips")).toBeInTheDocument();
  });

  it("renders the designed empty value instead of undefined or Unavailable", () => {
    render(<LocaleProvider><MetricCard icon={Activity} label="Average speed" value={null} /></LocaleProvider>);
    expect(screen.getByText("No data yet")).toBeInTheDocument();
    expect(screen.queryByText(/undefined|Unavailable/)).not.toBeInTheDocument();
  });

  it("renders text values compactly with wrap-to-two-lines and a full-value tooltip", () => {
    render(<MetricCard icon={Activity} variant="text" label="Road segment" value="Giải Phóng – Vành đai 2 (southbound service lane)" />);
    const value = screen.getByText("Giải Phóng – Vành đai 2 (southbound service lane)");
    expect(value).toHaveClass("line-clamp-2", "font-semibold");
    expect(value).not.toHaveClass("truncate", "text-2xl");
    expect(value).toHaveAttribute("title", "Giải Phóng – Vành đai 2 (southbound service lane)");
  });

  it("keeps numeric values in the large figure style", () => {
    render(<MetricCard icon={Activity} label="Average speed" value="18 km/h" />);
    expect(screen.getByText("18 km/h")).toHaveClass("text-2xl", "font-bold", "tabular-nums");
  });

  it("colors the value only when a severity is flagged", () => {
    const { rerender } = render(<MetricCard icon={Activity} label="DAVI" value="0.19" />);
    expect(screen.getByText("0.19").className).not.toMatch(/text-(red|amber|emerald)-/);
    rerender(<MetricCard icon={Activity} label="DAVI" value="0.19" severity="danger" />);
    expect(screen.getByText("0.19").className).toMatch(/text-red-/);
  });
});

describe("EmptyState", () => {
  it("defaults to No data yet with a hint", () => {
    render(<LocaleProvider><EmptyState hint="Speed samples appear when telemetry arrives." /></LocaleProvider>);
    expect(screen.getByRole("status")).toHaveTextContent("No data yet");
    expect(screen.getByText("Speed samples appear when telemetry arrives.")).toBeInTheDocument();
  });

  it("localizes the default title in Vietnamese", () => {
    window.localStorage.setItem("greensentinel.locale", "vi");
    render(<LocaleProvider><EmptyState /></LocaleProvider>);
    expect(screen.getByRole("status")).toHaveTextContent("Chưa có dữ liệu");
    window.localStorage.clear();
  });
});

const trip = {
  id: "018f2f4e-a000-7000-8000-000000000068",
  pickup_address: "78 Giải Phóng, Đống Đa",
  dropoff_address: "Duy Tân, Cầu Giấy",
  driver_status: "active",
  match_type: "auto",
  fare_amount_vnd: 300000,
};

describe("TripStatusRow", () => {
  it("keeps route, badges, fare and the case-ID chip on one line in that order", () => {
    render(<LocaleProvider><TripStatusRow caseDetail={{ trip } as any} /></LocaleProvider>);
    const row = screen.getByTestId("trip-status-row");
    expect(row).toHaveClass("flex-nowrap");
    const text = row.textContent ?? "";
    const order = ["78 Giải Phóng", "Duy Tân", "Active", "300,000 ₫", "018f2f4e"].map(part => text.indexOf(part));
    expect(order.every(index => index >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(within(row).getByRole("button", { name: `Trip ID: ${trip.id}` })).toBeInTheDocument();
  });

  it("truncates the route with a full-text tooltip", () => {
    render(<LocaleProvider><TripStatusRow caseDetail={{ trip } as any} /></LocaleProvider>);
    const route = screen.getByTitle("78 Giải Phóng, Đống Đa → Duy Tân, Cầu Giấy");
    expect(route.querySelector(".truncate")).not.toBeNull();
  });

  it("shows No data yet for missing addresses and fare", () => {
    render(<LocaleProvider><TripStatusRow caseDetail={{ trip: { id: "T-1" } } as any} /></LocaleProvider>);
    const row = screen.getByTestId("trip-status-row");
    expect(row).toHaveTextContent("No data yet");
    expect(row).not.toHaveTextContent(/undefined|Unavailable/);
  });
});

describe("ChatThread", () => {
  const messages = [
    { role: "customer" as const, text: "Anh ơi anh đến đâu rồi ạ?", occurred_at: "2026-10-20T10:19:15Z" },
    { role: "driver" as const, text: "Anh đang kẹt xe ở Giải Phóng", occurred_at: "2026-10-20T10:20:02Z" },
  ];

  it("aligns customer bubbles right and driver bubbles left", () => {
    render(<LocaleProvider><ChatThread messages={messages} driverLabel="Trần Ngọc Long" /></LocaleProvider>);
    expect(screen.getByText(messages[0].text).closest("[data-align]")).toHaveAttribute("data-align", "right");
    expect(screen.getByText(messages[1].text).closest("[data-align]")).toHaveAttribute("data-align", "left");
  });

  it("is a scrollable log with an empty state when no messages exist", () => {
    render(<LocaleProvider><ChatThread messages={[]} driverLabel="Driver" /></LocaleProvider>);
    expect(screen.getByRole("log")).toHaveClass("overflow-y-auto");
    expect(screen.getByRole("status")).toHaveTextContent("No data yet");
  });
});

describe("EventTimeline", () => {
  it("shows each status with its duration until the next status and highlights cancel events", () => {
    const events = [
      { id: "a", label: "Driver assigned", timestamp: "2026-10-20T10:19:00Z", tone: "info" as const },
      { id: "b", label: "Driving to pickup", timestamp: "2026-10-20T10:20:10Z", tone: "success" as const },
      { id: "c", label: "Cancelled", timestamp: "2026-10-20T10:22:15Z", tone: "danger" as const, highlight: true },
    ];
    render(<LocaleProvider><EventTimeline events={events} /></LocaleProvider>);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("1m 10s");
    expect(items[1]).toHaveTextContent("2m 5s");
    expect(items[2]).toHaveAttribute("data-highlight", "true");
  });
});
