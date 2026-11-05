import type { CaseDetailResponse, DisputeDossierResponse, TimelineMilestone } from "@/types/schemas";

// Pure derivations for the cockpit center panel. Every value comes from a
// measured case field; a missing source yields null so the UI renders an
// explicit empty state instead of a fabricated number.

export type SignalTone = "neutral" | "success" | "warning" | "danger" | "info" | "violet";

export function finite(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function sampleTime(sample: Record<string, unknown>): number | null {
  const raw = sample.recorded_at ?? sample.occurred_at ?? sample.timestamp;
  if (typeof raw !== "string") return null;
  const time = Date.parse(raw);
  return Number.isFinite(time) ? time : null;
}

function sampleSpeedKmh(sample: Record<string, unknown>): number | null {
  const kmh = finite(sample.speed_kmh);
  if (kmh !== null) return kmh;
  const mps = finite(sample.speed_mps);
  return mps === null ? null : mps * 3.6;
}

export interface SpeedPoint { time: number; speed: number }
export interface SpeedMarker { time: number; speed: number; kind: "stop" | "davi"; label: string }

export function speedSeries(samples: Array<Record<string, unknown>> | undefined): SpeedPoint[] {
  return (samples ?? [])
    .map(sample => ({ time: sampleTime(sample), speed: sampleSpeedKmh(sample) }))
    .filter((point): point is SpeedPoint => point.time !== null && point.speed !== null)
    .sort((a, b) => a.time - b.time)
    .map(point => ({ time: point.time, speed: Math.round(point.speed * 10) / 10 }));
}

function nearestSpeed(series: SpeedPoint[], time: number): number {
  if (!series.length) return 0;
  return series.reduce((best, point) => Math.abs(point.time - time) < Math.abs(best.time - time) ? point : best).speed;
}

export function speedMarkers(milestones: TimelineMilestone[] | undefined, series: SpeedPoint[]): SpeedMarker[] {
  const markers: SpeedMarker[] = [];
  for (const milestone of milestones ?? []) {
    const time = Date.parse(milestone.timestamp);
    if (!Number.isFinite(time)) continue;
    const measured = finite(milestone.speed_mps);
    const speed = measured === null ? nearestSpeed(series, time) : Math.round(measured * 36) / 10;
    if (milestone.type === "stall_anomaly") markers.push({ time, speed, kind: "stop", label: milestone.title });
    else if (milestone.is_anomaly && finite(milestone.davi) !== null) markers.push({ time, speed, kind: "davi", label: milestone.title });
  }
  return markers;
}

/** DAVI heading score in [-1, 1] (backend contract) from features, evidence or the latest sample. */
export function daviScore(detail: CaseDetailResponse, samples?: Array<Record<string, unknown>>): number | null {
  const latest = samples?.length ? samples[samples.length - 1] : undefined;
  const features = (detail.features ?? {}) as Record<string, unknown>;
  const stall = (detail.cockpit_evidence?.stall_davi ?? {}) as Record<string, unknown>;
  const points = detail.cockpit_evidence?.stall_davi_points ?? [];
  const lastPoint = points.length ? points[points.length - 1] : undefined;
  for (const value of [features.davi_score, features.davi, stall.davi_score, stall.davi, latest?.davi_score, latest?.davi, lastPoint?.davi]) {
    const score = finite(value);
    if (score !== null && score >= -1 && score <= 1) return score;
  }
  return null;
}

export interface MockRatio { flagged: number; total: number; ratio: number }

/** Share of telemetry samples that report a mock location; null without the flag. */
export function mockLocationRatio(samples: Array<Record<string, unknown>> | undefined): MockRatio | null {
  const reported = (samples ?? []).filter(sample => typeof sample.mock_location_reported === "boolean");
  if (!reported.length) return null;
  const flagged = reported.filter(sample => sample.mock_location_reported === true).length;
  return { flagged, total: reported.length, ratio: flagged / reported.length };
}

export interface SpeedComparison { key: "trip" | "ambient" | "peers"; speed: number }

/** Trip speed against the traffic provider and peer vehicles on the same segment. */
export function speedComparison(detail: CaseDetailResponse): SpeedComparison[] {
  const traffic = detail.traffic_corroboration;
  const peers = (traffic?.peer_drivers ?? []).map(peer => finite(peer.speed_kmh)).filter((speed): speed is number => speed !== null);
  const rows: Array<SpeedComparison | null> = [
    finite(traffic?.suspect_driver?.speed_kmh) === null ? null : { key: "trip", speed: finite(traffic?.suspect_driver?.speed_kmh)! },
    finite(traffic?.public_service?.average_speed_kmh) === null ? null : { key: "ambient", speed: finite(traffic?.public_service?.average_speed_kmh)! },
    peers.length ? { key: "peers", speed: Math.round((peers.reduce((sum, speed) => sum + speed, 0) / peers.length) * 10) / 10 } : null,
  ];
  return rows.filter((row): row is SpeedComparison => row !== null);
}

export interface TimelineEvent {
  id: string;
  label: string;
  timestamp: string | null;
  tone: SignalTone;
  detail?: string;
  highlight?: boolean;
}

const milestoneTone: Record<TimelineMilestone["type"], SignalTone> = {
  start_match: "info",
  driver_arrived: "violet",
  pickup: "success",
  dropoff_destination: "success",
  stall_anomaly: "warning",
  gap_anomaly: "warning",
  speed_anomaly: "danger",
};

/** Trip status changes from timeline milestones, ending with the recorded cancel event. */
export function tripTimeline(detail: CaseDetailResponse, cancelLabel: string): TimelineEvent[] {
  const events: TimelineEvent[] = [...(detail.timeline_milestones ?? [])]
    .filter(milestone => Number.isFinite(Date.parse(milestone.timestamp)))
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
    .map(milestone => ({
      id: milestone.id,
      label: milestone.title,
      timestamp: milestone.timestamp,
      tone: milestoneTone[milestone.type] ?? "neutral",
      detail: milestone.description || undefined,
      highlight: Boolean(milestone.is_anomaly),
    }));
  const trip = detail.trip;
  if (trip?.cancellation_reason || trip?.cancellation_actor) {
    const at = typeof trip.cancelled_at === "string" && Number.isFinite(Date.parse(trip.cancelled_at)) ? trip.cancelled_at : null;
    events.push({
      id: "trip-cancelled",
      label: trip.cancellation_actor ? `${cancelLabel} · ${trip.cancellation_actor}` : cancelLabel,
      timestamp: at,
      tone: "danger",
      detail: trip.cancellation_reason || undefined,
      highlight: true,
    });
  }
  return events;
}

/** Seconds between each event and the next timestamped event; null when unknown. */
export function segmentDurations(events: Array<{ timestamp: string | null }>): Array<number | null> {
  return events.map((event, index) => {
    const next = events.slice(index + 1).find(candidate => candidate.timestamp);
    if (!event.timestamp || !next?.timestamp) return null;
    const seconds = (Date.parse(next.timestamp) - Date.parse(event.timestamp)) / 1000;
    return Number.isFinite(seconds) && seconds >= 0 ? Math.round(seconds) : null;
  });
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export interface RelayTurn { role: "agent" | "driver"; text: string; timestamp: string | null }

/** Agent–driver relay turns (GSupport agent and driver), oldest first. */
export function relayTurns(dossier: DisputeDossierResponse | null | undefined): RelayTurn[] {
  return (dossier?.transcript ?? [])
    .map(turn => {
      const role = turn.role === "driver" || turn.role === "driver_agent" ? "driver" : turn.role === "agent" ? "agent" : null;
      const text = String(turn.text ?? turn.content ?? "").trim();
      const raw = turn.timestamp ?? turn.occurred_at ?? turn.created_at;
      const timestamp = typeof raw === "string" && Number.isFinite(Date.parse(raw)) ? raw : null;
      return role && text ? { role, text, timestamp } as RelayTurn : null;
    })
    .filter((turn): turn is RelayTurn => turn !== null)
    .sort((a, b) => (a.timestamp && b.timestamp ? Date.parse(a.timestamp) - Date.parse(b.timestamp) : 0));
}

export interface WillingnessMetrics { questions: number; answered: number; avgResponseSeconds: number | null; driverTurns: number }

/** Responsiveness measured from the relay: questions asked, answered, and reply latency. */
export function willingnessMetrics(turns: RelayTurn[]): WillingnessMetrics | null {
  const questions = turns.filter(turn => turn.role === "agent").length;
  const driverTurns = turns.filter(turn => turn.role === "driver").length;
  if (!questions && !driverTurns) return null;
  let answered = 0;
  const latencies: number[] = [];
  turns.forEach((turn, index) => {
    if (turn.role !== "agent") return;
    const reply = turns.slice(index + 1).find(candidate => candidate.role === "driver" || candidate.role === "agent");
    if (reply?.role !== "driver") return;
    answered += 1;
    if (turn.timestamp && reply.timestamp) {
      const seconds = (Date.parse(reply.timestamp) - Date.parse(turn.timestamp)) / 1000;
      if (Number.isFinite(seconds) && seconds >= 0) latencies.push(seconds);
    }
  });
  const avgResponseSeconds = latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : null;
  return { questions, answered, avgResponseSeconds, driverTurns };
}

/** Driver statements first: they carry the stated reasons behind the trip outcome. */
export function motivationEvidence(turns: RelayTurn[], limit = 2): RelayTurn[] {
  return turns.filter(turn => turn.role === "driver").slice(0, limit);
}

/** The latest agent question with the driver's reply shows cooperation directly. */
export function willingnessEvidence(turns: RelayTurn[]): RelayTurn[] {
  for (let index = turns.length - 1; index > 0; index -= 1) {
    if (turns[index].role === "driver" && turns[index - 1].role === "agent") return [turns[index - 1], turns[index]];
  }
  return turns.filter(turn => turn.role === "driver").slice(-1);
}
