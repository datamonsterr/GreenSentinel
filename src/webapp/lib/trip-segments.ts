/** Pure trip-replay classification: telemetry fixes -> coloured segments (planned / actual / off-route / gap / post-cancel). */
export type SegmentKind = "planned" | "actual" | "offroute" | "gap" | "postcancel";
export type LonLat = [number, number];

export interface TripSegment {
  kind: SegmentKind;
  coords: LonLat[];
  /** Per-vertex epoch ms (null when unknown); same length as coords. */
  times: Array<number | null>;
  distanceM: number;
  durationS: number | null;
  avgSpeedKmh: number | null;
  /** Gap reason when kind === "gap". */
  reason?: string;
}

export interface GapWindow { start_time: string; end_time: string; reason?: string }

export interface ClassifyOptions {
  samples: Array<Record<string, any>>;
  planned?: LonLat[];
  gaps?: GapWindow[];
  cancelAtMs?: number | null;
  /** Distance from planned route beyond which a track edge is off-route. */
  offRouteM?: number;
  /** A time hole between two fixes longer than this is a GPS gap. */
  gapThresholdS?: number;
}

export const SEGMENT_STYLE: Record<SegmentKind, { color: string; width: number; dash?: [number, number] }> = {
  planned: { color: "#22a45d", width: 3.5, dash: [2, 1.6] },
  actual: { color: "#0b3fae", width: 5 },
  offroute: { color: "#d97706", width: 5.5 },
  gap: { color: "#7c3aed", width: 4.5, dash: [1.6, 1.6] },
  postcancel: { color: "#dc2626", width: 5 },
};

const R = 6371000;
const rad = (d: number) => (d * Math.PI) / 180;

export function haversineM(a: LonLat, b: LonLat): number {
  const dLat = rad(b[1] - a[1]), dLon = rad(b[0] - a[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Min distance (m) from p to a polyline, local equirectangular projection. */
export function distanceToPolylineM(p: LonLat, line: LonLat[]): number {
  if (!line.length) return Infinity;
  const k = Math.cos(rad(p[1]));
  const proj = (q: LonLat): [number, number] => [rad(q[0] - p[0]) * k * R, rad(q[1] - p[1]) * R];
  let best = Infinity;
  for (let i = 0; i < line.length; i += 1) {
    const [ax, ay] = proj(line[i]);
    if (i === 0 && line.length === 1) best = Math.hypot(ax, ay);
    if (i === line.length - 1) break;
    const [bx, by] = proj(line[i + 1]);
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return best;
}

const lonLat = (sample: Record<string, any>): LonLat | null => {
  const c = sample?.position?.coordinates ?? (sample?.longitude != null ? [sample.longitude, sample.latitude] : null);
  if (!Array.isArray(c) || c[0] == null || c[1] == null) return null;
  const lon = Number(c[0]), lat = Number(c[1]);
  return Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lon, lat] : null;
};
const timeOf = (sample: Record<string, any>): number | null => {
  const ms = Date.parse(sample?.recorded_at ?? sample?.occurred_at ?? "");
  return Number.isFinite(ms) ? ms : null;
};

function build(kind: SegmentKind, coords: LonLat[], times: Array<number | null>, reason?: string): TripSegment {
  let distanceM = 0;
  for (let i = 1; i < coords.length; i += 1) distanceM += haversineM(coords[i - 1], coords[i]);
  const first = times.find((t) => t != null) ?? null, last = [...times].reverse().find((t) => t != null) ?? null;
  const durationS = first != null && last != null && last > first ? (last - first) / 1000 : null;
  return { kind, coords, times, distanceM, durationS, avgSpeedKmh: durationS ? (distanceM / durationS) * 3.6 : null, ...(reason ? { reason } : {}) };
}

/**
 * Walk fixes in time order. A null-coordinate fix (GPS dropout) or a recorded gap window
 * turns the connection between the neighbouring valid fixes into a "gap" segment; no
 * position is invented for the dropout itself.
 */
export function classifyTripSegments(opts: ClassifyOptions): TripSegment[] {
  const { samples, planned = [], gaps = [], cancelAtMs = null, offRouteM = 150, gapThresholdS = 30 } = opts;
  const ordered = samples.map((s, i) => ({ pos: lonLat(s), t: timeOf(s), i }))
    .sort((a, b) => (a.t != null && b.t != null && a.t !== b.t ? a.t - b.t : a.i - b.i));
  const windows = gaps.map((g) => ({ start: Date.parse(g.start_time), end: Date.parse(g.end_time), reason: g.reason }))
    .filter((g) => Number.isFinite(g.start) && Number.isFinite(g.end) && g.end > g.start);

  const out: TripSegment[] = [];
  const push = (kind: SegmentKind, a: LonLat, ta: number | null, b: LonLat, tb: number | null, reason?: string) => {
    const prev = out[out.length - 1];
    if (prev && prev.kind === kind && kind !== "gap") { prev.coords.push(b); prev.times.push(tb); return; }
    out.push({ kind, coords: [a, b], times: [ta, tb], distanceM: 0, durationS: null, avgSpeedKmh: null, ...(reason ? { reason } : {}) });
  };

  let last: { pos: LonLat; t: number | null } | null = null;
  let dropout = false;
  for (const s of ordered) {
    if (!s.pos) { dropout = true; continue; }
    if (last) {
      const hole = last.t != null && s.t != null ? (s.t - last.t) / 1000 : 0;
      const win = windows.find((w) => last!.t != null && s.t != null && last!.t <= w.end && s.t >= w.start);
      if (dropout || win || hole > gapThresholdS) {
        push("gap", last.pos, last.t, s.pos, s.t, win?.reason);
      } else {
        const mid: LonLat = [(last.pos[0] + s.pos[0]) / 2, (last.pos[1] + s.pos[1]) / 2];
        const after = cancelAtMs != null && last.t != null && s.t != null && last.t >= cancelAtMs && s.t > cancelAtMs;
        const off = planned.length > 1 && distanceToPolylineM(mid, planned) > offRouteM;
        push(after ? "postcancel" : off ? "offroute" : "actual", last.pos, last.t, s.pos, s.t);
      }
    }
    last = { pos: s.pos, t: s.t };
    dropout = false;
  }
  return out.map((seg) => build(seg.kind, seg.coords, seg.times, seg.reason));
}

/** Keep only vertices recorded at or before the playhead (unknown times are kept). */
export function clipSegmentsAt(segments: TripSegment[], tMs: number): TripSegment[] {
  return segments.flatMap((seg) => {
    const keep = seg.times.findIndex((t) => t != null && t > tMs);
    if (keep === -1) return [seg];
    if (keep < 2) return [];
    return [build(seg.kind, seg.coords.slice(0, keep), seg.times.slice(0, keep), seg.reason)];
  });
}

export function plannedSegment(planned: LonLat[]): TripSegment | null {
  return planned.length > 1 ? build("planned", planned, planned.map(() => null)) : null;
}

/** Valid [lon, lat] vertices of a GeoJSON coordinate array; anything else is dropped. */
export function lonLatList(value: unknown): LonLat[] {
  return Array.isArray(value) ? value.map((c) => lonLat({ position: { coordinates: c } })).filter((c): c is LonLat => c !== null) : [];
}
