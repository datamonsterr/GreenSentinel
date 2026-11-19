"use client";

import React, { useEffect, useRef, useState, useMemo } from "react";
import { createPlaybackTrack, playbackAt, playbackTrail } from "@/lib/telemetry-playback";
import { CheckpointIcon, markerSvg, vehicleKind } from "./checkpoint-icon";
import { createCircleCoordinates } from "@/lib/geo";
import {
  RouteCandidate,
  TrafficCorroboration,
  TimelineMilestone,
  DataMissingnessAlert,
} from "@/types/schemas";
import { formatStallDuration } from "@/lib/utils";
import { useLocale } from "@/lib/locale";
import { mapMessages } from "@/lib/map-messages";
import { clipSegmentsAt, type SegmentKind, type TripSegment } from "@/lib/trip-segments";
import { TripSegmentLayers, TripSegmentLegend, type CancelPoint } from "@/components/map/trip-segment-layers";
export type TripStatus = "coming" | "picked up" | "complete" | "stalled" | "suspended" | string;

export interface StallPointInfo {
  latitude: number;
  longitude: number;
  duration_seconds: number;
  davi_score?: number;
  label?: string;
}

export interface DriverLocationInfo {
  latitude: number;
  longitude: number;
  bearing?: number;
  status?: TripStatus;
}

export interface HotspotInfo {
  latitude: number;
  longitude: number;
  radius_meters?: number;
  label?: string;
}

export interface CustomerLocationInfo {
  latitude: number;
  longitude: number;
  label?: string;
}

export interface MapLibreViewProps {
  caseId?: string;
  pickupRoute?: [number, number][]; // [longitude, latitude][]
  driverBreadcrumbs?: [number, number][]; // [longitude, latitude][]
  driverLocation?: DriverLocationInfo;
  vehicleType?: string | null;
  customerLocation?: CustomerLocationInfo;
  driverInitialLocation?: { latitude: number; longitude: number; label?: string };
  destinationLocation?: { latitude: number; longitude: number; label?: string };
  stallPoint?: StallPointInfo | null;
  hotspots?: HotspotInfo[];
  candidateRoutes?: RouteCandidate[];
  trafficCorroboration?: TrafficCorroboration | null;
  timelineMilestones?: TimelineMilestone[];
  missingnessAlerts?: DataMissingnessAlert[];
  currentSpeedMps?: number;
  gpsLatencyMs?: number;
  telemetrySamples?: Array<Record<string, any>>;
  routeGeometry?: Record<string, any> | null;
  /** Classified trip segments (planned/actual/off-route/gap/post-cancel); replaces the single-colour trail when set. */
  tripSegments?: TripSegment[];
  cancelPoint?: CancelPoint | null;
  /** Fixed map canvas height in px (default: compact 256/288). */
  mapHeight?: number;
  className?: string;
  initialTraffic?: boolean;
  initialBreadcrumbs?: boolean;
  initialRoute?: boolean;
  initialHotspots?: boolean;
  mapStyle?: string | Record<string, any>;
  showKinematicFooter?: boolean;
  /** Measured stationary duration (s) shown when no stall point is active. */
  stallDurationSeconds?: number | null;
  /** Measured DAVI score shown when no milestone or stall carries one. */
  daviScore?: number | null;
  followDriver?: boolean;
  onToggleFollowDriver?: (follow: boolean) => void;
  onMapClick?: (coords: { latitude: number; longitude: number }) => void;
  /** Opt-in: the initial/pickup/destination markers can be dragged (tester console). */
  draggableStops?: boolean;
  onStopDrag?: (
    kind: "initial" | "pickup" | "destination",
    coords: { latitude: number; longitude: number }
  ) => void;
  onStopDragStart?: (kind: "initial" | "pickup" | "destination") => void;
  onStopDragEnd?: (kind: "initial" | "pickup" | "destination") => void;
  waypoints?: Array<{ id: string; lat: number; lon: number; leg?: "pickup" | "destination"; name?: string }>;
  proximityCircle?: { center: { latitude: number; longitude: number }; radiusM: number } | null;
}

export const OPENFREEMAP_LIBERTY_STYLE = "https://tiles.openfreemap.org/styles/liberty";
export const OPENFREEMAP_POSITRON_STYLE = "https://tiles.openfreemap.org/styles/positron";
const EMPTY_ROUTES: RouteCandidate[] = [];
const EMPTY_MILESTONES: TimelineMilestone[] = [];
const EMPTY_GAPS: DataMissingnessAlert[] = [];

export const OSM_RASTER_FALLBACK_STYLE: any = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    },
  },
  layers: [
    {
      id: "osm-tiles",
      type: "raster",
      source: "osm",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

/**
 * Safely test if WebGL context can be initialized.
 * Returns false in headless / jsdom / test environments without WebGL.
 */
export function isWebGLSupported(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined" || !window.WebGLRenderingContext) {
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl") ||
      canvas.getContext("webgl2");
    return Boolean(gl);
  } catch {
    return false;
  }
}

function isGeographicCoordinate(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length >= 2
    && Number.isFinite(value[0]) && value[0] >= -180 && value[0] <= 180
    && Number.isFinite(value[1]) && value[1] >= -90 && value[1] <= 90;
}

export function extractCoordinates(value: unknown): [number, number][] {
  return Array.isArray(value)
    ? value.filter(isGeographicCoordinate)
    : [];
}

// A road leg is ordered geometry: dropping a malformed vertex would invent a connecting segment.
function extractRouteCoordinates(value: unknown): [number, number][] {
  return Array.isArray(value) && value.length >= 2 && value.every(isGeographicCoordinate)
    ? value
    : [];
}

export function MapLibreView({
  caseId,
  pickupRoute,
  driverBreadcrumbs,
  driverLocation,
  vehicleType,
  customerLocation,
  driverInitialLocation,
  destinationLocation,
  stallPoint,
  hotspots,
  candidateRoutes = EMPTY_ROUTES,
  trafficCorroboration,
  timelineMilestones = EMPTY_MILESTONES,
  missingnessAlerts = EMPTY_GAPS,
  currentSpeedMps,
  gpsLatencyMs,
  telemetrySamples,
  routeGeometry,
  tripSegments,
  cancelPoint,
  mapHeight,
  className = "",
  initialTraffic,
  initialBreadcrumbs,
  initialRoute,
  initialHotspots,
  mapStyle,
  showKinematicFooter = true,
  stallDurationSeconds = null,
  daviScore = null,
  followDriver,
  onToggleFollowDriver,
  onMapClick,
  draggableStops = false,
  onStopDrag,
  onStopDragStart,
  onStopDragEnd,
  waypoints,
  proximityCircle,
}: MapLibreViewProps) {
  const { locale } = useLocale();
  const messages = mapMessages[locale] ?? mapMessages.en;
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);
  const onStopDragRef = useRef(onStopDrag);
  useEffect(() => {
    onStopDragRef.current = onStopDrag;
  }, [onStopDrag]);
  const onStopDragStartRef = useRef(onStopDragStart);
  useEffect(() => {
    onStopDragStartRef.current = onStopDragStart;
  }, [onStopDragStart]);
  const onStopDragEndRef = useRef(onStopDragEnd);
  useEffect(() => {
    onStopDragEndRef.current = onStopDragEnd;
  }, [onStopDragEnd]);
  const fittedBoundsRef = useRef<string>("");
  const candidateIdsRef = useRef<string[]>([]);
  const lineCoordinatesRef = useRef(new Map<string, { points: [number, number][]; segments?: [number, number][][] }>());
  const markerConstructorRef = useRef<any>(null);
  const checkpointMarkersRef = useRef(new Map<string, { marker: any; element: HTMLDivElement; svg: string; offset?: [number, number] }>());
  const waypointMarkersRef = useRef(new Map<string, { marker: any; element: HTMLDivElement }>());
  const activeWaypoints = useMemo(() => waypoints ?? [], [waypoints]);
  const isTestEnv = typeof process !== "undefined" && process.env.NODE_ENV === "test";

  // In test environments (JSDOM), evaluate isWebGLSupported synchronously (false) so fallback renders immediately.
  // In browser, evaluate isWebGLSupported synchronously (true) so real map container renders without flashing SVG paths.
  const [hasWebGL, setHasWebGL] = useState<boolean>(() => {
    if (isTestEnv) {
      return isWebGLSupported();
    }
    if (typeof window !== "undefined") {
      return isWebGLSupported();
    }
    return true;
  });
  const [mapLoaded, setMapLoaded] = useState<boolean>(false);
  const [isFollowingDriver, setIsFollowingDriver] = useState<boolean>(Boolean(followDriver));

  useEffect(() => {
    if (followDriver !== undefined) {
      setIsFollowingDriver(followDriver);
    }
  }, [followDriver]);

  // Layer toggles state
  const [showTraffic, setShowTraffic] = useState<boolean>(initialTraffic ?? true);
  const [showBreadcrumbs, setShowBreadcrumbs] = useState<boolean>(initialBreadcrumbs ?? true);
  const [showRoute, setShowRoute] = useState<boolean>(initialRoute ?? true);
  const [showHotspots, setShowHotspots] = useState<boolean>(initialHotspots ?? true);

  // Interactive timeline with millisecond GPS precision and route inspection
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [inspectedRouteId, setInspectedRouteId] = useState<string | null>(null);
  const [showTrafficPanel, setShowTrafficPanel] = useState<boolean>(false);
  const [isTrafficHovered, setIsTrafficHovered] = useState<boolean>(false);

  const isTrafficExpanded = isTrafficHovered || showTrafficPanel;

  // Resolved milestones
  const hasTelemetrySource = telemetrySamples !== undefined;
  const normalizedTelemetry = useMemo(() => (telemetrySamples || [])
    .filter((s: any) => isGeographicCoordinate(s?.position?.coordinates) && (s.recorded_at || s.occurred_at))
    .map((s: any) => ({ ...s, recorded_at: s.recorded_at || s.occurred_at, _time: new Date(s.recorded_at || s.occurred_at).getTime() }))
    .filter((s: any) => Number.isFinite(s._time))
    .sort((a: any, b: any) => a._time - b._time), [telemetrySamples]);
  const milestones = useMemo(() => {
    const persisted = normalizedTelemetry.map((s: any, i: number) => ({
      id: `telemetry-${i}`, type: s.anomaly_type ? `${s.anomaly_type}_anomaly` : "telemetry",
      timestamp: s.recorded_at, title: s.anomaly_type || "Telemetry", is_anomaly: Boolean(s.anomaly_type),
      lat: Number(s.position.coordinates[1]), lon: Number(s.position.coordinates[0]), speed_mps: s.speed_mps,
    })) as any[];
    return [...timelineMilestones, ...persisted.filter((s: any) => s.is_anomaly && !timelineMilestones.some((m) => m.timestamp === s.timestamp && m.is_anomaly))].filter((m) => Number.isFinite(Date.parse(m.timestamp))).sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  }, [timelineMilestones, normalizedTelemetry]);

  // Bounds include every recorded sample, including trips without milestones.
  const { startTimestampMs, totalDurationSec, startTimeFormatted, endTimeFormatted } = useMemo(() => {
    const times = (normalizedTelemetry.length ? normalizedTelemetry.map((s) => s._time) : milestones.map((m) => Date.parse(m.timestamp))).filter(Number.isFinite);
    const gapEndTimes = missingnessAlerts.map((gap) => Date.parse(gap.end_time)).filter(Number.isFinite);
    const startTimestampMs = times.length ? Math.min(...times) : 0;
    // A terminal gap's end is a recorded observation; the track reaches it without inventing positions.
    const endTimestampMs = times.length ? Math.max(...times, ...gapEndTimes) : 0;
    return {
      startTimestampMs,
      totalDurationSec: (endTimestampMs - startTimestampMs) / 1000,
      startTimeFormatted: times.length ? new Date(startTimestampMs).toISOString().slice(11, 19) : "—",
      endTimeFormatted: times.length ? new Date(endTimestampMs).toISOString().slice(11, 19) : "—",
    };
  }, [milestones, normalizedTelemetry, missingnessAlerts]);

  const [currentSecondOffset, setCurrentSecondOffset] = useState<number>(0);
  const [rangeStartSecond, setRangeStartSecond] = useState<number>(0);
  const [rangeEndSecond, setRangeEndSecond] = useState<number | null>(null);
  const previousCaseIdRef = useRef(caseId);
  useEffect(() => {
    if (previousCaseIdRef.current === caseId) return;
    previousCaseIdRef.current = caseId;
    setIsPlaying(false);
    setCurrentSecondOffset(0);
    setRangeStartSecond(0);
    setRangeEndSecond(null);
  }, [caseId]);
  const visibleEndSecond = Math.min(rangeEndSecond ?? totalDurationSec, totalDurationSec);
  const visibleStartSecond = Math.min(rangeStartSecond, visibleEndSecond);
  const scrubSecond = Math.max(visibleStartSecond, Math.min(currentSecondOffset, visibleEndSecond));
  const currentTimeMs = startTimestampMs + scrubSecond * 1000;
  const visibleMilestones = useMemo(() => milestones.filter((m) => {
    const second = (Date.parse(m.timestamp) - startTimestampMs) / 1000;
    return second >= visibleStartSecond && second <= visibleEndSecond;
  }), [milestones, startTimestampMs, visibleStartSecond, visibleEndSecond]);
  // Red dashed warning bands anchored to recorded gap windows; never part of the measured trail.
  const visibleGaps = useMemo(() => missingnessAlerts.flatMap((gap) => {
    const startMs = Date.parse(gap.start_time), endMs = Date.parse(gap.end_time);
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return [];
    const startSecond = (startMs - startTimestampMs) / 1000, endSecond = (endMs - startTimestampMs) / 1000;
    const clampedStart = Math.max(visibleStartSecond, Math.min(startSecond, visibleEndSecond));
    const clampedEnd = Math.max(visibleStartSecond, Math.min(endSecond, visibleEndSecond));
    if (clampedEnd <= clampedStart) return [];
    const span = Math.max(0.001, visibleEndSecond - visibleStartSecond);
    return [{ gap, left: (clampedStart - visibleStartSecond) / span * 100, width: (clampedEnd - clampedStart) / span * 100 }];
  }), [missingnessAlerts, startTimestampMs, visibleStartSecond, visibleEndSecond]);
  const validGapAlerts = useMemo(() => missingnessAlerts.filter((gap) => {
    const startMs = Date.parse(gap.start_time), endMs = Date.parse(gap.end_time);
    return Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs;
  }), [missingnessAlerts]);
  const gapExplanation = (gap: typeof missingnessAlerts[number]) => {
    const duration = Number(gap.gap_duration_s);
    const source = /network|mạng|kết nối|offline/i.test(gap.reason) && duration > 30
      ? "Mất kết nối (>30s)"
      : "GPS không khả dụng";
    return `GPS: ${source} từ ${gap.start_time.slice(11, 19)} đến ${gap.end_time.slice(11, 19)} · ${duration}s · ${gap.reason}`;
  };
  const seek = (second: number) => { setIsPlaying(false); setCurrentSecondOffset(second); };

  const currentTimeFormatted = useMemo(() => {
    if (!normalizedTelemetry.length && !milestones.length) return "—";
    const d = new Date(currentTimeMs);
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    const ss = String(d.getUTCSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }, [currentTimeMs, normalizedTelemetry.length, milestones.length]);

  // Never display a future event as the current trip state.
  const activeMilestone = visibleMilestones.filter((m) => Date.parse(m.timestamp) <= currentTimeMs).at(-1) ?? null;

  // One recorded second per elapsed second, independent of trip duration.
  useEffect(() => {
    if (!isPlaying) return;
    let previousTime = performance.now();
    let frame = 0;
    const advance = (now: number) => {
      const elapsed = Math.max(0, (now - previousTime) / 1000);
      previousTime = now;
      setCurrentSecondOffset((prev) => {
        const next = Math.max(prev, visibleStartSecond) + elapsed;
        if (next >= visibleEndSecond) {
          setIsPlaying(false);
          return visibleEndSecond;
        }
        return next;
      });
      frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [isPlaying, visibleStartSecond, visibleEndSecond]);

  // Geometry is supplied by the API; never substitute a synthetic route.
  const derivedPickupRoute = useMemo(() => extractRouteCoordinates(
    pickupRoute ??
    routeGeometry?.pickup_route?.coordinates ??
    routeGeometry?.pickup_route?.route?.coordinates ??
    routeGeometry?.route?.coordinates ??
    routeGeometry?.coordinates
  ), [pickupRoute, routeGeometry]);

  const derivedDestinationRoute = useMemo(() => extractRouteCoordinates(
    routeGeometry?.destination_route?.coordinates ??
    routeGeometry?.destination_route?.route?.coordinates
  ), [routeGeometry]);

  const playbackTrack = useMemo(() => createPlaybackTrack(normalizedTelemetry, [derivedPickupRoute, derivedDestinationRoute], missingnessAlerts),
    [normalizedTelemetry, derivedPickupRoute, derivedDestinationRoute, missingnessAlerts]);
  const playback = useMemo(() => playbackAt(playbackTrack, currentTimeMs), [playbackTrack, currentTimeMs]);
  const breadcrumbSegments = useMemo(() => hasTelemetrySource
    ? playbackTrail(playbackTrack, currentTimeMs, startTimestampMs + visibleStartSecond * 1000)
    : [extractCoordinates(driverBreadcrumbs)],
  [hasTelemetrySource, playbackTrack, currentTimeMs, startTimestampMs, visibleStartSecond, driverBreadcrumbs]);
  const derivedBreadcrumbs = useMemo(() => breadcrumbSegments.flat(), [breadcrumbSegments]);
  const hasSegments = Boolean(tripSegments?.length);
  // Replay: only draw what has been recorded up to the playhead.
  const visibleSegments = useMemo(() => (tripSegments?.length ? clipSegmentsAt(tripSegments, currentTimeMs) : []), [tripSegments, currentTimeMs]);
  const legendKinds = useMemo(() => (["planned", "actual", "offroute", "gap", "postcancel"] as SegmentKind[]).filter((k) => tripSegments?.some((seg) => seg.kind === k)), [tripSegments]);
  const visibleCancel = cancelPoint && (!Number.isFinite(Date.parse(cancelPoint.timestamp ?? "")) || Date.parse(cancelPoint.timestamp!) <= currentTimeMs || !normalizedTelemetry.length) ? cancelPoint : null;
  const observedBreadcrumbs = useMemo(() => normalizedTelemetry.filter((s) => s._time >= startTimestampMs + visibleStartSecond * 1000 && s._time <= currentTimeMs),
    [normalizedTelemetry, startTimestampMs, visibleStartSecond, currentTimeMs]);
  // Gap anchors sit on recorded fixes only; no geometry is invented between them.
  const gapEndpoints = useMemo(() => validGapAlerts.flatMap((gap) => {
    const startMs = Date.parse(gap.start_time), endMs = Date.parse(gap.end_time);
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return [];
    const summary = `Mất dữ liệu GPS ${Number(gap.gap_duration_s)}s (${gap.start_time.slice(11, 19)} – ${gap.end_time.slice(11, 19)}): ${gap.reason}`;
    const before = [...normalizedTelemetry].reverse().find((s) => s._time <= startMs);
    const after = normalizedTelemetry.find((s) => s._time >= endMs);
    return [
      ...(before ? [{ key: `${gap.alert_id}-start`, alert: gap, role: "gap_start", coordinate: before.position.coordinates as [number, number], tooltip: summary }] : []),
      ...(after ? [{ key: `${gap.alert_id}-end`, alert: gap, role: "gap_end", coordinate: after.position.coordinates as [number, number], tooltip: summary }] : []),
    ];
  }), [validGapAlerts, normalizedTelemetry]);
  const observedBreadcrumbCount = hasTelemetrySource ? observedBreadcrumbs.length : derivedBreadcrumbs.length;

  const activeDriver: DriverLocationInfo | undefined = useMemo(() => {
    if (hasTelemetrySource && normalizedTelemetry.length === 0) {
      return undefined;
    }
    if (normalizedTelemetry.length) {
      return playback && {
        latitude: playback.coordinate[1],
        longitude: playback.coordinate[0],
        bearing: playback.bearing,
        status: playback.sample.anomaly_type ? "stalled" : "en_route",
      };
    }
    return driverLocation ?? (activeMilestone?.lat != null && activeMilestone?.lon != null
      ? { latitude: activeMilestone.lat, longitude: activeMilestone.lon, status: activeMilestone.is_anomaly ? "stalled" : "en_route" }
      : undefined);
  }, [hasTelemetrySource, normalizedTelemetry.length, playback, driverLocation, activeMilestone]);

  const initialDriverPos = driverInitialLocation;
  const destinationPos = destinationLocation;
  const activeCustomer = customerLocation;
  const activeStall = stallPoint ?? null;
  const footerStallSeconds = activeStall?.duration_seconds ?? (Number.isFinite(stallDurationSeconds) ? stallDurationSeconds : null);
  const footerDavi = activeStall?.davi_score ?? (Number.isFinite(daviScore) ? daviScore : null);
  const activeHotspots = useMemo(() => hotspots ?? [], [hotspots]);
  const anomalyMilestones = useMemo(
    () => visibleMilestones.filter((m) => m.is_anomaly && m.lat != null && m.lon != null),
    [visibleMilestones]
  );

  // Shared coordinate projection keeps every SVG layer in the same geographic frame.
  const allCoordinates = useMemo(() => [
    ...derivedPickupRoute,
    ...derivedDestinationRoute,
    ...(hasTelemetrySource ? [] : extractCoordinates(driverBreadcrumbs)),
    ...extractCoordinates(normalizedTelemetry.map((s) => s.position.coordinates)),
    ...candidateRoutes.flatMap((r) => r.coordinates),
    ...[initialDriverPos, destinationPos, activeCustomer, hasTelemetrySource ? undefined : driverLocation, activeStall, ...activeHotspots].filter(Boolean).map((p) => [p!.longitude, p!.latitude] as [number, number]),
    ...milestones.filter((m) => m.lat != null && m.lon != null).map((m) => [m.lon, m.lat] as [number, number]),
    ...activeWaypoints.map((w) => [w.lon, w.lat] as [number, number]),
  ], [
    derivedPickupRoute,
    derivedDestinationRoute,
    normalizedTelemetry,
    hasTelemetrySource,
    driverBreadcrumbs,
    candidateRoutes,
    initialDriverPos,
    destinationPos,
    activeCustomer,
    driverLocation,
    activeStall,
    activeHotspots,
    milestones,
    activeWaypoints,
  ]);

  // Full travelled path + 3 key points (driver initial pos, customer pickup pos, destination pos)
  const tripKeyCoordinates = useMemo(() => {
    const points: [number, number][] = [
      ...derivedPickupRoute,
      ...derivedDestinationRoute,
      ...(hasTelemetrySource ? [] : extractCoordinates(driverBreadcrumbs)),
      ...extractCoordinates(normalizedTelemetry.map((s) => s.position.coordinates)),
      ...([initialDriverPos, destinationPos, activeCustomer].filter(Boolean).map((p) => [p!.longitude, p!.latitude] as [number, number])),
      ...activeWaypoints.map((w) => [w.lon, w.lat] as [number, number]),
    ];
    return points.length > 0 ? points : allCoordinates;
  }, [
    derivedPickupRoute,
    derivedDestinationRoute,
    normalizedTelemetry,
    hasTelemetrySource,
    driverBreadcrumbs,
    initialDriverPos,
    destinationPos,
    activeCustomer,
    allCoordinates,
    activeWaypoints,
  ]);

  const { minLon, maxLon, minLat, maxLat } = useMemo(() => {
    const coords = tripKeyCoordinates.length ? tripKeyCoordinates : allCoordinates;
    if (!coords.length) return { minLon: 0, maxLon: 0, minLat: 0, maxLat: 0 };
    const longitudes = coords.map((p) => p[0]);
    const latitudes = coords.map((p) => p[1]);
    return {
      minLon: Math.min(...longitudes),
      maxLon: Math.max(...longitudes),
      minLat: Math.min(...latitudes),
      maxLat: Math.max(...latitudes),
    };
  }, [tripKeyCoordinates, allCoordinates]);
  const project = (longitude: number, latitude: number) => ({
    x: maxLon > minLon ? 40 + (longitude - minLon) / (maxLon - minLon) * 620 : 350,
    y: maxLat > minLat ? 220 - (latitude - minLat) / (maxLat - minLat) * 190 : 125,
  });
  const pathFor = (points: [number, number][]) => points.map(([lon, lat], i) => {
    const point = project(lon, lat);
    return `${i ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  }).join(" ");
  const transformFor = (point: { longitude: number; latitude: number }) => {
    const projected = project(point.longitude, point.latitude);
    return `translate(${projected.x.toFixed(1)}, ${projected.y.toFixed(1)})`;
  };
  const speedMps = hasTelemetrySource ? playback?.speedMps : currentSpeedMps ?? activeMilestone?.speed_mps;
  const speedKmh = speedMps != null && Number.isFinite(speedMps) ? (speedMps * 3.6).toFixed(1) : null;
  const rawLatency = gpsLatencyMs ?? activeMilestone?.latency_ms;
  const latencyMs = rawLatency != null && rawLatency !== "—" && rawLatency !== "" ? rawLatency : null;

  // Inspected candidate route
  const inspectedRoute = useMemo(() => {
    if (!inspectedRouteId) return null;
    return candidateRoutes.find((r) => r.id === inspectedRouteId) || null;
  }, [candidateRoutes, inspectedRouteId]);

  // Verify WebGL capability on mount in real browser (handles rare WebGL disabled cases)
  useEffect(() => {
    if (!isWebGLSupported()) {
      setHasWebGL(false);
    }
  }, []);

  // MapLibre dynamic initialization when WebGL is available
  useEffect(() => {
    if (!hasWebGL || !mapContainerRef.current) return;

    let isMounted = true;

    async function initMap() {
      try {
        const maplibregl = await import("maplibre-gl");

        // Next/Webpack cannot provide MapLibre's import.meta.url fallback. Without
        // an explicit worker URL, MapLibre creates `new Worker("")`, which loads
        // the current page as a worker and leaves GeoJSON sources unresolved.
        maplibregl.setWorkerUrl(
          new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString(),
        );

        if (!isMounted || !mapContainerRef.current) return;

        // Basemap style resolution:
        // 1. Explicit prop mapStyle
        // 2. process.env.NEXT_PUBLIC_MAP_STYLE_URL
        // 3. CARTO Voyager raster IF NEXT_PUBLIC_CARTO_API_KEY is provided
        // 4. Default: OpenFreeMap Liberty (Vector, 100% keyless, public, CORS enabled, no watermark)
        const cartoKey =
          typeof process !== "undefined" ? process.env.NEXT_PUBLIC_CARTO_API_KEY : undefined;
        const envStyle =
          typeof process !== "undefined" ? process.env.NEXT_PUBLIC_MAP_STYLE_URL : undefined;

        let activeStyle: any = mapStyle || envStyle;

        if (!activeStyle) {
          if (cartoKey && cartoKey !== "your_carto_api_key_here") {
            activeStyle = {
              version: 8,
              sources: {
                carto: {
                  type: "raster",
                  tiles: [
                    `https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${cartoKey}`,
                    `https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${cartoKey}`,
                    `https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${cartoKey}`,
                    `https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png?key=${cartoKey}`,
                  ],
                  tileSize: 256,
                  attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
                },
              },
              layers: [
                {
                  id: "carto-tiles",
                  type: "raster",
                  source: "carto",
                  minzoom: 0,
                  maxzoom: 20,
                },
              ],
            };
          } else {
            activeStyle = OPENFREEMAP_LIBERTY_STYLE;
          }
        }

        const map = new maplibregl.Map({
          container: mapContainerRef.current,
          style: activeStyle,
          center: activeDriver ? [activeDriver.longitude, activeDriver.latitude] : allCoordinates[0] ?? [0, 0],
          zoom: 15.2,
          maxZoom: 19,
        });

        mapInstanceRef.current = map;
        markerConstructorRef.current = maplibregl.Marker;
        // Keep MapLibre's navigation UI in its own control slot so it cannot
        // collide with the telemetry chips rendered by the console.
        if (typeof map.addControl === "function" && typeof maplibregl.NavigationControl === "function") {
          map.addControl(new maplibregl.NavigationControl(), "top-right");
        }
        if (typeof window !== "undefined") {
          (window as any).__maplibreInstance = map;
        }

        // Fallback to OSM raster style if remote vector style encounters network error
        map.on("error", (e: any) => {
          if (e && e.error && String(e.error).includes("style")) {
            console.warn("Map style load failed, falling back to OSM raster:", e);
            try {
              map.setStyle(OSM_RASTER_FALLBACK_STYLE);
            } catch {
              // ignore fallback error
            }
          }
        });

        const markStyleReady = () => {
          if (!isMounted) return;
          map.resize();
          setMapLoaded(true);
        };
        // `load` waits for every external source. A stalled basemap must not
        // prevent our source-backed GIS overlays from rendering.
        map.on("style.load", markStyleReady);
        map.on("load", markStyleReady);
        map.on("dragstart", () => {
          setIsFollowingDriver(false);
          onToggleFollowDriver?.(false);
        });
        map.on("click", (e: any) => {
          if (e && e.lngLat && onMapClickRef.current) {
            onMapClickRef.current({
              latitude: Number(e.lngLat.lat.toFixed(6)),
              longitude: Number(e.lngLat.lng.toFixed(6)),
            });
          }
        });
        if (typeof map.isStyleLoaded === "function" && map.isStyleLoaded()) {
          markStyleReady();
        }
      } catch (err) {
        console.warn("MapLibre initialization skipped (headless/no WebGL):", err);
        if (typeof window !== "undefined") {
          setHasWebGL(false);
        }
      }
    }

    initMap();

    const resizeObserver = typeof ResizeObserver !== "undefined" && mapContainerRef.current
      ? new ResizeObserver(() => {
          if (mapInstanceRef.current) {
            mapInstanceRef.current.resize();
          }
        })
      : null;
    if (resizeObserver && mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }

    return () => {
      isMounted = false;
      resizeObserver?.disconnect();
      checkpointMarkersRef.current.forEach(({ marker }) => marker.remove());
      checkpointMarkersRef.current.clear();
      markerConstructorRef.current = null;
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
      if (typeof window !== "undefined" && (window as any).__maplibreInstance) {
        (window as any).__maplibreInstance = null;
      }
      fittedBoundsRef.current = "";
      candidateIdsRef.current = [];
      lineCoordinatesRef.current.clear();
      setMapLoaded(false);
    };
  }, [hasWebGL]);

  // Reconcile recorded layers after load, prop updates and timeline changes.
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !mapLoaded) return;
    if (allCoordinates.length) {
      const boundsKey = tripKeyCoordinates.length
        ? `${minLon},${minLat},${maxLon},${maxLat}`
        : "initial";
      if (fittedBoundsRef.current !== boundsKey && !isFollowingDriver) {
        map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 40, maxZoom: 19, duration: 0 });
        fittedBoundsRef.current = boundsKey;

        if (typeof map.setMaxZoom === "function") {
          map.setMaxZoom(19);
        }

      }
    }
    const candidateIds = candidateRoutes.map((r) => r.id);
    for (const id of candidateIdsRef.current.filter((id) => !candidateIds.includes(id))) {
      if (map.getLayer(`candidate-${id}-line`)) map.removeLayer(`candidate-${id}-line`);
      if (map.getSource(`candidate-${id}-source`)) map.removeSource(`candidate-${id}-source`);
      lineCoordinatesRef.current.delete(`candidate-${id}-source`);
    }
    candidateIdsRef.current = candidateIds;
    const line = (id: string, points: [number, number][], color: string, visible: boolean, width = 3.5, segments?: [number, number][][]) => {
      const sourceId = `${id}-source`;
      const layerId = `${id}-line`;
      const paths = segments?.filter((segment) => segment.length > 1);
      const data = (paths ? paths.length : points.length > 1)
        ? { type: "Feature", properties: {}, geometry: paths && paths.length > 1
          ? { type: "MultiLineString", coordinates: paths }
          : { type: "LineString", coordinates: paths ? paths[0] : points } }
        : { type: "FeatureCollection", features: [] };
      const source = map.getSource(sourceId), previous = lineCoordinatesRef.current.get(sourceId);
      if (!source) map.addSource(sourceId, { type: "geojson", data });
      else if (previous?.points !== points || previous?.segments !== segments) source.setData(data);
      lineCoordinatesRef.current.set(sourceId, { points, segments });
      if (!map.getLayer(layerId)) map.addLayer({
        id: layerId, type: "line", source: sourceId,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": color, "line-width": width },
      });
      map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      map.setPaintProperty(layerId, "line-width", width);
      map.setPaintProperty(layerId, "line-color", color);
    };
    line("pickup-route", derivedPickupRoute, "#2563eb", showRoute && !hasSegments);
    line("destination-route", derivedDestinationRoute, "#7c3aed", showRoute && !hasSegments);
    line("driver-trajectory", derivedBreadcrumbs, "#ea580c", showBreadcrumbs && !hasSegments, 4.5, breadcrumbSegments);
    const observations = { type: "FeatureCollection", features: observedBreadcrumbs.map((s) => ({
      type: "Feature", properties: { recorded_at: s.recorded_at }, geometry: { type: "Point", coordinates: s.position.coordinates },
    })) };
    if (map.getSource("driver-observations-source")) map.getSource("driver-observations-source").setData(observations);
    else map.addSource("driver-observations-source", { type: "geojson", data: observations });
    if (!map.getLayer("driver-observations")) map.addLayer({ id: "driver-observations", type: "circle", source: "driver-observations-source",
      paint: { "circle-radius": 2, "circle-color": "#ea580c", "circle-stroke-width": 1, "circle-stroke-color": "#ffffff" } });
    map.setLayoutProperty("driver-observations", "visibility", showBreadcrumbs ? "visible" : "none");
    const gapData = { type: "FeatureCollection", features: gapEndpoints.map(({ alert, role, coordinate }) => ({
      type: "Feature", properties: { alert_id: alert.alert_id, gap_role: role, start_time: alert.start_time, end_time: alert.end_time, gap_duration_s: alert.gap_duration_s, reason: alert.reason },
      geometry: { type: "Point", coordinates: coordinate },
    })) };
    if (map.getSource("gap-warnings-source")) map.getSource("gap-warnings-source").setData(gapData);
    else map.addSource("gap-warnings-source", { type: "geojson", data: gapData });
    if (!map.getLayer("gap-warnings")) map.addLayer({ id: "gap-warnings", type: "circle", source: "gap-warnings-source", paint: {
      "circle-radius": 7, "circle-color": "rgba(220, 38, 38, 0.2)", "circle-stroke-color": "#dc2626", "circle-stroke-width": 2,
    } });
    for (const route of candidateRoutes) {
      line(`candidate-${route.id}`, route.coordinates, route.color, showRoute, inspectedRouteId === route.id ? 6 : 3.5);
    }
    const points: Array<{ point: { longitude: number; latitude: number }; kind: string; color: string; label?: string; timestamp?: string; playback_mode?: string; vehicle_kind?: string }> = [
      ...(initialDriverPos ? [{ point: initialDriverPos, kind: "initial", color: "#4338ca", label: initialDriverPos.label || "Khởi hành" }] : []),
      ...(activeCustomer ? [{ point: activeCustomer, kind: "pickup", color: "#059669", label: activeCustomer.label || "Điểm đón khách" }] : []),
      ...(destinationPos ? [{ point: destinationPos, kind: "destination", color: "#7c3aed", label: destinationPos.label || "Đích đến" }] : []),
      ...(activeDriver ? [{ point: activeDriver, kind: "driver", color: "#059669", label: activeDriver.status || "", playback_mode: playback?.mode ?? "observed", vehicle_kind: vehicleKind(vehicleType) }] : []),
      ...(activeStall ? [{ point: activeStall, kind: "stall", color: "#dc2626" }] : []),
      ...(showHotspots ? activeHotspots.map((point) => ({ point, kind: "hotspot", color: "#d97706" })) : []),
      ...anomalyMilestones.map((m) => ({ point: { longitude: m.lon, latitude: m.lat }, kind: "anomaly", color: "#dc2626", timestamp: m.timestamp, label: `${m.title} (${m.timestamp.slice(11, 19)})` })),
    ];
    const pointData = { type: "FeatureCollection", features: points.map(({ point, ...properties }) => ({
      type: "Feature", properties,
      geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
    })) };
    const checkpointPoints = points.filter((point) => ["initial", "pickup", "destination", "driver"].includes(point.kind))
      .sort((a, b) => ["driver", "pickup", "destination", "initial"].indexOf(a.kind) - ["driver", "pickup", "destination", "initial"].indexOf(b.kind));
    const occupied: Array<{ x: number; y: number; radius: number }> = [];
    for (const [kind, entry] of checkpointMarkersRef.current) {
      if (!checkpointPoints.some((point) => point.kind === kind)) { entry.marker.remove(); checkpointMarkersRef.current.delete(kind); }
    }
    for (const { kind, point, label } of checkpointPoints) {
      const role = kind as "initial" | "pickup" | "destination" | "driver";
      const projected = typeof map.project === "function" ? map.project([point.longitude, point.latitude]) : null;
      const radius = kind === "driver" ? 14 : 12;
      const overlaps = (offset: [number, number]) => projected && occupied.some((p) =>
        Math.abs(p.x - projected.x - offset[0]) < p.radius + radius + 4 && Math.abs(p.y - projected.y - offset[1]) < p.radius + radius + 4);
      const previousOffset = checkpointMarkersRef.current.get(kind)?.offset;
      const draggableStopKind =
        draggableStops && (kind === "initial" || kind === "pickup" || kind === "destination");
      let offset: [number, number] = [0, 0];
      if (kind !== "driver" && !draggableStopKind && overlaps(offset)) {
        offset = previousOffset && !overlaps(previousOffset) ? previousOffset :
          ([[0, -32], [32, 0], [0, 32], [-32, 0], [0, -64], [64, 0]] as [number, number][]).find((candidate) => !overlaps(candidate)) ?? [0, -64];
      }
      if (projected) occupied.push({ x: projected.x + offset[0], y: projected.y + offset[1], radius });
      const leader = offset[0] || offset[1] ? `<svg aria-hidden="true" width="24" height="24" style="position:absolute;left:0;top:0;overflow:visible;z-index:-1"><line x1="12" y1="12" x2="${12 - offset[0]}" y2="${12 - offset[1]}" stroke="#565e74" stroke-width="1" stroke-dasharray="3 2"/></svg>` : "";
      const svg = markerSvg(role, vehicleType) + leader;
      let entry = checkpointMarkersRef.current.get(kind);
      if (!entry) {
        const element = document.createElement("div");
        element.setAttribute("role", "img");
        element.dataset.testid = kind === "initial" ? "driver-initial-marker" : kind === "pickup" ? "customer-pickup-marker" : kind === "destination" ? "destination-marker" : "driver-vehicle-marker";
        element.style.width = element.style.height = kind === "driver" ? "28px" : "24px";
        element.style.zIndex = kind === "driver" ? "3" : "2";
        element.innerHTML = svg;
        const marker = new markerConstructorRef.current({ element, anchor: "center", draggable: draggableStopKind })
          .setLngLat([point.longitude, point.latitude])
          .addTo(map);
        entry = { element, svg, marker };
        checkpointMarkersRef.current.set(kind, entry);
        if (draggableStopKind && typeof marker.on === "function") {
          marker.on("dragstart", () => {
            onStopDragStartRef.current?.(kind as "initial" | "pickup" | "destination");
          });
          marker.on("dragend", () => {
            onStopDragEndRef.current?.(kind as "initial" | "pickup" | "destination");
            const lngLat = marker.getLngLat();
            onStopDragRef.current?.(kind as "initial" | "pickup" | "destination", {
              latitude: lngLat.lat,
              longitude: lngLat.lng,
            });
          });
        }
        if (draggableStopKind) element.style.cursor = "grab";
      }
      if (entry.svg !== svg) { entry.element.innerHTML = svg; entry.svg = svg; }
      if (typeof entry.marker.setDraggable === "function") entry.marker.setDraggable(Boolean(draggableStopKind));
      const name = kind === "driver" ? `Tài xế · ${vehicleKind(vehicleType) === "car" ? "Ô tô" : vehicleKind(vehicleType) === "motorbike" ? "Xe máy" : "Chưa rõ phương tiện"}` : label || kind;
      entry.element.setAttribute("aria-label", name);
      entry.element.title = name;
      entry.element.dataset.longitude = String(point.longitude);
      entry.element.dataset.latitude = String(point.latitude);
      entry.offset = offset;
      entry.element.dataset.visualOffset = offset.join(",");
      if (typeof entry.marker.setOffset === "function") entry.marker.setOffset(offset);
      if (kind === "driver") entry.element.dataset.playbackMode = playback?.mode ?? "observed";
      entry.marker.setLngLat([point.longitude, point.latitude]);
    }
    if (isFollowingDriver && activeDriver && map) {
      map.easeTo({
        center: [activeDriver.longitude, activeDriver.latitude],
        duration: 300,
        essential: true,
      });
    }
    if (map.getSource("trip-points-source")) map.getSource("trip-points-source").setData(pointData);
    else map.addSource("trip-points-source", { type: "geojson", data: pointData });
    if (!map.getLayer("trip-points")) map.addLayer({ id: "trip-points", type: "circle", source: "trip-points-source", filter: ["!", ["in", ["get", "kind"], ["literal", ["initial", "pickup", "destination", "driver"]]]], paint: {
      "circle-color": ["get", "color"], "circle-radius": 6, "circle-stroke-width": 2, "circle-stroke-color": "#ffffff",
    } });
    if (!map.getLayer("trip-point-labels")) map.addLayer({ id: "trip-point-labels", type: "symbol", source: "trip-points-source", filter: ["!=", ["get", "kind"], "driver"], layout: {
      "text-field": ["coalesce", ["get", "label"], ""], "text-size": 11, "text-offset": [0, -1.5],
    }, paint: { "text-color": "#0f172a", "text-halo-color": "#ffffff", "text-halo-width": 1 } });

    // Waypoint numbered markers in MapLibre
    const currentWaypointIds = activeWaypoints.map((w) => w.id);
    for (const [id, entry] of waypointMarkersRef.current) {
      if (!currentWaypointIds.includes(id)) {
        entry.marker.remove();
        waypointMarkersRef.current.delete(id);
      }
    }
    if (markerConstructorRef.current) {
      activeWaypoints.forEach((wp, idx) => {
        const num = idx + 1;
        const html = `<div style="width:22px;height:22px;border-radius:50%;background:#f59e0b;color:#ffffff;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:11px;border:2px solid #ffffff;box-shadow:0 1px 3px rgba(0,0,0,0.3);">${num}</div>`;
        let entry = waypointMarkersRef.current.get(wp.id);
        if (!entry) {
          const element = document.createElement("div");
          element.setAttribute("role", "img");
          element.dataset.testid = `waypoint-marker-${num}`;
          element.setAttribute("aria-label", wp.name || `Điểm rẽ #${num}`);
          element.innerHTML = html;
          const marker = new markerConstructorRef.current({ element, anchor: "center" })
            .setLngLat([wp.lon, wp.lat])
            .addTo(map);
          entry = { marker, element };
          waypointMarkersRef.current.set(wp.id, entry);
        } else {
          entry.element.dataset.testid = `waypoint-marker-${num}`;
          entry.element.setAttribute("aria-label", wp.name || `Điểm rẽ #${num}`);
          entry.element.innerHTML = html;
          entry.marker.setLngLat([wp.lon, wp.lat]);
        }
      });
    }

    // Proximity circle (4 km rule)
    if (proximityCircle && proximityCircle.radiusM > 0) {
      const ring = createCircleCoordinates(proximityCircle.center, proximityCircle.radiusM, 64);
      const circleData = {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [ring],
        },
      };
      const src = map.getSource("proximity-circle-source");
      if (src) {
        src.setData(circleData);
      } else {
        map.addSource("proximity-circle-source", { type: "geojson", data: circleData });
        map.addLayer({
          id: "proximity-circle-fill",
          type: "fill",
          source: "proximity-circle-source",
          paint: { "fill-color": "#3b82f6", "fill-opacity": 0.08 },
        });
        map.addLayer({
          id: "proximity-circle-stroke",
          type: "line",
          source: "proximity-circle-source",
          paint: { "line-color": "#2563eb", "line-width": 1.5, "line-dasharray": [3, 2] },
        });
      }
    } else {
      if (map.getLayer("proximity-circle-stroke")) map.removeLayer("proximity-circle-stroke");
      if (map.getLayer("proximity-circle-fill")) map.removeLayer("proximity-circle-fill");
      if (map.getSource("proximity-circle-source")) map.removeSource("proximity-circle-source");
    }

    map.triggerRepaint();
  }, [allCoordinates, minLon, minLat, maxLon, maxLat, mapLoaded, derivedPickupRoute, derivedDestinationRoute, derivedBreadcrumbs, breadcrumbSegments, observedBreadcrumbs, gapEndpoints, candidateRoutes, activeDriver, playback?.mode, vehicleType, initialDriverPos, activeCustomer, destinationPos, activeStall, activeHotspots, anomalyMilestones, showRoute, showBreadcrumbs, showHotspots, hasSegments, inspectedRouteId, isFollowingDriver, draggableStops, activeWaypoints, proximityCircle]);

  const centerWholeTrip = () => {
    if (allCoordinates.length && mapInstanceRef.current) {
      mapInstanceRef.current.resize();
      mapInstanceRef.current.fitBounds([[minLon, minLat], [maxLon, maxLat]], {padding:48,maxZoom:16,duration:300});
    }
  };

  const toggleClass = (active: boolean) =>
    active
      ? "inline-flex h-7 items-center px-2 text-[10px] font-medium rounded-md bg-emerald-50 text-emerald-700 border border-emerald-300 shadow-2xs cursor-pointer"
      : "inline-flex h-7 items-center px-2 text-[10px] font-medium rounded-md bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors border border-slate-200 cursor-pointer";

  return (
    <div
      data-testid="maplibre-view"
      className={`relative w-full ${className?.includes("h-full") ? "flex-1 min-h-0" : ""} bg-slate-100 rounded border border-slate-200 overflow-hidden select-none flex flex-col ${className || ""}`}
    >
      {/* Missingness Alert Banner (Requirement 5) */}
      {missingnessAlerts && missingnessAlerts.length > 0 && (
        <div
          data-testid="data-missingness-alert-banner"
          title={missingnessAlerts[0].reason}
          className="bg-amber-50 border-b border-amber-200 px-3 py-1.5 flex items-center justify-between text-[11px] text-amber-900 font-mono"
        >
          <div className="flex items-center gap-1.5">
            <span className="text-amber-700 font-bold">{messages.dataGap}</span>
            <span>
              {Number(missingnessAlerts[0].gap_duration_s)}s
            </span>
          </div>
          <span className="text-[10px] text-amber-800 bg-white px-1.5 py-0.5 rounded border border-amber-200 font-semibold shadow-2xs">
            {missingnessAlerts[0].start_time.slice(11, 19)} - {missingnessAlerts[0].end_time.slice(11, 19)}
          </span>
        </div>
      )}

      {/* Top Action Bar: map actions, candidate routes, latency and layer toggles */}
      <div data-testid="map-control-chips" className="p-2 bg-white border-b border-slate-200 flex flex-wrap items-center justify-start gap-2 z-10">
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label={messages.centerTrip} title={messages.centerTrip} disabled={!allCoordinates.length} onClick={centerWholeTrip} className="p-1.5 rounded border border-slate-200 text-slate-700 hover:bg-slate-100 disabled:opacity-40"><span aria-hidden="true" className="material-symbols-outlined text-base">gps_fixed</span></button>
          <button
            type="button"
            data-testid="follow-driver-btn"
            aria-label={isFollowingDriver ? messages.followingTitle : messages.followTitle}
            title={isFollowingDriver ? messages.followingTitle : messages.followTitle}
            disabled={!activeDriver}
            onClick={() => {
              const next = !isFollowingDriver;
              setIsFollowingDriver(next);
              onToggleFollowDriver?.(next);
              if (next && activeDriver && mapInstanceRef.current) {
                mapInstanceRef.current.easeTo({
                  center: [activeDriver.longitude, activeDriver.latitude],
                  zoom: Math.max(mapInstanceRef.current.getZoom(), 15),
                  duration: 300,
                });
              }
            }}
            className={`inline-flex h-7 items-center px-2 rounded-md border text-[11px] font-medium gap-1 transition-all cursor-pointer ${
              isFollowingDriver
                ? "bg-emerald-700 text-white border-emerald-800 shadow-2xs font-semibold"
                : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50 disabled:opacity-40"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isFollowingDriver ? "bg-white animate-ping" : "bg-emerald-500"}`} />
            <span>{isFollowingDriver ? messages.followingDriver : messages.followDriver}</span>
          </button>
        </div>
        {/* Route Selector Pills (Requirement 1 & 4) */}
        {candidateRoutes && candidateRoutes.length > 0 ? (
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            <span className="text-[10px] font-bold text-slate-500 font-mono uppercase mr-1">{messages.route}</span>
            {candidateRoutes.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setInspectedRouteId((prev) => (prev === r.id ? null : r.id))}
                onMouseEnter={() => setInspectedRouteId(r.id)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded flex items-center gap-1 transition-all cursor-pointer ${
                  inspectedRouteId === r.id
                    ? "bg-emerald-700 text-white shadow-2xs font-semibold"
                    : "bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200"
                }`}
              >
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: r.color }} />
                <span>{r.name.split(":")[0]}</span>
              </button>
            ))}
          </div>
        ) : null}

        {/* GPS Latency & Layer Toggles */}
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {/* GPS Latency / Quality */}
          {latencyMs != null && (
            <div
              data-testid="gps-latency-indicator"
              className="inline-flex h-7 items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 text-[11px] font-mono text-emerald-700 font-medium"
              title={messages.gpsTitle}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              <span>{latencyMs}ms</span>
            </div>
          )}

          {/* Layer toggles */}
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => setShowTraffic((prev) => !prev)}
              disabled={trafficCorroboration === null}
              className={`${toggleClass(trafficCorroboration !== null && showTraffic)} disabled:cursor-default disabled:opacity-50`}
              title={trafficCorroboration === null ? `${messages.traffic}: ${messages.unavailable}` : messages.traffic}
            >
              {trafficCorroboration !== null && showTraffic ? `✓ ${messages.traffic}` : messages.traffic}
            </button>
            <button
              type="button"
              onClick={() => setShowBreadcrumbs((prev) => !prev)}
              className={toggleClass(showBreadcrumbs)}
              title={messages.breadcrumbs}
            >
              {showBreadcrumbs ? `✓ ${messages.breadcrumbs}` : messages.breadcrumbs}
            </button>
            <button
              type="button"
              onClick={() => setShowRoute((prev) => !prev)}
              className={toggleClass(showRoute)}
            title={messages.roadRoute}
            >
              {showRoute ? `✓ ${messages.roadRoute}` : messages.roadRoute}
            </button>
            <button
              type="button"
              onClick={() => setShowHotspots((prev) => !prev)}
              className={toggleClass(showHotspots)}
              title={messages.hotspots}
            >
              {showHotspots ? `✓ ${messages.hotspots}` : messages.hotspots}
            </button>
            <button
              type="button"
              onClick={() => setShowTrafficPanel((prev) => !prev)}
              disabled={trafficCorroboration === null}
              className={`${toggleClass(trafficCorroboration !== null && showTrafficPanel)} disabled:cursor-default disabled:opacity-50`}
              title={trafficCorroboration === null ? `${messages.corroboration}: ${messages.unavailable}` : messages.corroboration}
            >
              {trafficCorroboration !== null && showTrafficPanel ? `✓ ${messages.probeCheck}` : messages.probeCheck}
            </button>
          </div>
        </div>
      </div>

      {/* Availability stays in document flow, outside map markers and live playback readouts. */}
      {((hasTelemetrySource && normalizedTelemetry.length === 0)
        || ((routeGeometry !== undefined || pickupRoute !== undefined) && (!derivedPickupRoute.length || !derivedDestinationRoute.length))
        || trafficCorroboration === null) && (
        <div role="status" aria-label={messages.dataStatus} aria-atomic="true"
          className="flex flex-wrap items-center gap-2 px-2 py-1 bg-slate-50 border-b border-slate-200">
          {hasTelemetrySource && normalizedTelemetry.length === 0 && (
            <span data-testid="gps-unavailable-label" className="bg-white px-2 py-1 text-[11px] text-slate-600 rounded border border-slate-200 font-medium">GPS: <span className="font-sans font-medium text-slate-500">{messages.noData}</span></span>
          )}
          {(routeGeometry !== undefined || pickupRoute !== undefined) && (
            <>
              {derivedPickupRoute.length === 0 && derivedDestinationRoute.length === 0 && (
                <span data-testid="missing-route-both" className="bg-white px-2 py-1 text-[11px] text-slate-600 rounded border border-slate-200 font-medium">{messages.estimatedRoute}: <span className="font-sans font-medium text-slate-500">{messages.noData}</span></span>
              )}
              {derivedPickupRoute.length === 0 && derivedDestinationRoute.length > 0 && (
                <span data-testid="missing-route-pickup" className="bg-white px-2 py-1 text-[11px] text-slate-600 rounded border border-slate-200 font-medium">{messages.route} pickup: <span className="font-sans font-medium text-slate-500">{messages.noData}</span></span>
              )}
              {derivedDestinationRoute.length === 0 && derivedPickupRoute.length > 0 && (
                <span data-testid="missing-route-destination" className="bg-white px-2 py-1 text-[11px] text-slate-600 rounded border border-slate-200 font-medium">{messages.route} destination: <span className="font-sans font-medium text-slate-500">{messages.noData}</span></span>
              )}
            </>
          )}
          {trafficCorroboration === null && (
            <span data-testid="traffic-corroboration-panel" className="inline-flex min-h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-700 font-medium">
              {messages.noTraffic}
            </span>
          )}
        </div>
      )}

      {/* Main Map Area with Overlays */}
      <div style={mapHeight ? { height: mapHeight } : undefined} className={`relative w-full overflow-hidden ${mapHeight ? "" : className?.includes("h-full") ? "flex-1 h-full min-h-[380px]" : "h-64 sm:h-72"}`}>
        {hasSegments && <TripSegmentLayers mapRef={mapInstanceRef} ready={mapLoaded} segments={visibleSegments} cancel={visibleCancel} showTrack={showBreadcrumbs} showPlanned={showRoute} />}
        {hasSegments && <TripSegmentLegend kinds={legendKinds} showCancel={Boolean(cancelPoint)} />}
        {/* Main Map Canvas or SVG Headless Fallback */}
        {hasWebGL ? (
          <div
            ref={mapContainerRef}
            data-testid="maplibre-container"
            className="w-full h-full relative"
          >
            {/* Smooth loading overlay before tiles & layers are ready (prevents path glitch) */}
            {!mapLoaded && (
              <div
                data-testid="map-loading-overlay"
                className="absolute inset-0 bg-slate-100 flex flex-col items-center justify-center z-10 select-none transition-opacity duration-300 pointer-events-none"
              >
                <div className="flex items-center gap-2 text-[11px] text-slate-500 font-mono bg-white px-3 py-1.5 rounded-full border border-slate-200 shadow-2xs">
                  <span className="w-2 h-2 rounded-full bg-emerald-600 animate-ping" />
                  <span>{messages.loadingMap}</span>
                </div>
              </div>
            )}
          </div>
        ) : (
        /* Fallback Static GIS SVG for unit tests & headless environment */
        <div
          data-testid="maplibre-fallback"
          className={`w-full bg-slate-100 relative overflow-hidden ${className?.includes("h-full") ? "h-full min-h-[380px]" : "h-64 sm:h-72"}`}
        >
          {!normalizedTelemetry.length && !driverLocation && <span className="absolute z-10 left-3 top-3 text-xs text-slate-500">{messages.noTripData}</span>}
          {normalizedTelemetry.length > 0 && !derivedPickupRoute.length && <span className="absolute z-10 left-3 top-3 text-xs text-slate-500">{messages.noRoute}</span>}
          <svg
            className="w-full h-full"
            fill="none"
            viewBox="0 0 700 250"
            xmlns="http://www.w3.org/2000/svg"
          >
            <rect fill="#f8fafc" height="250" width="700" x="0" y="0"></rect>
            {showHotspots && activeHotspots.map((point, i) => (
              <g key={i} data-testid="hotspot-indicator" transform={transformFor(point)}>
                <circle r="20" fill="#f59e0b" fillOpacity="0.15" stroke="#d97706" />
                <title>{point.label || "Hotspot"}</title>
              </g>
            ))}
            {showRoute && candidateRoutes.map((route) => (
              <g key={route.id} data-testid={`candidate-route-${route.rank}`}>
                <path d={pathFor(route.coordinates)} stroke={route.color} strokeWidth="3" />
                <title>{route.name}</title>
              </g>
            ))}
            {showRoute && derivedPickupRoute.length > 1 && (
              <g data-testid="pickup-route"><path d={pathFor(derivedPickupRoute)} stroke="#2563eb" strokeWidth="3.5" /></g>
            )}
            {showRoute && derivedDestinationRoute.length > 1 && (
              <g data-testid="destination-route"><path d={pathFor(derivedDestinationRoute)} stroke="#7c3aed" strokeWidth="3.5" /></g>
            )}
            {showBreadcrumbs && observedBreadcrumbCount > 0 && (
              <g data-testid="driver-trajectory" data-point-count={observedBreadcrumbCount}>
                {breadcrumbSegments.map((segment, i) => <path key={i} d={pathFor(segment)} stroke="#ea580c" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />)}
              </g>
            )}
            {showBreadcrumbs && observedBreadcrumbs.map((s, i) => <circle key={i} data-testid="observed-gps-fix" cx={project(s.position.coordinates[0], s.position.coordinates[1]).x} cy={project(s.position.coordinates[0], s.position.coordinates[1]).y} r="2" fill="#ea580c"><title>{s.recorded_at}</title></circle>)}
            {initialDriverPos && <g data-testid="driver-initial-marker" transform={transformFor(initialDriverPos)}><g transform="translate(-12,-12)"><CheckpointIcon role="initial" /></g><title>{initialDriverPos.label || "Khởi hành"}</title></g>}
            {activeCustomer && <g data-testid="customer-pickup-marker" transform={transformFor(activeCustomer)}><g transform="translate(-12,-12)"><CheckpointIcon role="pickup" /></g><title>{activeCustomer.label || "Điểm đón khách"}</title></g>}
            {destinationPos && <g data-testid="destination-marker" transform={transformFor(destinationPos)}><g transform="translate(-12,-12)"><CheckpointIcon role="destination" /></g><title>{destinationPos.label || "Đích đến"}</title></g>}
            {activeDriver && <g data-testid="driver-vehicle-marker" data-longitude={activeDriver.longitude} data-latitude={activeDriver.latitude} data-playback-mode={playback?.mode ?? "observed"} transform={transformFor(activeDriver)}>
              <g transform="translate(-14,-14)"><CheckpointIcon role="driver" vehicleType={vehicleType} /></g>
              <text data-testid="trip-status-badge" x="10" y="-12" fill="#0f172a" fontSize="9">{activeDriver.status || "—"}</text>
            </g>}
            {activeStall && <g data-testid="stall-point-indicator" transform={transformFor(activeStall)}>
              <circle r="8" fill="#dc2626" /><title>{activeStall.label || `${activeStall.duration_seconds}s Stall`} | DAVI alert</title>
            </g>}
            {anomalyMilestones.map((m) => <g key={m.id} data-testid={`anomaly-${m.id}`} data-longitude={m.lon} data-latitude={m.lat} data-timestamp={m.timestamp} transform={transformFor({ longitude: m.lon, latitude: m.lat })}>
              <circle r="7" fill="#dc2626" stroke="#fff" /><title>{m.title} ({m.timestamp})</title>
            </g>)}
            {gapEndpoints.map((endpoint) => (
              <g key={endpoint.key} data-testid="gap-warning-marker" transform={transformFor({ longitude: endpoint.coordinate[0], latitude: endpoint.coordinate[1] })}>
                <circle r="7" fill="rgba(220, 38, 38, 0.2)" stroke="#dc2626" strokeWidth="2" strokeDasharray="3 2" />
                <title>{endpoint.tooltip}</title>
              </g>
            ))}
            {/* Proximity Circle Fallback */}
            {proximityCircle && (
              <g data-testid="proximity-circle">
                <circle
                  cx={project(proximityCircle.center.longitude, proximityCircle.center.latitude).x}
                  cy={project(proximityCircle.center.longitude, proximityCircle.center.latitude).y}
                  r="45"
                  fill="#3b82f6"
                  fillOpacity="0.08"
                  stroke="#2563eb"
                  strokeWidth="1.5"
                  strokeDasharray="4 2"
                />
              </g>
            )}
            {/* Numbered Waypoints Fallback */}
            {activeWaypoints.map((wp, i) => (
              <g
                key={wp.id}
                data-testid={`waypoint-marker-${i + 1}`}
                transform={transformFor({ latitude: wp.lat, longitude: wp.lon })}
              >
                <circle r="11" fill="#f59e0b" stroke="#ffffff" strokeWidth="2" />
                <text textAnchor="middle" dy="4" fill="#ffffff" fontSize="10" fontWeight="bold">
                  {i + 1}
                </text>
                <title>{wp.name || `Điểm rẽ #${i + 1}`}</title>
              </g>
            ))}
          </svg>
        </div>
      )}

        {/* Inspected Route Floating Detail Card (Requirement 4) */}
        {inspectedRoute && (
          <div
            data-testid="route-inspection-card"
            onMouseLeave={() => setInspectedRouteId(null)}
            className="absolute bottom-2 left-2 z-20 bg-white/95 backdrop-blur-xs p-2.5 rounded shadow-md border border-slate-200 text-[11px] font-mono space-y-1 max-w-sm pointer-events-auto transition-all"
          >
            <div className="flex items-center justify-between font-bold text-slate-800">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: inspectedRoute.color }} />
                {inspectedRoute.name}
              </span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] bg-blue-50 text-blue-700 px-1 rounded border border-blue-200">
                  Rank #{inspectedRoute.rank}
                </span>
                <button
                  type="button"
                  onClick={() => setInspectedRouteId(null)}
                  className="text-slate-400 hover:text-slate-600 text-[11px] ml-1 px-1 cursor-pointer"
                  title={messages.closeRoute}
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-slate-600 pt-0.5">
              <div>
                {messages.distance} <strong className="text-slate-900">{inspectedRoute.distance_m}m</strong>
              </div>
              <div>
                {messages.duration} <strong className="text-slate-900">{Math.round(inspectedRoute.duration_s / 60)} min</strong>
              </div>
              <div>
                DAVI: <strong className={inspectedRoute.davi < 0 ? "text-red-600" : "text-emerald-700"}>
                  {inspectedRoute.davi >= 0 ? `+${inspectedRoute.davi}` : inspectedRoute.davi}
                </strong>
              </div>
              <div>
                SDD: <strong className="text-slate-900">{inspectedRoute.sdd}</strong>
              </div>
              <div>
                {messages.signals} <strong className="text-slate-900">{inspectedRoute.traffic_signals_count}</strong>
              </div>
              <div>
                Mật độ: <strong className={inspectedRoute.congestion_level === "clear" ? "text-emerald-700" : "text-amber-700"}>
                  {inspectedRoute.congestion_level === "clear" ? messages.clear : messages.congested}
                </strong>
              </div>
            </div>
          </div>
        )}

        {/* Multi-Driver Traffic Corroboration Card (Requirement 3) - Light Theme & Auto-Hide */}
        {(showTraffic || showTrafficPanel) && trafficCorroboration && (
          <div
            data-testid="traffic-corroboration-panel"
            onMouseEnter={() => setIsTrafficHovered(true)}
            onMouseLeave={() => setIsTrafficHovered(false)}
            className={`absolute top-28 right-2 z-20 bg-white/95 text-slate-800 backdrop-blur-xs rounded border border-slate-200 text-[10px] font-mono pointer-events-auto transition-all duration-200 ${
              isTrafficExpanded
                ? "p-2.5 max-w-xs space-y-1.5 shadow-md"
                : "px-2 py-1 max-w-[210px] shadow-2xs hover:border-emerald-300 cursor-pointer"
            }`}
          >
            {/* Collapsed Pill Header */}
            {!isTrafficExpanded ? (
              <div className="flex items-center justify-between gap-1.5">
                <span className="font-semibold text-slate-700 flex items-center gap-1">
                  <span>🔍</span>
                  <span>{messages.corroboration} {(trafficCorroboration.peer_drivers ?? []).length} {locale === "vi" ? "xe" : "vehicles"}</span>
                </span>
                <span className="text-[9px] bg-amber-50 text-amber-800 px-1 py-0.5 rounded border border-amber-200 font-bold">
                  {trafficCorroboration.verdict === "refuted" ? messages.refuted : trafficCorroboration.verdict === "corroborated" ? messages.corroborated : messages.insufficientData}
                </span>
              </div>
            ) : (
              /* Expanded Full Header */
              <div className="flex items-center justify-between border-b border-slate-100 pb-1">
                <span className="font-bold text-amber-800 flex items-center gap-1">
                  <span>🔍</span>
                  <span>{messages.multiDriverCorroboration}</span>
                </span>
                <span className="text-[9px] text-slate-400 font-mono">
                  {(trafficCorroboration.observed_at ?? "").slice(11, 19)}
                </span>
              </div>
            )}

            {/* Detailed Corroboration Breakdown */}
            <div className={isTrafficExpanded ? "space-y-1.5 pt-0.5" : "hidden"}>
              {trafficCorroboration.road_segment ? (
                <div className="text-slate-600">
                  {messages.route} <strong className="text-slate-900">{trafficCorroboration.road_segment}</strong>
                </div>
              ) : null}
              <div className="bg-slate-50 p-1.5 rounded border border-slate-100 space-y-1">
                <div className="text-red-700">
                  • {messages.suspectDriver} <strong className="font-bold">{trafficCorroboration.suspect_driver?.speed_kmh} km/h</strong> ({locale === "vi" ? "Dừng" : "Stopped"} {trafficCorroboration.suspect_driver?.stall_duration_s}s)
                </div>
                <div className="text-emerald-700">
                  • {messages.publicService} ({trafficCorroboration.public_service?.provider}): <strong className="font-bold">{trafficCorroboration.public_service?.average_speed_kmh} km/h</strong> ({trafficCorroboration.public_service?.congestion === "clear" ? messages.clear : messages.congested})
                </div>
                <div className="text-slate-700">
                  • {messages.peerDrivers} {(trafficCorroboration.peer_drivers ?? []).map((p) => `${p.vehicle_plate}: ${Number(p.speed_kmh).toFixed(1)} km/h`).join(", ")}
                </div>
              </div>
              <div className="text-[10px] text-amber-900 font-bold bg-amber-50 p-1 rounded border border-amber-200">
                ⚖️ {messages.conclusion} {trafficCorroboration.verdict_detail}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Interactive Trip Timeline Bar (Requirements 1, 2, 3) - Emerald Sentinel Light Theme */}
      <div
        data-testid="trip-timeline-bar"
        className="p-2.5 bg-slate-50 text-slate-800 border-t border-slate-200 flex flex-col gap-2 select-none"
      >
        {/* Timeline Header & Live Scrub Status */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={totalDurationSec === 0}
              onClick={() => { if (!isPlaying && scrubSecond >= visibleEndSecond) setCurrentSecondOffset(visibleStartSecond); setIsPlaying((prev) => !prev); }}
              className="px-2.5 py-0.5 bg-emerald-700 hover:bg-emerald-800 text-white font-semibold rounded text-[10px] flex items-center gap-1 transition-colors cursor-pointer shadow-2xs"
            >
                <span>{isPlaying ? `⏸ ${messages.pause}` : `▶ ${messages.replay}`}</span>
            </button>
            <span className="text-slate-500">1×</span>
            {speedKmh != null && (
              <div
                data-testid="speedometer-readout"
                className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 text-[11px] font-mono font-bold text-slate-800"
                title={messages.speedTitle}
              >
                <span className="text-slate-400">⚡</span>
                <span>{speedKmh} km/h</span>
              </div>
            )}
            {normalizedTelemetry.length > 0 && <span data-testid="playback-quality" data-mode={playback?.mode ?? "unavailable"} className="text-slate-600">
              {playback?.mode === "interpolated" ? messages.estimatedRoute : playback?.mode === "gap" ? messages.gpsGapLastPosition : playback?.mode === "unmatched" ? messages.unknownRouteLastPosition : playback ? messages.recordedGps : messages.noGps}
            </span>}
            <span
              data-testid="active-timeline-status"
              className="font-bold text-emerald-900 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200"
            >
              {activeMilestone?.title && activeMilestone.type !== "start_match"
                ? `${activeMilestone.title} (${currentTimeFormatted})`
                : currentTimeFormatted}
            </span>
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-3 text-slate-500 text-[10px]">
            {validGapAlerts.length > 0 && (
              <div data-testid="timeline-gap-info" className="flex min-w-0 max-w-full flex-wrap items-center gap-1 overflow-hidden">
                {validGapAlerts.map((gap) => (
                  <span key={gap.alert_id} id={`gap-info-${gap.alert_id}`} data-testid="timeline-gap-tooltip"
                    title={gapExplanation(gap)}
                    className="min-w-0 max-w-full text-red-700 bg-red-50 px-1.5 py-0.5 rounded border border-red-200 font-medium">
                    <span className="sm:sr-only">
                      {gap.start_time.slice(11, 19)}–{gap.end_time.slice(11, 19)} · {Number(gap.gap_duration_s)}s
                    </span>
                    <span className="sr-only sm:not-sr-only">
                      {gapExplanation(gap)}
                    </span>
                  </span>
                ))}
              </div>
            )}
            <span className="inline-flex min-h-7 items-center gap-1">
              {messages.position} <strong className="text-slate-800">{activeDriver ? `${activeDriver.latitude.toFixed(4)}, ${activeDriver.longitude.toFixed(4)}` : "—"}</strong>
            </span>
            <span className="inline-flex min-h-7 items-center gap-1">
              DAVI: {(activeMilestone?.davi ?? activeStall?.davi_score ?? daviScore) == null ? <span className="font-sans font-medium text-slate-500">{messages.noData}</span> : <strong className={(activeMilestone?.davi ?? activeStall?.davi_score ?? daviScore)! < 0 ? "text-red-600" : "text-emerald-700"}>
                {activeMilestone?.davi ?? activeStall?.davi_score ?? daviScore}
              </strong>}
            </span>
          </div>
        </div>

        {/* Timeline Range Scrubber Slider flanked by Start Time (leftmost) and End Time (rightmost) */}
        <div className="flex flex-wrap items-center gap-2.5 w-full">
          <span
            data-testid="timeline-start-time"
            className="text-[11px] font-mono font-bold text-slate-700 bg-white px-2 py-0.5 rounded border border-slate-200 shrink-0 shadow-2xs"
            title={messages.startTime}
          >
            {visibleStartSecond ? new Date(startTimestampMs + visibleStartSecond * 1000).toISOString().slice(11, 19) : startTimeFormatted}
          </span>

          <div className="relative flex-1 min-w-24 py-1.5 flex items-center">
            <input type="range" aria-label={messages.replayTime} data-testid="timeline-scrubber-slider"
              aria-describedby={validGapAlerts.length ? validGapAlerts.map((gap) => `gap-info-${gap.alert_id}`).join(" ") : undefined}
              min={visibleStartSecond} max={visibleEndSecond} step={0.001} value={scrubSecond}
              onChange={(e) => seek(Number(e.target.value))}
              className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-emerald-600 relative z-10" />
            {visibleGaps.length > 0 && (
              <div data-testid="timeline-gap-bands" className="absolute inset-x-0 top-1/2 -translate-y-1/2 pointer-events-none z-20">
                {visibleGaps.map(({ gap, left, width }) => (
                  <span key={gap.alert_id} data-testid="timeline-gap-band" role="img"
                    aria-label={`Mất dữ liệu GPS ${Number(gap.gap_duration_s)}s từ ${gap.start_time.slice(11, 19)} đến ${gap.end_time.slice(11, 19)} · ${gap.reason}`}
                    style={{ left: `${left}%`, width: `${width}%`, background: "repeating-linear-gradient(45deg, rgba(220, 38, 38, 0.2), rgba(220, 38, 38, 0.2) 4px, rgba(220, 38, 38, 0.1) 4px, rgba(220, 38, 38, 0.1) 8px)", borderTop: "2px dashed #dc2626", borderBottom: "2px dashed #dc2626" }}
                    className="absolute top-1/2 -translate-y-1/2 h-2" />
                ))}
              </div>
            )}
            <div data-testid="timeline-checkpoint-marks" className="absolute inset-x-0 top-1/2 -translate-y-1/2 pointer-events-none z-20">
              {visibleMilestones.map((milestone) => {
                const second = (Date.parse(milestone.timestamp) - startTimestampMs) / 1000;
                const pct = (second - visibleStartSecond) / Math.max(0.001, visibleEndSecond - visibleStartSecond) * 100;
                return <span key={milestone.id} role="img" data-testid={`milestone-${milestone.type}`}
                  aria-label={`${milestone.title || 'Điểm bắt đầu'} (${milestone.timestamp})`}
                  style={{ left: `${pct}%` }}
                  className={`absolute -translate-x-1/2 -translate-y-1/2 w-0.5 h-3 rounded-full ring-1 ring-white ${milestone.is_anomaly ? 'bg-red-600' : milestone.type === 'pickup' ? 'bg-emerald-700' : milestone.type === 'dropoff_destination' ? 'bg-purple-700' : 'bg-slate-700'}`} />;
              })}
            </div>
          </div>
          <label className="sr-only" htmlFor="timeline-range-start">{messages.startRange}</label>
          <label className="text-[10px]" htmlFor="timeline-range-start">{locale === "vi" ? "Từ" : "From"}</label>
          <input id="timeline-range-start" aria-label={messages.startRange} type="range" min={0} max={visibleEndSecond} value={visibleStartSecond} onChange={(e) => setRangeStartSecond(Number(e.target.value))} className="w-24 accent-emerald-600" />
          <label className="text-[10px]" htmlFor="timeline-range-end">{messages.endRange}</label>
          <input id="timeline-range-end" aria-label={messages.endRange} type="range" min={visibleStartSecond} max={totalDurationSec} value={visibleEndSecond} onChange={(e) => setRangeEndSecond(Number(e.target.value))} className="w-24 accent-emerald-600" />

          <span
            data-testid="timeline-end-time"
            className="text-[11px] font-mono font-bold text-slate-700 bg-white px-2 py-0.5 rounded border border-slate-200 shrink-0 shadow-2xs"
            title={messages.endTime}
          >
            {visibleEndSecond !== totalDurationSec ? new Date(startTimestampMs + visibleEndSecond * 1000).toISOString().slice(11, 19) : endTimeFormatted}
          </span>
        </div>
      </div>

      {/* Kinematic Telemetry Footer Ribbon: measured values only, else the designed empty state */}
      {showKinematicFooter && (
        <div className="items-center p-2 bg-slate-50 border-t border-slate-200 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px] font-mono select-none">
          <div className="inline-flex min-w-0 min-h-7 items-center gap-1.5">
            <span aria-hidden="true" className={`w-2 h-2 rounded-full shrink-0 ${footerStallSeconds == null ? "bg-slate-300" : "bg-red-500 animate-pulse"}`}></span>
            <span className="text-slate-500">{messages.stallPoint}</span>
            {footerStallSeconds == null ? <span className="font-sans font-medium text-slate-500">{messages.noData}</span> : (
              <span data-testid="footer-stall-point" className="font-bold text-red-600 bg-red-50 px-1 py-0.5 rounded border border-red-200">
                {`${footerStallSeconds}s Stall`}
              </span>
            )}
          </div>
          <div className="inline-flex min-w-0 min-h-7 items-center gap-1.5">
            <span className="text-slate-500">{messages.daviDrift}</span>
            {footerDavi == null ? <span className="font-sans font-medium text-slate-500">{messages.noData}</span> : (
              <span data-testid="footer-davi-drift" className="font-bold text-amber-700 bg-amber-50 px-1 py-0.5 rounded border border-amber-200">
                {footerDavi}
              </span>
            )}
          </div>
          <div className="inline-flex min-w-0 min-h-7 items-center gap-1.5 sm:justify-end text-emerald-700 font-medium">
            <span className="material-symbols-outlined inline-flex items-center !text-[14px] !leading-none text-emerald-600 shrink-0">speed</span>
            <span data-testid="ambient-traffic-status">
              {messages.ambient} {trafficCorroboration?.public_service?.average_speed_kmh != null ? <strong className="text-slate-800">{`${trafficCorroboration.public_service.average_speed_kmh} km/h`}</strong> : <span className="font-sans font-medium text-slate-500">{messages.noData}</span>}
            </span>
          </div>
          </div>
      )}
    </div>
  );
}
