import { describe, it, expect } from "vitest";
import { getHypothesisEvidence } from "@/lib/adjudication-data-adapter";

describe("getHypothesisEvidence sensor passthrough (issue #100 P1)", () => {
  const baseDetail: any = {
    telemetry_samples: [
      {
        davi_score: 0.71,
        drift_distance_m: 14.5,
        gps_accuracy_m: 4.2,
        gps_state: "valid",
        mock_location_reported: false,
        ping_latency_ms: 42,
        battery_level_pct: 84,
      },
    ],
    features: {},
    missingness_alerts: [],
    case: { category: "ERR-01", confidence: 0.84 },
  };

  it("reads drift, ping latency and battery from live telemetry samples", () => {
    const evidence = getHypothesisEvidence(baseDetail);

    expect(evidence.drift_distance_m).toBe(14.5);
    expect(evidence.ping_latency_ms).toBe(42);
    expect(evidence.battery_level_pct).toBe(84);
    expect(evidence.device_integrity).toBe("verified");
  });

  it("falls back to feature flags when sample fields are absent", () => {
    const evidence = getHypothesisEvidence({
      ...baseDetail,
      telemetry_samples: [{}],
      features: { drift_distance_m: 9.5, ping_latency_ms: 55, battery_level_pct: 61 },
    });

    expect(evidence.drift_distance_m).toBe(9.5);
    expect(evidence.ping_latency_ms).toBe(55);
    expect(evidence.battery_level_pct).toBe(61);
  });

  it("stays null-safe with no telemetry at all", () => {
    const evidence = getHypothesisEvidence({ telemetry_samples: [], features: {}, case: {} } as any);

    expect(evidence.drift_distance_m).toBeNull();
    expect(evidence.ping_latency_ms).toBeNull();
    expect(evidence.battery_level_pct).toBeNull();
    expect(evidence.device_integrity).toBe("unknown");
  });
});
