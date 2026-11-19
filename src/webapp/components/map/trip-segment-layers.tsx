"use client";

import React, { useEffect, useRef } from "react";
import { useLocale } from "@/lib/locale";
import { SEGMENT_STYLE, type SegmentKind, type TripSegment } from "@/lib/trip-segments";

export interface CancelPoint { longitude: number; latitude: number; timestamp?: string | null; label?: string }

const copy = {
  en: { planned: "Planned route", actual: "Actual GPS track", offroute: "Off-route", gap: "GPS gap / dropout", postcancel: "After cancel", cancel: "Cancelled", distance: "Distance", speed: "Avg speed", time: "Time", reason: "Reason" },
  vi: { planned: "Lộ trình đặt xe", actual: "GPS thực tế", offroute: "Lệch tuyến", gap: "Mất GPS", postcancel: "Sau khi hủy", cancel: "Hủy đơn", distance: "Quãng đường", speed: "TB tốc độ", time: "Thời gian", reason: "Lý do" },
} as const;

const hhmmss = (ms: number | null) => (ms == null ? "—" : new Date(ms).toISOString().slice(11, 19));
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const SRC = "trip-segments-source", CANCEL_SRC = "trip-cancel-source";
const LAYERS = ["trip-seg-casing", "trip-seg-solid", "trip-seg-dashed", "trip-cancel", "trip-cancel-label"];

export function segmentTooltip(seg: TripSegment, t: Record<keyof typeof copy.en, string>): string {
  const first = seg.times.find((x) => x != null) ?? null, last = [...seg.times].reverse().find((x) => x != null) ?? null;
  const rows = [
    `<b style="color:${SEGMENT_STYLE[seg.kind].color}">${esc(t[seg.kind])}</b>`,
    `${t.time}: ${hhmmss(first)} – ${hhmmss(last)}`,
    `${t.distance}: ${seg.distanceM >= 1000 ? `${(seg.distanceM / 1000).toFixed(2)} km` : `${Math.round(seg.distanceM)} m`}`,
    ...(seg.avgSpeedKmh != null && seg.kind !== "planned" ? [`${t.speed}: ${seg.avgSpeedKmh.toFixed(1)} km/h`] : []),
    ...(seg.reason ? [`${t.reason}: ${esc(seg.reason)}`] : []),
  ];
  return rows.join("<br/>");
}

interface LayersProps {
  mapRef: React.MutableRefObject<any>;
  ready: boolean;
  segments: TripSegment[];
  cancel?: CancelPoint | null;
  showTrack: boolean;
  showPlanned: boolean;
}

/** GeoJSON line layers + hover tooltips for classified trip segments; renders no DOM. */
export function TripSegmentLayers({ mapRef, ready, segments, cancel, showTrack, showPlanned }: LayersProps) {
  const { locale } = useLocale();
  const t = copy[locale] ?? copy.en;
  const popupRef = useRef<any>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const visible = segments.filter((s) => s.coords.length > 1 && (s.kind === "planned" ? showPlanned : showTrack));
    const data = { type: "FeatureCollection", features: visible.map((s, i) => ({
      type: "Feature", id: i,
      properties: { kind: s.kind, color: SEGMENT_STYLE[s.kind].color, width: SEGMENT_STYLE[s.kind].width, dashed: Boolean(SEGMENT_STYLE[s.kind].dash), tip: segmentTooltip(s, t) },
      geometry: { type: "LineString", coordinates: s.coords },
    })) };
    const cancelData = { type: "FeatureCollection", features: cancel && showTrack ? [{
      type: "Feature", properties: { tip: `<b>${esc(cancel.label ?? t.cancel)}</b>${cancel.timestamp ? `<br/>${hhmmss(Date.parse(cancel.timestamp))}` : ""}`, label: cancel.label ?? t.cancel },
      geometry: { type: "Point", coordinates: [cancel.longitude, cancel.latitude] },
    }] : [] };
    if (map.getSource(SRC)) map.getSource(SRC).setData(data); else map.addSource(SRC, { type: "geojson", data });
    if (map.getSource(CANCEL_SRC)) map.getSource(CANCEL_SRC).setData(cancelData); else map.addSource(CANCEL_SRC, { type: "geojson", data: cancelData });
    const line = { "line-cap": "round", "line-join": "round" };
    if (!map.getLayer("trip-seg-casing")) map.addLayer({ id: "trip-seg-casing", type: "line", source: SRC, layout: line, paint: { "line-color": "#ffffff", "line-width": ["+", ["get", "width"], 4], "line-opacity": 0.95 } });
    if (!map.getLayer("trip-seg-solid")) map.addLayer({ id: "trip-seg-solid", type: "line", source: SRC, filter: ["!", ["get", "dashed"]], layout: line, paint: { "line-color": ["get", "color"], "line-width": ["get", "width"] } });
    if (!map.getLayer("trip-seg-dashed")) map.addLayer({ id: "trip-seg-dashed", type: "line", source: SRC, filter: ["get", "dashed"], layout: { "line-cap": "butt", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-dasharray": [2, 1.5] } });
    if (!map.getLayer("trip-cancel")) map.addLayer({ id: "trip-cancel", type: "circle", source: CANCEL_SRC, paint: { "circle-radius": 8, "circle-color": "#0d1826", "circle-stroke-width": 3, "circle-stroke-color": "#ffffff" } });
    if (!map.getLayer("trip-cancel-label")) map.addLayer({ id: "trip-cancel-label", type: "symbol", source: CANCEL_SRC, layout: { "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.6], "text-anchor": "top" }, paint: { "text-color": "#0d1826", "text-halo-color": "#ffffff", "text-halo-width": 1.2 } });
  }, [mapRef, ready, segments, cancel, showTrack, showPlanned, t]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let cancelled = false;
    const handlers: Array<[string, string, (e: any) => void]> = [];
    (async () => {
      const maplibregl = await import("maplibre-gl");
      if (cancelled) return;
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, className: "trip-seg-popup" });
      popupRef.current = popup;
      const move = (e: any) => {
        const f = e.features?.[0];
        if (!f) return;
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML(`<div style="font-size:12px;line-height:1.45">${f.properties.tip}</div>`).addTo(map);
      };
      const leave = () => { map.getCanvas().style.cursor = ""; popup.remove(); };
      for (const layer of ["trip-seg-solid", "trip-seg-dashed", "trip-cancel", "trip-points"]) {
        if (!map.getLayer(layer)) continue;
        const onMove = layer === "trip-points"
          ? (e: any) => { const p = e.features?.[0]?.properties; if (p?.label) move({ ...e, features: [{ properties: { tip: `<b>${esc(String(p.label))}</b>${p.timestamp ? `<br/>${String(p.timestamp).slice(11, 19)}` : ""}` } }] }); }
          : move;
        map.on("mousemove", layer, onMove); map.on("mouseleave", layer, leave);
        handlers.push(["mousemove", layer, onMove], ["mouseleave", layer, leave]);
      }
    })();
    return () => {
      cancelled = true;
      for (const [type, layer, fn] of handlers) map.off(type, layer, fn);
      popupRef.current?.remove();
    };
  }, [mapRef, ready, segments.length]);

  return null;
}

/** Compact legend, mirrors the admin-portal reference map legend. */
export function TripSegmentLegend({ kinds, showCancel }: { kinds: SegmentKind[]; showCancel?: boolean }) {
  const { locale } = useLocale();
  const t = copy[locale] ?? copy.en;
  if (!kinds.length && !showCancel) return null;
  return (
    <div data-testid="trip-segment-legend" className="pointer-events-none absolute bottom-7 left-3 z-10 grid max-w-[calc(100%-24px)] grid-cols-2 gap-x-4 gap-y-1 rounded-[10px] bg-white px-3 py-2 text-[12px] text-slate-800 shadow-[0_2px_10px_rgba(13,24,38,0.15)]">
      {kinds.map((kind) => (
        <span key={kind} className="flex items-center gap-1.5 whitespace-nowrap">
          <i aria-hidden="true" className="inline-block w-[18px]" style={{ borderTop: `${Math.min(5, SEGMENT_STYLE[kind].width)}px ${SEGMENT_STYLE[kind].dash ? "dashed" : "solid"} ${SEGMENT_STYLE[kind].color}` }} />
          {t[kind]}
        </span>
      ))}
      {showCancel && <span className="flex items-center gap-1.5 whitespace-nowrap"><i aria-hidden="true" className="inline-block size-2.5 rounded-full border-2 border-white bg-[#0d1826] shadow-[0_0_0_1px_#0d1826]" />{t.cancel}</span>}
    </div>
  );
}
