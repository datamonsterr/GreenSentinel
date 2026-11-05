import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchCaseDriverScorecard, fetchDriverScorecard } from "@/lib/api-client";

describe("scorecard api-client (issue #100)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("fetches driver scorecard from the driver route", async () => {
    const payload = {
      driver_id: "DRV-1",
      violation_ratio_90d: 3.8,
      benchmark_violation_ratio: 5.0,
      fined_ratio: 50.0,
      repeat_offense_risk_score: 78,
      tenure_months: 16,
      past_incidents: [],
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });

    const data = await fetchDriverScorecard("DRV-1");

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/drivers/DRV-1/scorecard"),
      expect.objectContaining({ method: "GET" })
    );
    expect(data).toEqual(payload);
  });

  it("fetches driver scorecard from the case alias route", async () => {
    const payload = {
      driver_id: "DRV-1",
      violation_ratio_90d: 0.0,
      benchmark_violation_ratio: 5.0,
      fined_ratio: 0.0,
      repeat_offense_risk_score: 10,
      tenure_months: 0,
      past_incidents: [],
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });

    const data = await fetchCaseDriverScorecard("case-1");

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/cases/case-1/driver-scorecard"),
      expect.objectContaining({ method: "GET" })
    );
    expect(data.past_incidents).toEqual([]);
  });

  it("surfaces backend error detail on scorecard failure", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({ detail: "Scorecard database unavailable" }),
    });

    await expect(fetchDriverScorecard("DRV-1")).rejects.toThrow(
      "API Error 503: Scorecard database unavailable"
    );
  });
});
