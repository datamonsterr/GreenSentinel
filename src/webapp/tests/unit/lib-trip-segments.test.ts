import { describe, expect, it } from "vitest";
import { classifyTripSegments, clipSegmentsAt, distanceToPolylineM, plannedSegment } from "@/lib/trip-segments";

const fix = (lon: number, lat: number, sec: number | null) => ({
  position: lon == null ? null : { coordinates: [lon, lat] },
  recorded_at: sec == null ? undefined : new Date(Date.UTC(2026, 0, 1, 0, 0, sec)).toISOString(),
});
const dropout = (sec: number) => ({ position: { coordinates: [null, null] }, recorded_at: new Date(Date.UTC(2026, 0, 1, 0, 0, sec)).toISOString() });
const planned: [number, number][] = [[105, 21], [105.01, 21]];

describe("classifyTripSegments", () => {
  it("merges on-route fixes into one actual segment", () => {
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.003, 21, 5), fix(105.006, 21, 10)], planned });
    expect(segs).toHaveLength(1);
    expect(segs[0].kind).toBe("actual");
    expect(segs[0].coords).toHaveLength(3);
    expect(segs[0].distanceM).toBeGreaterThan(500);
    expect(segs[0].avgSpeedKmh).toBeGreaterThan(0);
  });

  it("marks edges far from the planned route as offroute", () => {
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.003, 21, 5), fix(105.004, 21.01, 10), fix(105.005, 21.02, 15)], planned });
    expect(segs.map((s) => s.kind)).toEqual(["actual", "offroute"]);
  });

  it("bridges null-coordinate dropouts with a gap segment and never crashes", () => {
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), dropout(5), dropout(10), fix(105.004, 21, 15), fix(105.005, 21, 20)], planned });
    expect(segs.map((s) => s.kind)).toEqual(["gap", "actual"]);
    expect(segs[0].coords).toEqual([[105, 21], [105.004, 21]]);
  });

  it("handles leading/trailing/all-null samples", () => {
    expect(classifyTripSegments({ samples: [dropout(0), dropout(5)], planned })).toEqual([]);
    const segs = classifyTripSegments({ samples: [dropout(0), fix(105, 21, 5), fix(105.001, 21, 10), dropout(15)] });
    expect(segs.map((s) => s.kind)).toEqual(["actual"]);
  });

  it("uses recorded gap windows and long time holes", () => {
    const gaps = [{ start_time: new Date(Date.UTC(2026, 0, 1, 0, 0, 8)).toISOString(), end_time: new Date(Date.UTC(2026, 0, 1, 0, 0, 12)).toISOString(), reason: "network offline" }];
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.001, 21, 5), fix(105.002, 21, 15), fix(105.003, 21, 20)], planned, gaps });
    expect(segs.map((s) => s.kind)).toEqual(["actual", "gap", "actual"]);
    expect(segs[1].reason).toBe("network offline");
    const holes = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.001, 21, 120)], planned });
    expect(holes[0].kind).toBe("gap");
  });

  it("marks movement after cancellation", () => {
    const cancelAtMs = Date.UTC(2026, 0, 1, 0, 0, 10);
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.002, 21, 10), fix(105.004, 21, 15), fix(105.006, 21, 20)], planned, cancelAtMs });
    expect(segs.map((s) => s.kind)).toEqual(["actual", "postcancel"]);
  });

  it("tolerates identical timestamps and missing timestamps", () => {
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.001, 21, 0), fix(105.002, 21, null)], planned });
    expect(segs).toHaveLength(1);
  });
});

describe("helpers", () => {
  it("clips segments at the playhead", () => {
    const segs = classifyTripSegments({ samples: [fix(105, 21, 0), fix(105.001, 21, 5), fix(105.002, 21, 10)], planned });
    expect(clipSegmentsAt(segs, Date.UTC(2026, 0, 1, 0, 0, 5))[0].coords).toHaveLength(2);
    expect(clipSegmentsAt(segs, Date.UTC(2026, 0, 1, 0, 0, 1))).toEqual([]);
    expect(clipSegmentsAt(segs, Infinity)).toEqual(segs);
  });
  it("measures distance to polyline and builds planned segment", () => {
    expect(distanceToPolylineM([105.005, 21], planned)).toBeLessThan(1);
    expect(distanceToPolylineM([105.005, 21.001], planned)).toBeGreaterThan(100);
    expect(plannedSegment(planned)?.kind).toBe("planned");
    expect(plannedSegment([])).toBeNull();
  });
});
