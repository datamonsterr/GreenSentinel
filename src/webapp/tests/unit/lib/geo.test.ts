import { describe, it, expect } from "vitest";
import {
  clampToRadius,
  haversineDistanceM,
  bearingDeg,
  destinationPoint,
  nearestLeg,
  createCircleCoordinates,
} from "@/lib/geo";

describe("Geospatial Utilities (geo.ts)", () => {
  const pickup = { latitude: 21.0118, longitude: 105.8497 }; // Vincom Ba Trieu
  const nearbyOrigin = { latitude: 21.02, longitude: 105.845 }; // ~1 km away
  const farOrigin = { latitude: 21.08, longitude: 105.82 }; // ~8 km away

  it("leaves coordinates unchanged when within maxM (4 km)", () => {
    const result = clampToRadius(pickup, nearbyOrigin, 4000);
    expect(result.clamped).toBe(false);
    expect(result.latitude).toBeCloseTo(nearbyOrigin.latitude, 4);
    expect(result.longitude).toBeCloseTo(nearbyOrigin.longitude, 4);
    expect(result.distanceM).toBeLessThan(4000);
  });

  it("snaps coordinates to exactly 4 km on the same bearing when outside 4 km", () => {
    const origDist = haversineDistanceM(pickup, farOrigin);
    expect(origDist).toBeGreaterThan(4000);

    const initialBearing = bearingDeg(pickup, farOrigin);

    const result = clampToRadius(pickup, farOrigin, 4000);
    expect(result.clamped).toBe(true);
    expect(result.distanceM).toBe(origDist);

    // Distance from center to snapped point must be ~4000m
    const newDist = haversineDistanceM(pickup, {
      latitude: result.latitude,
      longitude: result.longitude,
    });
    expect(newDist).toBeCloseTo(4000, -1); // within ~10 meters due to rounding

    // Bearing from center to snapped point must match initial bearing
    const newBearing = bearingDeg(pickup, {
      latitude: result.latitude,
      longitude: result.longitude,
    });
    expect(newBearing).toBeCloseTo(initialBearing, 1);
  });

  it("handles destinationPoint spherical destination correctly", () => {
    const dest = destinationPoint(pickup, 1000, 90); // 1 km due east
    const dist = haversineDistanceM(pickup, dest);
    expect(dist).toBeCloseTo(1000, -1);
    const bearing = bearingDeg(pickup, dest);
    expect(bearing).toBeCloseTo(90, 1);
  });

  it("determines nearest leg accurately (pickup vs destination)", () => {
    const origin = { latitude: 21.0285, longitude: 105.8524 }; // Hoan Kiem
    const pickupLoc = { latitude: 21.0118, longitude: 105.8497 }; // Vincom Ba Trieu
    const destination = { latitude: 21.0345, longitude: 105.8342 }; // Ba Dinh

    // Point close to origin-pickup corridor
    const pointNearPickupLeg = { latitude: 21.02, longitude: 105.851 };
    expect(nearestLeg(origin, pickupLoc, destination, pointNearPickupLeg)).toBe("pickup");

    // Point close to pickup-destination corridor
    const pointNearDestLeg = { latitude: 21.025, longitude: 105.838 };
    expect(nearestLeg(origin, pickupLoc, destination, pointNearDestLeg)).toBe("destination");
  });

  it("generates closed circle coordinate ring", () => {
    const ring = createCircleCoordinates(pickup, 4000, 16);
    expect(ring.length).toBe(17); // 16 segments + 1 closing point
    expect(ring[0][0]).toBeCloseTo(ring[16][0], 5);
    expect(ring[0][1]).toBeCloseTo(ring[16][1], 5);
  });
});
