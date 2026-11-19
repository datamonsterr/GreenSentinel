"use client";

import React, { useMemo, useState } from "react";
import { Activity, BatteryMedium, ChevronDown, ChevronRight, CloudSun, Crosshair, Gauge, Globe, LocateOff, Navigation, NetworkIcon, Radar, Route, ShieldCheck, Signal, Timer, TrafficCone, Users, Waypoints, type LucideIcon } from "lucide-react";
import { MapLibreView, extractCoordinates, type CustomerLocationInfo } from "@/components/map/maplibre-view";
import { classifyTripSegments, plannedSegment, type LonLat } from "@/lib/trip-segments";
import type { CaseDetailResponse, DisputeDossierResponse } from "@/types/schemas";
import { useLocale } from "@/lib/locale";
import { daviScore, finite, mockLocationRatio, speedComparison, speedMarkers, speedSeries } from "@/lib/cockpit-signals";
import { IconTile, type Tone } from "@/components/cockpit/icon-tile";
import { MetricCard } from "@/components/cockpit/metric-card";
import { MetricGrid } from "@/components/cockpit/metric-grid";
import { EmptyState } from "@/components/cockpit/empty-state";
import { TripStatusRow } from "@/components/cockpit/trip-status-row";
import { DaviGauge, MockLocationDonut, SpeedComparisonBars, SpeedOverTimeChart } from "@/components/cockpit/signal-charts";
import { numberLocale } from "@/components/cockpit/messages";

export interface MapsTabProps {
  caseDetail: CaseDetailResponse;
  disputeDossier?: DisputeDossierResponse | null;
  selectedCaseId: string;
  pickupLocation?: CustomerLocationInfo;
  initialDriverLocation?: { latitude: number; longitude: number; label?: string };
  destinationLocation?: { latitude: number; longitude: number; label?: string };
  mapTelemetry: Array<Record<string, any>>;
  isActive?: boolean;
}

const copy = {
  en: {
    heading: "Maps and trip evidence", charts: "Signal charts",
    traffic: "Traffic corroboration",
    sensors: "Platform and Sensor Reliability", telemetry: "Stall and Drift Telemetry",
    ambient: "Ambient conditions", probe: "Probe check", simulated: "Simulated",
    segment: "Road segment", avgSpeed: "Average speed", congestion: "Congestion", provider: "Provider", peers: "Peer vehicles", source: "Evidence source",
    gpsAccuracy: "GPS accuracy", gpsAccuracyHint: "Observed GPS accuracy", mock: "Mock location", ping: "Ping latency", battery: "Battery",
    stall: "Stall duration", drift: "Drift distance", samples: "Telemetry samples", point: "Point",
    cancelled: "Cancelled", noTraffic: "No traffic reference recorded for this trip yet.", noSection: "Nothing recorded for this check yet.",
  },
  vi: {
    heading: "Bản đồ và dữ liệu hành trình", charts: "Biểu đồ tín hiệu",
    traffic: "Đối soát giao thông",
    sensors: "Độ tin cậy nền tảng và cảm biến", telemetry: "Telemetry dừng và lệch tuyến",
    ambient: "Thời tiết môi trường", probe: "Kiểm tra probe", simulated: "Mô phỏng",
    segment: "Đoạn đường", avgSpeed: "Tốc độ trung bình", congestion: "Ùn tắc", provider: "Nhà cung cấp", peers: "Xe đối chứng", source: "Nguồn đo",
    gpsAccuracy: "Độ chính xác GPS", gpsAccuracyHint: "Độ chính xác GPS thực tế", mock: "Vị trí giả", ping: "Độ trễ ping", battery: "Pin",
    stall: "Thời gian dừng", drift: "Khoảng lệch tuyến", samples: "Mẫu telemetry", point: "Điểm",
    cancelled: "Hủy đơn", noTraffic: "Chưa có dữ liệu giao thông đối chứng cho chuyến này.", noSection: "Chưa ghi nhận dữ liệu cho mục này.",
  },
} as const;

const labelFor = (key: string) => key.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const present = (value: unknown) => value !== null && value !== undefined && value !== "";
const show = (value: unknown) => (present(value) ? String(value) : null);

function CollapsibleSection({ icon, tone, title, summary, open, onToggle, children }: {
  icon: LucideIcon; tone: Tone; title: string; summary?: React.ReactNode; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <section aria-label={title} className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex min-w-0 items-center gap-2 pr-3">
        <button type="button" aria-expanded={open} onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg p-3 text-left hover:bg-slate-50 focus-visible:outline-emerald-600">
          <IconTile icon={icon} tone={tone} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900">{title}</span>
          <Chevron aria-hidden="true" size={18} className="block shrink-0 text-slate-400" />
        </button>
        {summary}
      </div>
      {open && <div className="border-t border-slate-100 p-3">{children}</div>}
    </section>
  );
}

export const MapsTab: React.FC<MapsTabProps> = ({
  caseDetail,
  selectedCaseId,
  pickupLocation,
  initialDriverLocation,
  destinationLocation,
  mapTelemetry,
  isActive = true,
}) => {
  const { locale } = useLocale();
  const t = copy[locale];
  const fmt = (value: number, digits = 1) => value.toLocaleString(numberLocale(locale), { maximumFractionDigits: digits });
  const [open, setOpen] = useState<Record<string, boolean>>({ traffic: true, sensors: false, telemetry: false, ambient: false, probe: false });
  const toggle = (key: string) => setOpen((current) => ({ ...current, [key]: !current[key] }));
  const traffic = caseDetail.traffic_corroboration;
  const evidence = caseDetail.cockpit_evidence ?? {};
  const samples = mapTelemetry.length ? mapTelemetry : (caseDetail.telemetry_samples ?? []);
  const latest = mapTelemetry.length ? mapTelemetry[mapTelemetry.length - 1] : undefined;
  const features = (caseDetail.features ?? {}) as Record<string, unknown>;
  const sensor = (key: string) => latest?.[key] ?? features[key] ?? evidence.sensor_reliability?.[key] ?? evidence.stall_davi?.[key];
  const unit = (value: unknown, suffix: string) => (finite(value) === null ? show(value) : `${fmt(finite(value)!)}${suffix}`);

  // Raw samples (incl. null-coordinate dropouts) so GPS gaps render as gap segments.
  const { tripSegments, cancelPoint } = useMemo(() => {
    const planned: LonLat[] = [
      ...extractCoordinates(caseDetail.route_geometry?.pickup_route?.coordinates ?? caseDetail.route_geometry?.pickup_route?.route?.coordinates),
      ...extractCoordinates(caseDetail.route_geometry?.destination_route?.coordinates ?? caseDetail.route_geometry?.destination_route?.route?.coordinates),
    ];
    const trip = caseDetail.trip;
    const cancelled = /cancel/i.test(String(trip?.status ?? "")) && Number.isFinite(Date.parse(trip?.ended_at ?? ""));
    const cancelAtMs = cancelled ? Date.parse(trip!.ended_at!) : null;
    const raw = caseDetail.telemetry_samples ?? [];
    const actual = classifyTripSegments({ samples: raw, planned, gaps: caseDetail.missingness_alerts, cancelAtMs });
    const plan = plannedSegment(planned);
    const fixes = raw.map((s) => ({ s, c: s?.position?.coordinates, t: Date.parse(s.recorded_at ?? s.occurred_at) })).filter((f) => Array.isArray(f.c) && Number.isFinite(f.c[0]) && Number.isFinite(f.c[1]) && Number.isFinite(f.t));
    const at = cancelAtMs == null ? undefined : [...fixes].reverse().find((f) => f.t <= cancelAtMs) ?? fixes[fixes.length - 1];
    return {
      tripSegments: [...(plan ? [plan] : []), ...actual],
      cancelPoint: at ? { longitude: Number(at.c[0]), latitude: Number(at.c[1]), timestamp: trip?.ended_at ?? null, label: t.cancelled } : null,
    };
  }, [caseDetail.route_geometry, caseDetail.telemetry_samples, caseDetail.missingness_alerts, caseDetail.trip, t.cancelled]);

  const stallSeconds = finite(sensor("stall_duration_s")) ?? finite(traffic?.suspect_driver?.stall_duration_s);
  const davi = daviScore(caseDetail, samples);
  const series = speedSeries(samples);
  const markers = speedMarkers(caseDetail.timeline_milestones, series);
  const ambientKmh = finite(traffic?.public_service?.average_speed_kmh);
  const peers = traffic?.peer_drivers;

  const knownSensorKeys = new Set(["gps_accuracy_m", "mock_location_detected", "ping_latency_ms", "battery_level_pct", "is_simulated"]);
  const extraSensors = Object.entries(evidence.sensor_reliability ?? {}).filter(([key, value]) => !knownSensorKeys.has(key) && present(value));
  const entries = (record: Record<string, unknown> | null | undefined) => Object.entries(record ?? {}).filter(([key, value]) => key !== "is_simulated" && present(value) && typeof value !== "object");
  const simulatedChip = (record: Record<string, unknown> | null | undefined) => record?.is_simulated === true
    ? <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{t.simulated}</span>
    : null;
  const ambient = entries(evidence.ambient);
  const probe = entries(evidence.probe);

  return (
    <div role="tabpanel" id="panel-maps" aria-labelledby="tab-maps" className="space-y-3 rounded-b-lg border-x border-b border-slate-200 bg-slate-50/60 px-3 pb-3 pt-0.5 text-xs">
      <h2 className="sr-only">{t.heading}</h2>
      {isActive && <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs">
        <MapLibreView caseId={selectedCaseId} vehicleType={caseDetail.trip?.vehicle_type} customerLocation={pickupLocation} driverInitialLocation={initialDriverLocation} destinationLocation={destinationLocation} candidateRoutes={caseDetail.candidate_routes} trafficCorroboration={caseDetail.traffic_corroboration} timelineMilestones={caseDetail.timeline_milestones} missingnessAlerts={caseDetail.missingness_alerts} telemetrySamples={mapTelemetry} routeGeometry={caseDetail.route_geometry} tripSegments={tripSegments} cancelPoint={cancelPoint} mapHeight={520} showKinematicFooter stallDurationSeconds={stallSeconds} daviScore={davi} />
      </div>}
      <TripStatusRow caseDetail={caseDetail} />
      <section aria-label={t.charts} className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <SpeedOverTimeChart series={series} markers={markers} ambientKmh={ambientKmh} />
        <DaviGauge score={davi} />
        <SpeedComparisonBars rows={speedComparison(caseDetail)} />
        <MockLocationDonut ratio={mockLocationRatio(samples)} />
      </section>
      <CollapsibleSection icon={TrafficCone} tone="warning" title={t.traffic} open={open.traffic} onToggle={() => toggle("traffic")}>
        {traffic ? (
          <MetricGrid>
            <MetricCard icon={Route} tone="info" variant="text" label={t.segment} value={show(traffic.road_segment)} />
            <MetricCard icon={Gauge} tone="info" label={t.avgSpeed} value={ambientKmh === null ? null : `${fmt(ambientKmh)} km/h`} />
            <MetricCard icon={TrafficCone} tone="warning" variant="text" label={t.congestion} value={show(traffic.public_service?.congestion)} />
            <MetricCard icon={Globe} tone="neutral" variant="text" label={t.provider} value={show(traffic.public_service?.provider)} />
            <MetricCard icon={Users} tone="violet" label={t.peers} value={Array.isArray(peers) ? fmt(peers.length, 0) : null} />
            <MetricCard icon={ShieldCheck} tone="success" variant="text" label={t.source} value={show((traffic as unknown as Record<string, unknown>).source)} />
          </MetricGrid>
        ) : <EmptyState compact icon={TrafficCone} hint={t.noTraffic} />}
      </CollapsibleSection>
      <CollapsibleSection icon={Signal} tone="violet" title={t.sensors} open={open.sensors} onToggle={() => toggle("sensors")} summary={simulatedChip(evidence.sensor_reliability)}>
        <MetricGrid>
          <MetricCard icon={Crosshair} tone="info" label={t.gpsAccuracy} hint={t.gpsAccuracyHint} value={unit(sensor("gps_accuracy_m"), " m")} />
          <MetricCard icon={LocateOff} tone="danger" variant="text" label={t.mock} value={show(sensor("mock_location_detected"))} severity={sensor("mock_location_detected") === true ? "danger" : undefined} />
          <MetricCard icon={NetworkIcon} tone="neutral" label={t.ping} value={unit(sensor("ping_latency_ms"), " ms")} />
          <MetricCard icon={BatteryMedium} tone="success" label={t.battery} value={unit(sensor("battery_level_pct") ?? sensor("battery_pct"), "%")} />
          {extraSensors.filter(([key]) => key !== "battery_pct").map(([key, value]) => <MetricCard key={key} icon={Activity} label={labelFor(key)} value={show(value)} variant={finite(value) === null ? "text" : "number"} />)}
        </MetricGrid>
      </CollapsibleSection>
      <CollapsibleSection icon={Timer} tone="info" title={t.telemetry} open={open.telemetry} onToggle={() => toggle("telemetry")}>
        <MetricGrid>
          <MetricCard icon={Timer} tone="warning" label={t.stall} value={unit(sensor("stall_duration_s"), "s")} />
          <MetricCard icon={Navigation} tone="violet" label="DAVI" value={show(sensor("davi_score") ?? sensor("davi"))} />
          <MetricCard icon={Waypoints} tone="info" label={t.drift} value={unit(sensor("drift_distance_m"), " m")} />
          <MetricCard icon={Radar} tone="neutral" label={t.samples} value={mapTelemetry.length ? fmt(mapTelemetry.length, 0) : null} />
          {entries(evidence.stall_davi).map(([key, value]) => <MetricCard key={key} icon={Activity} label={labelFor(key)} value={show(value)} variant={finite(value) === null ? "text" : "number"} />)}
          {(evidence.stall_davi_points ?? []).slice(0, 8).map((point, index) => (
            <MetricCard key={`stall-point-${index}`} icon={Activity} variant="text" label={`${t.point} ${index + 1}`} value={Object.entries(point).filter(([key]) => key !== "is_simulated").map(([key, value]) => `${key}: ${value}`).join(" · ") || null} />
          ))}
        </MetricGrid>
      </CollapsibleSection>
      <CollapsibleSection icon={CloudSun} tone="info" title={t.ambient} open={open.ambient} onToggle={() => toggle("ambient")} summary={simulatedChip(evidence.ambient)}>
        {ambient.length ? (
          <MetricGrid>{ambient.map(([key, value]) => <MetricCard key={key} icon={CloudSun} tone="info" label={labelFor(key)} value={show(value)} variant={finite(value) === null ? "text" : "number"} />)}</MetricGrid>
        ) : <EmptyState compact icon={CloudSun} hint={t.noSection} />}
      </CollapsibleSection>
      <CollapsibleSection icon={Radar} tone="success" title={t.probe} open={open.probe} onToggle={() => toggle("probe")} summary={simulatedChip(evidence.probe)}>
        {probe.length ? (
          <MetricGrid>{probe.map(([key, value]) => <MetricCard key={key} icon={Radar} tone="success" label={labelFor(key)} value={show(value)} variant={finite(value) === null ? "text" : "number"} />)}</MetricGrid>
        ) : <EmptyState compact icon={Radar} hint={t.noSection} />}
      </CollapsibleSection>
    </div>
  );
};

export default MapsTab;
