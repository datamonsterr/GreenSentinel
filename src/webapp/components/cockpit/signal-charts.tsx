"use client";

import React from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceDot, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Compass, Gauge, LocateOff, TrendingUp } from "lucide-react";
import { useLocale } from "@/lib/locale";
import type { MockRatio, SpeedComparison, SpeedMarker, SpeedPoint } from "@/lib/cockpit-signals";
import { EmptyState } from "./empty-state";
import { SectionCard } from "./section-card";
import { formatClock, numberLocale } from "./messages";

const copy = {
  en: {
    speedTitle: "Speed over time", speedSub: "km/h from telemetry samples", speedEmpty: "Speed samples appear when telemetry arrives.",
    speed: "Trip speed", ambient: "Ambient traffic", stop: "Stop", davi: "DAVI deviation",
    daviTitle: "DAVI heading score", daviSub: "Range −1 to 1; lower = larger deviation from the expected heading", daviEmpty: "DAVI score is not computed yet.",
    compareTitle: "Trip vs traffic speed", compareSub: "Same road segment, km/h", compareEmpty: "No traffic reference recorded yet.",
    trip: "Trip", provider: "Traffic provider", peers: "Peer vehicles (avg)",
    mockTitle: "GPS mock-location ratio", mockSub: "Samples reporting a mock location", mockEmpty: "No GPS samples carry the mock-location flag yet.",
    flagged: "Mock", clean: "Clean", samples: "samples",
  },
  vi: {
    speedTitle: "Tốc độ theo thời gian", speedSub: "km/h từ mẫu telemetry", speedEmpty: "Mẫu tốc độ sẽ hiển thị khi có telemetry.",
    speed: "Tốc độ chuyến", ambient: "Giao thông xung quanh", stop: "Điểm dừng", davi: "Lệch DAVI",
    daviTitle: "Điểm hướng DAVI", daviSub: "Thang −1 đến 1; càng thấp càng lệch hướng dự kiến", daviEmpty: "Chưa tính điểm DAVI.",
    compareTitle: "Tốc độ chuyến và giao thông", compareSub: "Cùng đoạn đường, km/h", compareEmpty: "Chưa có dữ liệu giao thông đối chứng.",
    trip: "Chuyến đi", provider: "Nhà cung cấp giao thông", peers: "Xe đối chứng (TB)",
    mockTitle: "Tỷ lệ vị trí GPS giả", mockSub: "Mẫu báo cáo vị trí giả", mockEmpty: "Chưa có mẫu GPS mang cờ vị trí giả.",
    flagged: "Giả", clean: "Sạch", samples: "mẫu",
  },
} as const;

function useCopy() {
  const { locale } = useLocale();
  return { t: copy[locale], locale };
}

export function SpeedOverTimeChart({ series, markers, ambientKmh }: { series: SpeedPoint[]; markers: SpeedMarker[]; ambientKmh: number | null }) {
  const { t, locale } = useCopy();
  const config = {
    speed: { label: t.speed, color: "#0fb3c1" },
    ambient: { label: t.ambient, color: "#5a6b78" },
  } satisfies ChartConfig;
  return (
    <SectionCard icon={TrendingUp} tone="success" title={t.speedTitle} subtitle={t.speedSub} headingLevel={3}>
      {series.length < 2 ? <EmptyState compact icon={TrendingUp} hint={t.speedEmpty} /> : (
        <>
          <ChartContainer config={config} className="aspect-auto h-48 w-full">
            <LineChart data={series} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="time" type="number" scale="time" domain={["dataMin", "dataMax"]} tickLine={false} axisLine={false} tickMargin={6} minTickGap={40} tickFormatter={(value: number) => formatClock(new Date(value).toISOString(), locale) ?? ""} />
              <YAxis tickLine={false} axisLine={false} width={44} />
              <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, payload) => formatClock(new Date(Number(payload?.[0]?.payload?.time)).toISOString(), locale)} />} />
              {ambientKmh !== null && <ReferenceLine y={ambientKmh} stroke="var(--color-ambient)" strokeDasharray="4 4" label={{ value: `${t.ambient} ${ambientKmh} km/h`, position: "insideTopLeft", fontSize: 10, fill: "#5a6b78" }} />}
              <Line dataKey="speed" type="monotone" stroke="var(--color-speed)" strokeWidth={2} dot={false} isAnimationActive={false} />
              {markers.map((marker, index) => (
                <ReferenceDot key={`${marker.kind}-${index}`} x={marker.time} y={marker.speed} r={5} fill={marker.kind === "stop" ? "#e0484b" : "#c99616"} stroke="#fff" />
              ))}
            </LineChart>
          </ChartContainer>
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-600">
            <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="h-0.5 w-3 bg-primary" />{t.speed}</span>
            {ambientKmh !== null && <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="h-0 w-3 border-t border-dashed border-slate-500" />{t.ambient}</span>}
            {markers.some(marker => marker.kind === "stop") && <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-2 rounded-full bg-gs-red" />{t.stop}</span>}
            {markers.some(marker => marker.kind === "davi") && <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="size-2 rounded-full bg-gs-amber" />{t.davi}</span>}
          </div>
        </>
      )}
    </SectionCard>
  );
}

/** Display bands for the gauge arc only; they are not a verdict threshold. */
function daviColor(score: number): string {
  if (score < 0.3) return "#e0484b";
  if (score < 0.6) return "#c99616";
  return "#22a45d";
}

export function DaviGauge({ score }: { score: number | null }) {
  const { t, locale } = useCopy();
  const config = { score: { label: t.daviTitle, color: score === null ? "#8794a2" : daviColor(score) } } satisfies ChartConfig;
  return (
    <SectionCard icon={Compass} tone="violet" title={t.daviTitle} subtitle={t.daviSub} headingLevel={3}>
      {score === null ? <EmptyState compact icon={Compass} hint={t.daviEmpty} /> : (
        <div className="relative">
          <ChartContainer config={config} className="aspect-auto h-36 w-full">
            <PieChart>
              <Pie data={[{ value: (score + 1) / 2 }, { value: 1 - (score + 1) / 2 }]} dataKey="value" startAngle={180} endAngle={0} cx="50%" cy="85%" innerRadius="95%" outerRadius="130%" stroke="none" isAnimationActive={false}>
                <Cell fill="var(--color-score)" />
                <Cell fill="#e2e7ec" />
              </Pie>
            </PieChart>
          </ChartContainer>
          <p className="absolute inset-x-0 bottom-1 text-center text-3xl font-bold tabular-nums" style={{ color: daviColor(score) }}>
            {score.toLocaleString(numberLocale(locale), { maximumFractionDigits: 3 })}
          </p>
        </div>
      )}
    </SectionCard>
  );
}

export function SpeedComparisonBars({ rows }: { rows: SpeedComparison[] }) {
  const { t } = useCopy();
  const labels: Record<SpeedComparison["key"], string> = { trip: t.trip, ambient: t.provider, peers: t.peers };
  const colors: Record<SpeedComparison["key"], string> = { trip: "#0fb3c1", ambient: "#5a6b78", peers: "#2f6fe0" };
  const data = rows.map(row => ({ ...row, label: labels[row.key], fill: colors[row.key] }));
  const config = { speed: { label: "km/h" } } satisfies ChartConfig;
  return (
    <SectionCard icon={Gauge} tone="info" title={t.compareTitle} subtitle={t.compareSub} headingLevel={3}>
      {!rows.length ? <EmptyState compact icon={Gauge} hint={t.compareEmpty} /> : (
        <ChartContainer config={config} className="aspect-auto h-36 w-full">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 40, left: 0, bottom: 0 }}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={120} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="speed" radius={4} isAnimationActive={false} label={{ position: "right", fontSize: 12, fontWeight: 700, fill: "#1c2733", formatter: (value: number) => `${value} km/h` }}>
              {data.map(row => <Cell key={row.key} fill={row.fill} />)}
            </Bar>
          </BarChart>
        </ChartContainer>
      )}
    </SectionCard>
  );
}

export function MockLocationDonut({ ratio }: { ratio: MockRatio | null }) {
  const { t } = useCopy();
  const config = { flagged: { label: t.flagged, color: "#e0484b" }, clean: { label: t.clean, color: "#c8d0d8" } } satisfies ChartConfig;
  return (
    <SectionCard icon={LocateOff} tone="danger" title={t.mockTitle} subtitle={t.mockSub} headingLevel={3}>
      {ratio === null ? <EmptyState compact icon={LocateOff} hint={t.mockEmpty} /> : (
        <div className="flex items-center gap-4">
          <div className="relative h-32 w-32 shrink-0">
            <ChartContainer config={config} className="aspect-square h-32 w-32">
              <PieChart>
                <Pie data={[{ name: "flagged", value: ratio.flagged }, { name: "clean", value: ratio.total - ratio.flagged }]} dataKey="value" nameKey="name" innerRadius={40} outerRadius={60} stroke="none" isAnimationActive={false}>
                  <Cell fill="var(--color-flagged)" />
                  <Cell fill="var(--color-clean)" />
                </Pie>
              </PieChart>
            </ChartContainer>
            <span className={`absolute inset-0 flex items-center justify-center text-xl font-bold tabular-nums ${ratio.flagged ? "text-gs-red" : "text-slate-900"}`}>
              {Math.round(ratio.ratio * 100)}%
            </span>
          </div>
          <dl className="space-y-1 text-[13px]">
            <div className="flex items-center gap-2"><span aria-hidden="true" className="size-2.5 rounded-full bg-gs-red" /><dt className="text-slate-600">{t.flagged}</dt><dd className="font-bold tabular-nums text-slate-900">{ratio.flagged}</dd></div>
            <div className="flex items-center gap-2"><span aria-hidden="true" className="size-2.5 rounded-full bg-slate-300" /><dt className="text-slate-600">{t.clean}</dt><dd className="font-bold tabular-nums text-slate-900">{ratio.total - ratio.flagged}</dd></div>
          </dl>
          <p className="self-end text-[11px] text-slate-500">{ratio.total} {t.samples}</p>
        </div>
      )}
    </SectionCard>
  );
}
