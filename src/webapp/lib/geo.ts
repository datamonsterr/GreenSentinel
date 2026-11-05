/**
 * Geospatial utilities for Test Console — SPEC-0130 §6.7 & Issue #459
 * Standard spherical earth model (R = 6,371,000 meters)
 */

export interface LatLng {
  latitude: number;
  longitude: number;
}

export type CoordInput =
  | LatLng
  | { lat: number; lon: number }
  | [number, number]; // [longitude, latitude] GeoJSON order

export interface ClampedResult {
  latitude: number;
  longitude: number;
  clamped: boolean;
  distanceM: number;
}

export const EARTH_RADIUS_M = 6371000.0;

export function toLatLng(input: CoordInput): LatLng {
  if (Array.isArray(input)) {
    return { longitude: input[0], latitude: input[1] };
  }
  if ("lat" in input && "lon" in input) {
    return { latitude: input.lat, longitude: input.lon };
  }
  return { latitude: input.latitude, longitude: input.longitude };
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180.0;
}

function toDeg(rad: number): number {
  return (rad * 180.0) / Math.PI;
}

/**
 * Great-circle distance between two points in meters using haversine formula.
 */
export function haversineDistanceM(p1: CoordInput, p2: CoordInput): number {
  const c1 = toLatLng(p1);
  const c2 = toLatLng(p2);

  const phi1 = toRad(c1.latitude);
  const phi2 = toRad(c2.latitude);
  const dPhi = toRad(c2.latitude - c1.latitude);
  const dLam = toRad(c2.longitude - c1.longitude);

  const a =
    Math.sin(dPhi / 2.0) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2.0) ** 2;
  const c = 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0.0, 1.0 - a)));
  return EARTH_RADIUS_M * c;
}

/**
 * Initial compass bearing (0°..360°) from start to target.
 */
export function bearingDeg(start: CoordInput, target: CoordInput): number {
  const c1 = toLatLng(start);
  const c2 = toLatLng(target);

  const phi1 = toRad(c1.latitude);
  const phi2 = toRad(c2.latitude);
  const dLam = toRad(c2.longitude - c1.longitude);

  const y = Math.sin(dLam) * Math.cos(phi2);
  const x =
    Math.cos(phi1) * Math.sin(phi2) -
    Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLam);
  const deg = toDeg(Math.atan2(y, x));
  return (deg + 360.0) % 360.0;
}

/**
 * Calculates destination point given start point, distance in meters, and bearing in degrees.
 */
export function destinationPoint(
  start: CoordInput,
  distanceM: number,
  bearing: number
): LatLng {
  const c = toLatLng(start);
  const phi1 = toRad(c.latitude);
  const lam1 = toRad(c.longitude);
  const brng = toRad(bearing);
  const delta = distanceM / EARTH_RADIUS_M;

  const sinPhi2 =
    Math.sin(phi1) * Math.cos(delta) +
    Math.cos(phi1) * Math.sin(delta) * Math.cos(brng);
  const phi2 = Math.asin(Math.max(-1.0, Math.min(1.0, sinPhi2)));

  const y = Math.sin(brng) * Math.sin(delta) * Math.cos(phi1);
  const x = Math.cos(delta) - Math.sin(phi1) * Math.sin(phi2);
  const lam2 = lam1 + Math.atan2(y, x);

  const normalizedLon = ((toDeg(lam2) + 540.0) % 360.0) - 180.0;
  return {
    latitude: Number(toDeg(phi2).toFixed(6)),
    longitude: Number(normalizedLon.toFixed(6)),
  };
}

/**
 * Pure 4 km proximity rule helper:
 * If point is within maxM of center, returns unchanged.
 * If outside maxM, snaps to circle boundary along the same bearing.
 */
export function clampToRadius(
  center: CoordInput,
  point: CoordInput,
  maxM = 4000
): ClampedResult {
  const c = toLatLng(center);
  const p = toLatLng(point);
  const dist = haversineDistanceM(c, p);

  if (dist <= maxM) {
    return {
      latitude: p.latitude,
      longitude: p.longitude,
      clamped: false,
      distanceM: dist,
    };
  }

  const brng = bearingDeg(c, p);
  const snapped = destinationPoint(c, maxM, brng);
  return {
    latitude: snapped.latitude,
    longitude: snapped.longitude,
    clamped: true,
    distanceM: dist,
  };
}

/**
 * Calculates minimum distance from point to segment AB in meters.
 */
function distanceToSegmentM(p: LatLng, a: LatLng, b: LatLng): number {
  const midLat = toRad((a.latitude + b.latitude) / 2.0);
  const cosLat = Math.cos(midLat);

  // Local flat-earth projection in meters
  const metersPerDegLat = 111132.95;
  const metersPerDegLon = 111412.84 * cosLat;

  const ax = a.longitude * metersPerDegLon;
  const ay = a.latitude * metersPerDegLat;
  const bx = b.longitude * metersPerDegLon;
  const by = b.latitude * metersPerDegLat;
  const px = p.longitude * metersPerDegLon;
  const py = p.latitude * metersPerDegLat;

  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;

  if (lenSq === 0) {
    return Math.hypot(px - ax, py - ay);
  }

  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq));
  const projX = ax + t * dx;
  const projY = ay + t * dy;

  return Math.hypot(px - projX, py - projY);
}

/**
 * Determines whether a clicked point is closer to pickup leg (origin -> pickup)
 * or destination leg (pickup -> destination).
 */
export function nearestLeg(
  origin: CoordInput,
  pickup: CoordInput,
  destination: CoordInput,
  point: CoordInput
): "pickup" | "destination" {
  const o = toLatLng(origin);
  const u = toLatLng(pickup);
  const d = toLatLng(destination);
  const p = toLatLng(point);

  const distToPickupLeg = distanceToSegmentM(p, o, u);
  const distToDestLeg = distanceToSegmentM(p, u, d);

  return distToPickupLeg <= distToDestLeg ? "pickup" : "destination";
}

/**
 * Creates GeoJSON Polygon coordinate ring representing a circle around center.
 */
export function createCircleCoordinates(
  center: CoordInput,
  radiusM: number,
  pointsCount = 64
): [number, number][] {
  const ring: [number, number][] = [];
  for (let i = 0; i <= pointsCount; i++) {
    const brng = (i * 360) / pointsCount;
    const pt = destinationPoint(center, radiusM, brng);
    ring.push([pt.longitude, pt.latitude]);
  }
  return ring;
}
