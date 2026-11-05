import { describe, expect, it } from "vitest";
import {
  daviScore,
  mockLocationRatio,
  relayTurns,
  segmentDurations,
  speedComparison,
  speedMarkers,
  speedSeries,
  tripTimeline,
  willingnessEvidence,
  willingnessMetrics,
} from "@/lib/cockpit-signals";

const at = (seconds: number) => new Date(Date.UTC(2026, 9, 20, 10, 19, seconds)).toISOString();

describe("speedSeries", () => {
  it("converts m/s samples to km/h, drops unusable samples and sorts by time", () => {
    const series = speedSeries([
      { recorded_at: at(20), speed_mps: 10 },
      { recorded_at: at(10), speed_kmh: 18 },
      { recorded_at: "not-a-date", speed_mps: 3 },
      { recorded_at: at(30) },
    ]);
    expect(series.map(point => point.speed)).toEqual([18, 36]);
  });
});

describe("speedMarkers", () => {
  it("marks stall milestones as stops and anomalous DAVI milestones as deviations", () => {
    const series = speedSeries([{ recorded_at: at(0), speed_mps: 5 }, { recorded_at: at(40), speed_mps: 0 }]);
    const markers = speedMarkers([
      { id: "s", timestamp: at(40), type: "stall_anomaly", title: "Stop", description: "" },
      { id: "d", timestamp: at(0), type: "speed_anomaly", title: "Heading drift", description: "", davi: 0.18, is_anomaly: true },
      { id: "p", timestamp: at(5), type: "pickup", title: "Pickup", description: "" },
    ], series);
    expect(markers.map(marker => [marker.kind, marker.speed])).toEqual([["stop", 0], ["davi", 18]]);
  });
});

describe("daviScore", () => {
  it("prefers measured features and rejects values outside [-1, 1]", () => {
    expect(daviScore({ features: { davi_score: 0.187 } } as any)).toBe(0.187);
    expect(daviScore({ features: { davi_score: 7 } } as any)).toBeNull();
    expect(daviScore({ case: {} } as any)).toBeNull();
  });

  it("falls back to the latest stall DAVI point, including negative scores", () => {
    expect(daviScore({ cockpit_evidence: { stall_davi_points: [{ davi: -0.42 }, { davi: -0.3 }] } } as any)).toBe(-0.3);
  });
});

describe("mockLocationRatio", () => {
  it("counts only samples that carry the mock-location flag", () => {
    expect(mockLocationRatio([{ mock_location_reported: true }, { mock_location_reported: false }, {}, { mock_location_reported: false }]))
      .toEqual({ flagged: 1, total: 3, ratio: 1 / 3 });
    expect(mockLocationRatio([{}, {}])).toBeNull();
  });
});

describe("speedComparison", () => {
  it("keeps only measured speeds and averages peer vehicles", () => {
    const rows = speedComparison({
      traffic_corroboration: {
        suspect_driver: { speed_kmh: 42 },
        public_service: { average_speed_kmh: undefined },
        peer_drivers: [{ speed_kmh: 20 }, { speed_kmh: 25 }],
      },
    } as any);
    expect(rows).toEqual([{ key: "trip", speed: 42 }, { key: "peers", speed: 22.5 }]);
    expect(speedComparison({} as any)).toEqual([]);
  });
});

describe("tripTimeline", () => {
  it("orders milestones and appends the recorded cancellation as a highlighted event", () => {
    const events = tripTimeline({
      timeline_milestones: [
        { id: "b", timestamp: at(70), type: "pickup", title: "Pickup", description: "" },
        { id: "a", timestamp: at(0), type: "start_match", title: "Matched", description: "" },
      ],
      trip: { cancellation_reason: "Abnormal GPS coordinates", cancellation_actor: "platform", cancelled_at: at(200) },
    } as any, "Cancelled");
    expect(events.map(event => event.id)).toEqual(["a", "b", "trip-cancelled"]);
    expect(events[2]).toMatchObject({ tone: "danger", highlight: true, detail: "Abnormal GPS coordinates" });
    expect(segmentDurations(events)).toEqual([70, 130, null]);
  });

  it("is empty without milestones or a cancellation", () => {
    expect(tripTimeline({ trip: {} } as any, "Cancelled")).toEqual([]);
  });
});

describe("relay-derived willingness", () => {
  const dossier = {
    transcript: [
      { role: "agent", content: "Why were you stationary?", timestamp: at(0) },
      { role: "driver", content: "Heavy traffic", timestamp: at(30) },
      { role: "system", content: "ignored", timestamp: at(31) },
      { role: "agent", content: "Can you share a screenshot?", timestamp: at(40) },
      { role: "agent", content: "Are you there?", timestamp: at(100) },
      { role: "driver_agent", text: "Yes, sending now", timestamp: at(150) },
    ],
  } as any;

  it("measures questions answered and mean reply latency", () => {
    const turns = relayTurns(dossier);
    expect(turns).toHaveLength(5);
    expect(willingnessMetrics(turns)).toEqual({ questions: 3, answered: 2, avgResponseSeconds: 40, driverTurns: 2 });
  });

  it("quotes the latest agent question with the driver's reply", () => {
    expect(willingnessEvidence(relayTurns(dossier)).map(turn => turn.text)).toEqual(["Are you there?", "Yes, sending now"]);
  });

  it("returns null metrics without a relay transcript", () => {
    expect(willingnessMetrics(relayTurns(null))).toBeNull();
  });
});
