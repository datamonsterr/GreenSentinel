export type Coordinate = [number, number];
export type PlaybackMode = "observed" | "interpolated" | "gap" | "unmatched";
export interface PlaybackSample {
  _time: number;
  position: { coordinates: Coordinate };
  speed_mps?: number;
  bearing_deg?: number;
  anomaly_type?: string;
  leg?: string;
}
interface Gap { start_time: string; end_time: string }
type GapTime = [start: number, end: number];
interface Projection { distance: number; offset: number; coordinate: Coordinate }
interface Road { coordinates: Coordinate[]; offsets: number[]; leg?: string }
interface Interval { path: Coordinate[] | null; mode: PlaybackMode; distance: number }
export interface PlaybackTrack { samples: PlaybackSample[]; intervals: Interval[]; knownGaps?: GapTime[] }
export interface PlaybackPosition {
  coordinate: Coordinate;
  mode: PlaybackMode;
  sample: PlaybackSample;
  speedMps?: number;
  bearing?: number;
}

const radians = (degrees: number) => degrees * Math.PI / 180;
export function distanceMeters(a: Coordinate, b: Coordinate): number {
  const lat = radians(b[1] - a[1]);
  const lon = radians(b[0] - a[0]);
  const h = Math.sin(lat / 2) ** 2 + Math.cos(radians(a[1])) * Math.cos(radians(b[1])) * Math.sin(lon / 2) ** 2;
  return 6_371_000 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}

function project(point: Coordinate, road: Road): Projection {
  let best: Projection = { distance: Infinity, offset: 0, coordinate: point };
  const xScale = Math.cos(radians(point[1]));
  for (let i = 1; i < road.coordinates.length; i++) {
    const a = road.coordinates[i - 1], b = road.coordinates[i];
    const dx = (b[0] - a[0]) * xScale, dy = b[1] - a[1];
    const fraction = Math.max(0, Math.min(1, ((point[0] - a[0]) * xScale * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
    const coordinate: Coordinate = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
    const distance = distanceMeters(point, coordinate);
    if (distance < best.distance) best = { coordinate, distance, offset: road.offsets[i - 1] + (road.offsets[i] - road.offsets[i - 1]) * fraction };
  }
  return best;
}

function roadPath(a: Coordinate, b: Coordinate, road: Road): Coordinate[] | null {
  const start = project(a, road), end = project(b, road);
  // Only estimate within the supplied road corridor. Off-route observations
  // remain observations; they must not be snapped onto a planned route.
  if (start.distance > 30 || end.distance > 30) return null;
  const low = Math.min(start.offset, end.offset), high = Math.max(start.offset, end.offset);
  let middle = road.coordinates.filter((_, i) => road.offsets[i] > low && road.offsets[i] < high);
  if (end.offset < start.offset) middle = middle.reverse();
  const path = [start.coordinate, ...middle, end.coordinate];
  const offsets = [0];
  for (let i = 1; i < path.length; i++) offsets.push(offsets[i - 1] + distanceMeters(path[i - 1], path[i]));
  const length = offsets.at(-1) ?? 0;
  // Retain measured endpoint offsets, fading between them rather than jumping
  // to a road projection at the first animation frame.
  return path.map((p, i) => {
    const fraction = length ? offsets[i] / length : i / Math.max(1, path.length - 1);
    return [p[0] + (a[0] - start.coordinate[0]) * (1 - fraction) + (b[0] - end.coordinate[0]) * fraction,
      p[1] + (a[1] - start.coordinate[1]) * (1 - fraction) + (b[1] - end.coordinate[1]) * fraction];
  });
}

function pathDistance(path: Coordinate[]): number {
  return path.slice(1).reduce((sum, p, i) => sum + distanceMeters(path[i], p), 0);
}

export function createPlaybackTrack(samples: PlaybackSample[], routes: Coordinate[][], gaps: Gap[] = []): PlaybackTrack {
  const roads = routes.map((coordinates, index) => {
    const offsets = [0];
    for (let i = 1; i < coordinates.length; i++) offsets.push(offsets[i - 1] + distanceMeters(coordinates[i - 1], coordinates[i]));
    return { coordinates, offsets, leg: index === 0 ? 'pickup' : index === 1 ? 'destination' : undefined };
  }).filter((road) => road.coordinates.length > 1);
  const gapTimes: GapTime[] = gaps.map((gap) => [Date.parse(gap.start_time), Date.parse(gap.end_time)] as GapTime).filter(([s, e]) => !isNaN(s) && !isNaN(e) && s < e);
  const intervals = samples.slice(0, -1).map((sample, index): Interval => {
    const next = samples[index + 1], seconds = (next._time - sample._time) / 1000;
    if (seconds <= 0) return { path: null, mode: "unmatched", distance: 0 };
    if (seconds > 30 || gapTimes.some(([start, end]) => start < next._time && end > sample._time)) {
      return { path: null, mode: "gap", distance: 0 };
    }
    const a = sample.position.coordinates, b = next.position.coordinates;
    if (distanceMeters(a, b) < 0.1) return { path: [a, b], mode: "interpolated", distance: 0 };
    const sameLeg = !sample.leg || !next.leg || sample.leg === next.leg;
    const knownLeg = sample.leg || next.leg;
    const paths = roads.filter((road) => sameLeg && (!knownLeg || road.leg === knownLeg))
      .map((road) => roadPath(a, b, road)).filter((path): path is Coordinate[] => Boolean(path));
    const path = paths.sort((a, b) => pathDistance(a) - pathDistance(b))[0];
    const distance = path ? pathDistance(path) : 0;
    if (!path || distance / seconds > 50) return { path: null, mode: "unmatched", distance: 0 };
    return { path, mode: "interpolated", distance };
  });
  return { samples, intervals, knownGaps: gapTimes };
}

function sampleIndex(samples: PlaybackSample[], time: number): number {
  let low = 0, high = samples.length - 1, result = -1;
  while (low <= high) {
    const middle = (low + high) >>> 1;
    if (samples[middle]._time <= time) { result = middle; low = middle + 1; }
    else high = middle - 1;
  }
  return result;
}

function alongPath(path: Coordinate[], fraction: number): { coordinate: Coordinate; bearing?: number; prefix: Coordinate[] } {
  const target = pathDistance(path) * fraction;
  let travelled = 0;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i], length = distanceMeters(a, b);
    if (travelled + length >= target || i === path.length - 1) {
      const part = length ? Math.max(0, Math.min(1, (target - travelled) / length)) : 0;
      const coordinate: Coordinate = [a[0] + (b[0] - a[0]) * part, a[1] + (b[1] - a[1]) * part];
      const bearing = length > 0.1 ? (Math.atan2((b[0] - a[0]) * Math.cos(radians(a[1])), b[1] - a[1]) * 180 / Math.PI + 360) % 360 : undefined;
      return { coordinate, bearing, prefix: [...path.slice(0, i), coordinate] };
    }
    travelled += length;
  }
  return { coordinate: path[0], prefix: [path[0]] };
}

export function playbackAt(track: PlaybackTrack, time: number): PlaybackPosition | undefined {
  const index = sampleIndex(track.samples, time);
  if (index < 0) return undefined;
  const sample = track.samples[index], next = track.samples[index + 1];
  if (time === sample._time) return { coordinate: sample.position.coordinates, sample, mode: "observed", speedMps: sample.speed_mps, bearing: sample.bearing_deg };
  if (!next && track.knownGaps?.some(([start, end]) => start <= time && time <= end && time > sample._time)) {
    return { coordinate: sample.position.coordinates, sample, mode: "gap" };
  }
  if (!next) return { coordinate: sample.position.coordinates, sample, mode: "observed", speedMps: sample.speed_mps, bearing: sample.bearing_deg };
  const interval = track.intervals[index];
  if (!interval.path) return { coordinate: sample.position.coordinates, sample, mode: interval.mode };
  const fraction = (time - sample._time) / (next._time - sample._time);
  return { ...alongPath(interval.path, fraction), sample, mode: "interpolated", speedMps: interval.distance / ((next._time - sample._time) / 1000) };
}

/** Display-only road estimates. Break the trail across missing or unmatched GPS. */
export function playbackTrail(track: PlaybackTrack, time: number, startTime: number): Coordinate[][] {
  const segments: Coordinate[][] = [];
  let current: Coordinate[] = [];
  for (let i = 0; i < track.intervals.length; i++) {
    const sample = track.samples[i], next = track.samples[i + 1];
    if (sample._time >= time) break;
    if (next._time <= startTime) continue;
    const path = track.intervals[i].path;
    if (!path) { if (current.length > 1) segments.push(current); current = []; continue; }
    const fraction = Math.min(1, (time - sample._time) / (next._time - sample._time));
    const partial = alongPath(path, fraction).prefix;
    if (sample._time < startTime) {
      const startFraction = (startTime - sample._time) / (next._time - sample._time);
      const start = alongPath(path, startFraction);
      partial.splice(0, start.prefix.length - 1, start.coordinate);
    }
    current.push(...(current.length ? partial.slice(1) : partial));
  }
  if (current.length > 1) segments.push(current);
  return segments;
}
