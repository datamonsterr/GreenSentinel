"use client";

import React from "react";
import { Badge } from "@/components/ui/badge";

export interface DriverCardData {
  driver_id: string;
  full_name: string;
  vehicle_plate?: string;
  vehicle_model?: string;
  rating?: number | string;
  acceptance_rate?: string | number;
  completion_rate?: string | number;
  account_status?: string;
  total_trips?: number | string;
  badge?: string;
}

export function DriverCardWidget({
  data,
  onSelectCase,
}: {
  data: DriverCardData;
  onSelectCase?: (caseId: string) => void;
}) {
  const isSuspended =
    data.account_status?.toUpperCase().includes("SUSPEND") ||
    data.account_status?.toUpperCase().includes("LOCK");
  const isInvestigating =
    data.account_status?.toUpperCase().includes("INVESTIGAT");

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/80 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gs-green-soft text-gs-green-ink font-semibold text-xs">
            {data.full_name ? data.full_name[0] : "D"}
          </div>
          <div>
            <div className="font-semibold text-slate-800 text-xs">
              {data.full_name || data.driver_id}
            </div>
            <div className="font-mono text-[10px] text-slate-500">
              {data.driver_id}
            </div>
          </div>
        </div>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
            isSuspended
              ? "bg-gs-red-soft text-gs-red"
              : isInvestigating
              ? "bg-gs-amber-soft text-gs-amber-ink"
              : "bg-gs-green-soft text-gs-green-ink"
          }`}
        >
          {data.account_status || "ACTIVE"}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 p-2.5 text-[11px]">
        {data.vehicle_plate && (
          <div className="space-y-0.5">
            <span className="text-[10px] text-slate-400">Phương tiện</span>
            <div className="font-mono font-medium text-slate-700">
              {data.vehicle_plate}{" "}
              <span className="text-[10px] font-normal text-slate-500">
                ({data.vehicle_model || "VF e34"})
              </span>
            </div>
          </div>
        )}
        {data.rating !== undefined && (
          <div className="space-y-0.5">
            <span className="text-[10px] text-slate-400">Đánh giá</span>
            <div className="flex items-center gap-1 font-medium text-gs-amber-ink">
              <span className="material-symbols-outlined text-[12px]">star</span>
              <span>{data.rating}</span>
              {data.total_trips && (
                <span className="text-[10px] text-slate-400">
                  ({data.total_trips} chuyến)
                </span>
              )}
            </div>
          </div>
        )}
        {data.acceptance_rate && (
          <div className="space-y-0.5">
            <span className="text-[10px] text-slate-400">Tỉ lệ nhận cuốc (AR)</span>
            <div className="font-mono font-medium text-slate-700">
              {data.acceptance_rate}
            </div>
          </div>
        )}
        {data.completion_rate && (
          <div className="space-y-0.5">
            <span className="text-[10px] text-slate-400">Tỉ lệ hoàn thành (CR)</span>
            <div className="font-mono font-medium text-slate-700">
              {data.completion_rate}
            </div>
          </div>
        )}
      </div>
      {data.badge && (
        <div className="border-t border-slate-50 bg-slate-50/40 px-3 py-1 text-[10px] text-slate-500">
          Hạng đối tác: <span className="font-medium text-slate-700">{data.badge}</span>
        </div>
      )}
    </div>
  );
}

export interface ChoiceOption {
  id: string;
  label: string;
  detail?: string;
  description?: string;
}

export interface ChoiceSelectorData {
  title?: string;
  description?: string;
  options: ChoiceOption[];
}

export function ChoiceSelectorWidget({
  data,
  onSelectChoice,
}: {
  data: ChoiceSelectorData;
  onSelectChoice?: (choiceId: string, label: string) => void;
}) {
  const [selected, setSelected] = React.useState<string | null>(null);

  return (
    <div className="my-2 rounded-lg border border-slate-200 bg-white p-2.5 shadow-xs space-y-2">
      {data.title && (
        <div className="flex items-center gap-1.5 font-semibold text-xs text-slate-800">
          <span className="material-symbols-outlined text-[14px] text-gs-green-ink">
            checklist
          </span>
          <span>{data.title}</span>
        </div>
      )}
      {data.description && (
        <p className="text-[10px] text-slate-500">{data.description}</p>
      )}
      <div className="space-y-1.5">
        {data.options.map((opt) => {
          const isSelected = selected === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => {
                setSelected(opt.id);
                onSelectChoice?.(opt.id, opt.label);
              }}
              className={`w-full text-left rounded border px-2.5 py-1.5 text-xs transition-colors flex items-start gap-2 ${
                isSelected
                  ? "border-gs-green bg-gs-green-soft text-gs-green-ink font-medium"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
            >
              <span
                className={`mt-0.5 material-symbols-outlined text-[13px] ${
                  isSelected ? "text-gs-green-ink" : "text-slate-400"
                }`}
              >
                {isSelected ? "check_circle" : "radio_button_unchecked"}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-medium">{opt.label}</div>
                {(opt.detail || opt.description) && (
                  <div className="text-[10px] text-slate-500 truncate">
                    {opt.detail || opt.description}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface ListItem {
  id?: string;
  case_id?: string;
  title?: string;
  driver_name?: string;
  plate_number?: string;
  vehicle_model?: string;
  status?: string;
  priority?: string;
  badge?: string;
  created_at?: string;
}

export interface ListSelectorData {
  title?: string;
  total_related_cases?: number;
  vehicle_plate?: string;
  multi_driver_sharing_flag?: boolean;
  risk_summary?: string;
  related_cases?: ListItem[];
  items?: ListItem[];
}

export function ListSelectorWidget({
  data,
  onSelectCase,
}: {
  data: ListSelectorData;
  onSelectCase?: (caseId: string) => void;
}) {
  const items = data.related_cases || data.items || [];

  return (
    <div className="my-2 rounded-lg border border-slate-200 bg-white p-2.5 shadow-xs space-y-2">
      <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-xs text-slate-800">
          <span className="material-symbols-outlined text-[14px] text-gs-blue">
            format_list_bulleted
          </span>
          <span>
            {data.title ||
              `Lịch sử phương tiện ${data.vehicle_plate || ""} (${items.length} vụ việc)`}
          </span>
        </div>
        {data.multi_driver_sharing_flag && (
          <span className="rounded bg-gs-red-soft px-1.5 py-0.5 text-[9px] font-bold text-gs-red">
            CẢNH BÁO TRÁO XE
          </span>
        )}
      </div>

      {data.risk_summary && (
        <div className="rounded bg-gs-amber-soft border border-gs-amber/30 p-1.5 text-[10px] text-gs-amber-ink flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[12px] text-gs-amber-ink">
            warning
          </span>
          <span>{data.risk_summary}</span>
        </div>
      )}

      <div className="max-h-52 overflow-y-auto space-y-1 pr-1">
        {items.map((item, idx) => {
          const caseRef = item.case_id || item.id || `item-${idx}`;
          return (
            <div
              key={idx}
              onClick={() => {
                if (item.case_id && onSelectCase) onSelectCase(item.case_id);
              }}
              className="flex items-center justify-between rounded border border-slate-100 bg-slate-50/70 p-2 text-xs hover:border-gs-green/30 hover:bg-gs-green-soft/50 cursor-pointer transition-colors"
            >
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-1 font-mono font-medium text-[11px] text-slate-800">
                  <span className="material-symbols-outlined text-[11px] text-slate-400">
                    folder
                  </span>
                  <span>{caseRef}</span>
                  {item.priority && (
                    <span className="rounded bg-gs-red-soft px-1 text-[9px] font-bold text-gs-red">
                      {item.priority}
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-slate-500">
                  {item.driver_name ? `Tài xế: ${item.driver_name} · ` : ""}
                  {item.plate_number || item.vehicle_model || ""}
                </div>
              </div>
              <div className="text-right">
                <span className="rounded bg-slate-200/80 px-1.5 py-0.5 text-[9px] uppercase font-semibold text-slate-700">
                  {item.status || "CLOSED"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export interface TicketData {
  ticket_id: string;
  driver_id: string;
  case_id: string;
  violation_code: string;
  penalty_type: string;
  fine_amount_vnd?: number;
  suspension_hours?: number;
  reason?: string;
  rationale?: string;
  policy_clause?: string;
  created_at?: string;
  issued_at?: string;
}

export function TicketPreviewWidget({ data }: { data: TicketData }) {
  const fine = data.fine_amount_vnd ? `${data.fine_amount_vnd.toLocaleString()} VNĐ` : "0 VNĐ";

  return (
    <div className="my-2 overflow-hidden rounded-lg border-2 border-dashed border-gs-red/30 bg-gs-red-soft/30 p-3 shadow-xs space-y-2">
      <div className="flex items-center justify-between border-b border-gs-red/30 pb-2">
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-gs-red text-[16px]">
            receipt_long
          </span>
          <span className="font-bold text-xs uppercase tracking-wide text-gs-red">
            Biên bản xử phạt hành vi vi phạm
          </span>
        </div>
        <span className="font-mono text-[10px] font-bold text-gs-red bg-gs-red-soft px-1.5 py-0.5 rounded">
          {data.ticket_id}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <span className="text-[10px] text-slate-500">Tài xế bị xử phạt:</span>
          <div className="font-mono font-semibold text-slate-800">{data.driver_id}</div>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">Hành vi vi phạm:</span>
          <div className="font-bold text-gs-red">{data.violation_code}</div>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">Mức phạt tiền:</span>
          <div className="font-mono font-bold text-gs-green-ink">{fine}</div>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">Chế tài đình chỉ:</span>
          <div className="font-semibold text-gs-amber-ink">
            {data.suspension_hours ? `Tạm khóa ${data.suspension_hours} giờ` : "Không tạm khóa"}
          </div>
        </div>
      </div>

      {(data.reason || data.rationale) && (
        <div className="rounded bg-white/80 p-2 text-[10px] border border-gs-red/30 text-slate-700">
          <span className="font-semibold text-slate-800">Lý do chế tài:</span>{" "}
          {data.reason || data.rationale}
        </div>
      )}

      <div className="flex items-center justify-between pt-1 text-[9px] text-slate-500">
        <span>Căn cứ: {data.policy_clause || "Quy chế vận hành GreenSM 2026"}</span>
        <span className="font-medium text-gs-green-ink flex items-center gap-0.5">
          <span className="material-symbols-outlined text-[10px]">verified</span>
          Đã ký điện tử & ghi log
        </span>
      </div>
    </div>
  );
}

export interface WeatherData {
  temperature_c?: number;
  relative_humidity_pct?: number;
  precipitation_mm?: number;
  wind_speed_kmh?: number;
  condition_desc?: string;
  weather_code?: number;
  force_majeure?: boolean;
  force_majeure_note?: string;
  source?: string;
}

export function WeatherWidget({ data }: { data: WeatherData }) {
  const isFM = Boolean(data.force_majeure);

  return (
    <div className="my-2 rounded-lg border border-slate-200 bg-white p-2.5 shadow-xs space-y-2">
      <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-xs text-slate-800">
          <span className="material-symbols-outlined text-[15px] text-gs-cyan">
            partly_cloudy_day
          </span>
          <span>Thời tiết thực địa (Open-Meteo Live)</span>
        </div>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            isFM ? "bg-gs-green-soft text-gs-green-ink" : "bg-slate-100 text-slate-600"
          }`}
        >
          {isFM ? "Miễn trừ Điều 12.2" : "Bình thường"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center text-[11px]">
        <div className="rounded bg-gs-cyan-soft/50 p-1.5 border border-gs-cyan/30">
          <div className="text-[10px] text-slate-500">Nhiệt độ</div>
          <div className="font-mono font-bold text-gs-cyan">{data.temperature_c ?? 28}°C</div>
        </div>
        <div className="rounded bg-gs-cyan-soft/50 p-1.5 border border-gs-cyan/30">
          <div className="text-[10px] text-slate-500">Lượng mưa</div>
          <div className="font-mono font-bold text-gs-cyan">{data.precipitation_mm ?? 0} mm</div>
        </div>
        <div className="rounded bg-gs-cyan-soft/50 p-1.5 border border-gs-cyan/30">
          <div className="text-[10px] text-slate-500">Tốc độ gió</div>
          <div className="font-mono font-bold text-gs-cyan">{data.wind_speed_kmh ?? 10} km/h</div>
        </div>
      </div>

      <div className="text-[10px] text-slate-600 flex items-center justify-between">
        <span>Hiện trạng: <span className="font-medium text-slate-800">{data.condition_desc || "Quang đãng"}</span></span>
        {data.relative_humidity_pct && (
          <span className="text-slate-400">Độ ẩm: {data.relative_humidity_pct}%</span>
        )}
      </div>

      {data.force_majeure_note && (
        <div
          className={`rounded p-1.5 text-[10px] border ${
            isFM
              ? "bg-gs-green-soft border-gs-green/30 text-gs-green-ink font-medium"
              : "bg-slate-50 border-slate-200 text-slate-600"
          }`}
        >
          {data.force_majeure_note}
        </div>
      )}
    </div>
  );
}

export interface TrafficData {
  distance_km?: number;
  baseline_duration_sec?: number;
  observed_speed_kmh?: number;
  congestion_ratio?: number;
  congestion_level?: string;
  corroborates_delay?: boolean;
  verdict?: string;
  source?: string;
}

export function TrafficWidget({ data }: { data: TrafficData }) {
  const isCongested = data.corroborates_delay || data.congestion_level === "heavy_gridlock";
  const baselineMin = data.baseline_duration_sec ? Math.round(data.baseline_duration_sec / 60) : 10;

  return (
    <div className="my-2 rounded-lg border border-slate-200 bg-white p-2.5 shadow-xs space-y-2">
      <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-xs text-slate-800">
          <span className="material-symbols-outlined text-[15px] text-gs-amber">
            traffic
          </span>
          <span>Đối soát giao thông hành trình (OSRM)</span>
        </div>
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            isCongested ? "bg-gs-amber-soft text-gs-amber-ink" : "bg-gs-green-soft text-gs-green-ink"
          }`}
        >
          {data.congestion_level || "clear"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center text-[11px]">
        <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
          <div className="text-[10px] text-slate-500">Khoảng cách</div>
          <div className="font-mono font-bold text-slate-800">{data.distance_km ?? 5} km</div>
        </div>
        <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
          <div className="text-[10px] text-slate-500">Thời gian chuẩn</div>
          <div className="font-mono font-bold text-slate-800">{baselineMin} phút</div>
        </div>
        <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
          <div className="text-[10px] text-slate-500">Vận tốc đo được</div>
          <div className="font-mono font-bold text-slate-800">{data.observed_speed_kmh ?? 25} km/h</div>
        </div>
      </div>

      {data.verdict && (
        <div
          className={`rounded p-1.5 text-[10px] border ${
            isCongested
              ? "bg-gs-amber-soft border-gs-amber/30 text-gs-amber-ink font-medium"
              : "bg-gs-green-soft border-gs-green/30 text-gs-green-ink font-medium"
          }`}
        >
          {data.verdict}
        </div>
      )}
    </div>
  );
}

/**
 * Parses XML blocks (<driver_card>, <choice_selector>, <list_selector>, <ticket_preview>,
 * <weather_widget>, <traffic_widget>) and renders interactive Next AI SDK widgets.
 */
export function renderChatContent(
  text: string,
  callbacks?: {
    onSelectCase?: (caseId: string) => void;
    onSendChoice?: (text: string) => void;
    renderFallback?: (plainText: string) => React.ReactNode;
  }
): React.ReactNode {
  if (!text) return null;

  const xmlRegex = /(<(?:driver_card|choice_selector|list_selector|ticket_preview|weather_widget|traffic_widget)>[\s\S]*?<\/(?:driver_card|choice_selector|list_selector|ticket_preview|weather_widget|traffic_widget)>)/g;
  const parts = text.split(xmlRegex);

  return parts.map((part, index) => {
    if (!part) return null;

    if (part.startsWith("<driver_card>") && part.endsWith("</driver_card>")) {
      const jsonStr = part.replace(/^<driver_card>/, "").replace(/<\/driver_card>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return <DriverCardWidget key={index} data={payload} onSelectCase={callbacks?.onSelectCase} />;
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (part.startsWith("<choice_selector>") && part.endsWith("</choice_selector>")) {
      const jsonStr = part.replace(/^<choice_selector>/, "").replace(/<\/choice_selector>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return (
          <ChoiceSelectorWidget
            key={index}
            data={payload}
            onSelectChoice={(id, label) => callbacks?.onSendChoice?.(`Chọn: ${label} (${id})`)}
          />
        );
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (part.startsWith("<list_selector>") && part.endsWith("</list_selector>")) {
      const jsonStr = part.replace(/^<list_selector>/, "").replace(/<\/list_selector>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return <ListSelectorWidget key={index} data={payload} onSelectCase={callbacks?.onSelectCase} />;
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (part.startsWith("<ticket_preview>") && part.endsWith("</ticket_preview>")) {
      const jsonStr = part.replace(/^<ticket_preview>/, "").replace(/<\/ticket_preview>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return <TicketPreviewWidget key={index} data={payload} />;
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (part.startsWith("<weather_widget>") && part.endsWith("</weather_widget>")) {
      const jsonStr = part.replace(/^<weather_widget>/, "").replace(/<\/weather_widget>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return <WeatherWidget key={index} data={payload} />;
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (part.startsWith("<traffic_widget>") && part.endsWith("</traffic_widget>")) {
      const jsonStr = part.replace(/^<traffic_widget>/, "").replace(/<\/traffic_widget>$/, "").trim();
      try {
        const payload = JSON.parse(jsonStr);
        return <TrafficWidget key={index} data={payload} />;
      } catch {
        return <span key={index}>{part}</span>;
      }
    }

    if (callbacks?.renderFallback) {
      return <React.Fragment key={index}>{callbacks.renderFallback(part)}</React.Fragment>;
    }
    return <span key={index}>{part}</span>;
  });
}
