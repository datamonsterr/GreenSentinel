"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Link from "next/link";
import { isolatedGisBuild } from "@/lib/isolated-gis-build";
import dynamic from "next/dynamic";
import {
  Play,
  Pause,
  AlertTriangle,
  MapPin,
  User,
  Car,
  Activity,
  Navigation,
  RotateCcw,
  Check,
  Compass,
  Send,
  ExternalLink,
  Loader2,
  ChevronDown,
  ChevronUp,
  Flag,
  X,
} from "lucide-react";
import {
  setTestApiTokenProvider,
  postTest,
  TestSample,
  resolveTestRoute,
  RouteResolveResponse,
  searchGeocode,
  GeocodeLocation,
  publishSimulationToProduction,
  ProductionPublishResult,
  fetchTestRuns,
  fetchTestRunOverview,
  updateTestRunTitle,
  cancelTestRun,
  fetchTestPresets,
  fetchTestActors,
  TestRunSummary,
  TestRunOverview,
  TestPreset,
  TestPresetTrip,
  planTestPreset,
  TestActorDirectory,
  CancellationActor,
  controlTestRun,
  fetchRunTrace,
  TestRunTraceStage,
  ExpectedLabel,
  ClerkLinkedDriver,
} from "@/lib/testApiClient";
import { clampToRadius, nearestLeg } from "@/lib/geo";
import { WaypointPanel, WaypointItem } from "@/components/test-console/WaypointPanel";
import { SpeedControl } from "@/components/test-console/SpeedControl";
import { TripPipeline } from "@/components/test-console/TripPipeline";
import { DriverSearch } from "@/components/test-console/DriverSearch";
import { useAuth } from "@clerk/nextjs";
import { observeTestRun } from "@/lib/test-run-stream";
import { HistoryTable } from "@/components/test-console/HistoryTable";
import { PresetDetail } from "@/components/test-console/presets/PresetDetail";

// MapLibreView requires browser canvas — same component as production /workplace
const MapLibreView = dynamic(
  () => import("@/components/map/maplibre-view").then((m) => m.MapLibreView),
  { ssr: false, loading: () => <div className="w-full h-full bg-surface-container animate-pulse" /> }
);

type RunStatus =
  | "IDLE"
  | "QUEUED"
  | "RUNNING"
  | "PAUSED"
  | "STOP_MOVEMENT"
  | "CANCELLED"
  | "COMPLETED"
  | "FAILED";
type ConsoleTab = "manual" | "presets" | "history";
type DockTab = "log" | "overview";

interface ChatMessage {
  id: string;
  sender: "DRIVER" | "CUSTOMER";
  text: string;
  time: string;
}

interface LogEntry {
  id: string;
  time: string;
  event: string;
  state: string;
  details?: string;
}

interface ScenarioForm {
  originAddress: string;
  originLat: string;
  originLon: string;
  pickupAddress: string;
  pickupLat: string;
  pickupLon: string;
  destAddress: string;
  destLat: string;
  destLon: string;
  speedMps: string;
  driverId: string;
  passengerId: string;
  vehicleId: string;
  policyVersionId: string;
}

const DEFAULT_FORM: ScenarioForm = {
  originAddress: "Hồ Hoàn Kiếm, Hà Nội",
  originLat: "21.0285",
  originLon: "105.8524",
  pickupAddress: "Vincom Center Bà Triệu, Hà Nội",
  pickupLat: "21.0118",
  pickupLon: "105.8497",
  destAddress: "Quảng trường Ba Đình, Hà Nội",
  destLat: "21.0345",
  destLon: "105.8342",
  speedMps: "12",
  driverId: "",
  passengerId: "pass-sim-001",
  vehicleId: "veh-sim-001",
  policyVersionId: "pol-sim-001",
};

const INITIAL_CONVERSATION: ChatMessage[] = [
  { id: "init-1", sender: "DRIVER", text: "Tôi đã nhận cuốc và đang di chuyển tới điểm đón.", time: "10:00:00" },
  { id: "init-2", sender: "CUSTOMER", text: "Vâng, tôi đang đợi trước sảnh.", time: "10:00:15" },
];

const CUSTOM_LOCATION_LABEL = "Vị trí tuỳ chỉnh trên bản đồ";

/** Compact, coordinate-free address field. Address search is the single-pointer alternative to dragging. */
function StopRow({
  label,
  icon,
  value,
  disabled,
  onSelect,
  tone,
}: {
  label: string;
  icon: React.ReactNode;
  value: string;
  disabled?: boolean;
  onSelect: (item: GeocodeLocation) => void;
  tone: "emerald" | "blue" | "rose";
}) {
  const [query, setQuery] = useState(value);
  const [suggestions, setSuggestions] = useState<GeocodeLocation[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const searchRequestRef = useRef(0);

  useEffect(() => setQuery(value), [value]);

  const search = useCallback(async (text: string) => {
    setQuery(text);
    if (text.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    setLoading(true);
    const requestId = ++searchRequestRef.current;
    try {
      const results = await searchGeocode(text.trim(), 8);
      if (requestId === searchRequestRef.current) setSuggestions(results);
    } catch {
      if (requestId === searchRequestRef.current) setSuggestions([]);
    } finally {
      if (requestId === searchRequestRef.current) setLoading(false);
    }
  }, []);

  const toneRing =
    tone === "emerald" ? "text-on-primary-fixed" : tone === "blue" ? "text-gs-blue" : "text-gs-red";

  return (
    <div className="w-full min-w-0 rounded-lg border border-outline-variant/60 bg-white p-2 flex items-center gap-2">
      <span className={`shrink-0 ${toneRing}`} aria-hidden="true">
        {icon}
      </span>
      <div className="relative flex-1 min-w-0">
        <label className="sr-only">{label}</label>
        <input
          type="text"
          disabled={disabled}
          value={query}
          aria-label={label}
          placeholder={label}
          onFocus={() => setEditing(true)}
          onBlur={() => setTimeout(() => setEditing(false), 200)}
          onChange={(e) => {
            setEditing(true);
            void search(e.target.value);
          }}
          className="w-full h-8 pl-1 pr-6 text-xs rounded border border-transparent bg-transparent focus:border-primary focus:bg-white focus:outline-none truncate"
        />
        {loading && <Loader2 className="w-3.5 h-3.5 text-primary animate-spin absolute right-1 top-2" />}
        {editing && suggestions.length > 0 && (
          <div className="absolute z-30 left-0 right-0 top-9 max-h-52 overflow-y-auto bg-white border border-gs-line-2 rounded-md shadow-lg p-1 divide-y divide-gs-line">
            {suggestions.map((s, idx) => (
              <button
                key={`${s.formatted}-${idx}`}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onSelect(s);
                  setQuery(s.formatted);
                  setSuggestions([]);
                  setEditing(false);
                }}
                className="w-full text-left p-1.5 rounded hover:bg-surface-container-low text-xs"
              >
                <span className="font-semibold text-[11px] block truncate">
                  {s.address_line1 || s.formatted.split(",")[0]}
                </span>
                <span className="text-[10px] text-gs-mute-2 block truncate">{s.formatted}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Bottom processing dock: single-trip pipeline + overview. */
function ResultDock({
  open,
  onToggle,
  tab,
  onTab,
  logs,
  overview,
  status,
  runTrace,
}: {
  open: boolean;
  onToggle: () => void;
  tab: DockTab;
  onTab: (t: DockTab) => void;
  logs: LogEntry[];
  overview: TestRunOverview | null;
  status: RunStatus;
  runTrace?: TestRunTraceStage[];
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div role="region" aria-label="Kết quả xử lý" className="shrink-0 border-t border-outline-variant/60 bg-surface-container-lowest flex flex-col min-h-0 overflow-hidden" style={{ height: open ? "40%" : "38px" }}>
      <div className="h-[38px] shrink-0 flex items-center justify-between px-3 border-b border-outline-variant/40">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onTab("log")}
            aria-label="Log"
            className={`px-2 py-0.5 text-[11px] font-bold rounded ${
              tab === "log" ? "bg-primary/10 text-primary" : "text-secondary hover:bg-surface-container"
            }`}
          >
            Log
          </button>
          <button
            type="button"
            onClick={() => onTab("overview")}
            className={`px-2 py-0.5 text-[11px] font-bold rounded ${
              tab === "overview" ? "bg-primary/10 text-primary" : "text-secondary hover:bg-surface-container"
            }`}
          >
            Overview
          </button>
          <span className="ml-2 text-[10px] font-mono text-gs-mute-2">
            {runTrace && runTrace.length > 0
              ? `${runTrace.filter((s) => s.state === "done").length}/${runTrace.length} giai đoạn`
              : `${logs.length} sự kiện`}
          </span>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold rounded border border-outline-variant/60 hover:bg-surface-container"
        >
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          {open ? "Thu gọn" : "Mở bảng xử lý"}
        </button>
      </div>
      {open && (
        <div className="flex-1 min-h-0 overflow-y-auto p-2 text-xs">
          {tab === "log" ? (
            <div className="space-y-3">
              <TripPipeline stages={runTrace} status={status} />
              {logs.length > 0 && (
                <div className="border-t border-outline-variant/40 pt-2">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-secondary mb-1">
                    Nhật ký sự kiện
                  </div>
                  <ul className="space-y-1">
                    {logs.map((entry) => (
                      <li key={entry.id} className="border border-outline-variant/40 rounded">
                        <button
                          type="button"
                          onClick={() => setExpanded((prev) => (prev === entry.id ? null : entry.id))}
                          className="w-full flex items-center gap-2 px-2 py-1 text-left hover:bg-surface-container/60"
                        >
                          <span className="font-mono text-[10px] text-gs-mute-2 w-16 shrink-0">{entry.time}</span>
                          <span className="font-semibold text-[11px] w-40 shrink-0 truncate">{entry.event}</span>
                          <span className="text-[11px] text-secondary truncate flex-1">{entry.state}</span>
                          {entry.details && (
                            expanded === entry.id ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
                          )}
                        </button>
                        {expanded === entry.id && entry.details && (
                          <pre className="px-2 pb-1 text-[10px] whitespace-pre-wrap text-gs-mute-2">{entry.details}</pre>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : overview ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {overview.stages.map((stage) => (
                  <div key={stage.key} className="border border-outline-variant/50 rounded px-3 py-1.5">
                    <div className="text-[10px] uppercase tracking-wide text-secondary">{stage.label}</div>
                    <div className="text-sm font-bold text-on-surface">{stage.count}</div>
                    <div className="text-[10px] text-gs-mute-2">{stage.state}</div>
                  </div>
                ))}
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wide text-secondary mb-1">
                  Phân loại theo nhãn
                </div>
                {Object.keys(overview.classification_counts).length === 0 ? (
                  <p className="text-gs-mute-2 italic">Chưa có kết quả phân loại.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(overview.classification_counts).map(([label, count]) => (
                      <span key={label} className="px-2 py-0.5 rounded bg-surface-container text-[11px] font-semibold">
                        {label}: {count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="text-gs-mute-2 italic">
              {status === "IDLE" ? "Chưa có chuyến đi." : "Đang tải dữ liệu xử lý…"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function SimulationCockpitPage() {
  const e2eAuthBypass =
    (process.env.NODE_ENV !== "production" || isolatedGisBuild()) &&
    process.env.NEXT_PUBLIC_E2E_TEST === "true";
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const clerkAuth = e2eAuthBypass ? { getToken: async () => null, isLoaded: true, orgId: "e2e" } : useAuth();
  const getToken = e2eAuthBypass ? async () => null : clerkAuth.getToken;
  const isLoaded = e2eAuthBypass || clerkAuth.isLoaded;
  const organizationId = clerkAuth.orgId ?? null;
  const organizationRef = useRef(organizationId);
  useEffect(() => {
    organizationRef.current = organizationId;
  }, [organizationId]);

  const getTokenRef = useRef(getToken);
  useEffect(() => {
    getTokenRef.current = getToken;
  });
  useEffect(() => {
    if (!isLoaded) return;
    setTestApiTokenProvider(() => getTokenRef.current());
    return () => setTestApiTokenProvider(null);
  }, [isLoaded]);

  const [tab, setTab] = useState<ConsoleTab>("manual");
  const [form, setForm] = useState<ScenarioForm>(DEFAULT_FORM);

  // --- Run state ---
  const [runId, setRunId] = useState<string | null>(null);
  const [plannedDefinitionId, setPlannedDefinitionId] = useState<string | null>(null);
  const [streamState, setStreamState] = useState("idle");
  const [status, setStatus] = useState<RunStatus>("IDLE");
  const stopsEditableRef = useRef(true);
  useEffect(() => {
    stopsEditableRef.current = status === "IDLE";
  }, [status]);
  const [speedFactor, setSpeedFactor] = useState<number>(1);
  const [expectedLabel, setExpectedLabel] = useState<ExpectedLabel | "">("");
  const [selectedDriver, setSelectedDriver] = useState<ClerkLinkedDriver | null>(null);
  const [waypoints, setWaypoints] = useState<WaypointItem[]>([]);
  const [clickToAddWaypointMode, setClickToAddWaypointMode] = useState<boolean>(false);
  const [setPickupMode, setSetPickupMode] = useState<boolean>(false);
  const [isDraggingOrigin, setIsDraggingOrigin] = useState<boolean>(false);
  const [runTrace, setRunTrace] = useState<TestRunTraceStage[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- Title ---
  const [title, setTitle] = useState<string>("");
  const [titleDraft, setTitleDraft] = useState<string>("");
  const [editingTitle, setEditingTitle] = useState(false);

  // --- Kinematics ---
  const [speedMpsLive, setSpeedMpsLive] = useState(12);
  const [heading, setHeading] = useState(45);
  const [arrived, setArrived] = useState(false);

  // --- Conversation ---
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_CONVERSATION);
  const [driverChatInput, setDriverChatInput] = useState("");
  const [customerChatInput, setCustomerChatInput] = useState("");
  const driverScrollRef = useRef<HTMLDivElement>(null);
  const customerScrollRef = useRef<HTMLDivElement>(null);

  // --- Map ---
  const [breadcrumbs, setBreadcrumbs] = useState<[number, number][]>([]);
  const [vehicleLat, setVehicleLat] = useState(21.0285);
  const [vehicleLon, setVehicleLon] = useState(105.8524);
  const [samples, setSamples] = useState<TestSample[]>([]);
  const [followDriver, setFollowDriver] = useState(true);
  const [resolvedRoute, setResolvedRoute] = useState<RouteResolveResponse | null>(null);
  const [routeResolving, setRouteResolving] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);

  // --- Results dock ---
  const [dockOpen, setDockOpen] = useState(false);
  const [dockTab, setDockTab] = useState<DockTab>("log");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [overview, setOverview] = useState<TestRunOverview | null>(null);

  // --- Submission / cancellation ---
  const [submittingTrips, setSubmittingTrips] = useState(false);
  const [publishResult, setPublishResult] = useState<ProductionPublishResult | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelDialog, setCancelDialog] = useState<{ actor: CancellationActor } | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const cancelReasonRef = useRef<HTMLTextAreaElement>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);

  // --- Presets & history ---
  const [presets, setPresets] = useState<TestPreset[]>([]);
  const [presetSource, setPresetSource] = useState<Record<string, unknown> | null>(null);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [history, setHistory] = useState<TestRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [actors, setActors] = useState<TestActorDirectory | null>(null);
  const [actorsLoading, setActorsLoading] = useState(false);
  const historyCacheRef = useRef(new Map<string, TestRunSummary[]>());

  const sseRef = useRef<AbortController | null>(null);
  const publishTracePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const routeRequestRef = useRef(0);
  const stopGeocodeRequestRef = useRef<Record<string, number>>({});
  const vehicleLatRef = useRef(vehicleLat);
  const vehicleLonRef = useRef(vehicleLon);

  useEffect(() => {
    return () => {
      if (publishTracePollRef.current) {
        clearInterval(publishTracePollRef.current);
      }
    };
  }, []);

  useEffect(() => {
    vehicleLatRef.current = vehicleLat;
    vehicleLonRef.current = vehicleLon;
  }, [vehicleLat, vehicleLon]);

  useEffect(() => {
    if (driverScrollRef.current) driverScrollRef.current.scrollTop = driverScrollRef.current.scrollHeight;
    if (customerScrollRef.current) customerScrollRef.current.scrollTop = customerScrollRef.current.scrollHeight;
  }, [messages]);

  const addLog = useCallback((event: string, state: string, details?: string) => {
    setLogs((prev) => [
      ...prev,
      {
        id: `log-${Date.now()}-${prev.length}`,
        time: new Date().toLocaleTimeString(),
        event,
        state,
        details,
      },
    ]);
  }, []);

  const refreshOverview = useCallback(async (id: string) => {
    try {
      const scope = organizationRef.current;
      const data = await fetchTestRunOverview(id);
      if (scope === organizationRef.current) setOverview(data);
    } catch {
      /* overview stays at its last recorded value */
    }
  }, []);

  const fetchTrace = useCallback(async (id: string) => {
    try {
      const scope = organizationRef.current;
      const data = await fetchRunTrace(id);
      if (scope === organizationRef.current) setRunTrace(data);
    } catch {
      /* trace stays at its last recorded value */
    }
  }, []);

  // --- Speed Control ---
  const handleSetSpeedFactor = useCallback(
    async (factor: number) => {
      const f = Math.max(1, Math.min(20, factor));
      setSpeedFactor(f);
      if (runId && (status === "RUNNING" || status === "PAUSED")) {
        try {
          await controlTestRun(runId, "SET_SPEED_FACTOR", { speed_factor: f });
        } catch (e) {
          console.warn("Failed to set speed factor", e);
        }
      }
    },
    [runId, status]
  );

  // --- Driver Selection (Clerk) ---
  const handleSelectDriver = useCallback((drv: ClerkLinkedDriver | null) => {
    setSelectedDriver(drv);
    setForm((prev) => ({
      ...prev,
      driverId: drv ? drv.driver_id : "",
    }));
  }, []);

  // --- Waypoints Handlers ---
  const handleUpdateWaypointLeg = useCallback((id: string, leg: "pickup" | "destination") => {
    setWaypoints((prev) =>
      prev.map((wp) => (wp.id === id ? { ...wp, leg } : wp))
    );
    setResolvedRoute(null);
  }, []);

  const handleRemoveWaypoint = useCallback((id: string) => {
    setWaypoints((prev) => prev.filter((wp) => wp.id !== id));
    setResolvedRoute(null);
  }, []);

  const handleMoveWaypoint = useCallback((id: string, direction: "up" | "down") => {
    setWaypoints((prev) => {
      const idx = prev.findIndex((wp) => wp.id === id);
      if (idx === -1) return prev;
      if (direction === "up" && idx === 0) return prev;
      if (direction === "down" && idx === prev.length - 1) return prev;
      const targetIdx = direction === "up" ? idx - 1 : idx + 1;
      const next = [...prev];
      const temp = next[idx];
      next[idx] = next[targetIdx];
      next[targetIdx] = temp;
      return next;
    });
    setResolvedRoute(null);
  }, []);

  // --- Stop editing: address selection with 4 km proximity clamp ---
  const applyStop = useCallback((key: "origin" | "pickup" | "dest", loc: GeocodeLocation) => {
    if (!stopsEditableRef.current) return;
    routeRequestRef.current += 1;
    stopGeocodeRequestRef.current[key] = (stopGeocodeRequestRef.current[key] ?? 0) + 1;

    setForm((prev) => {
      let nextOriginLat = prev.originLat;
      let nextOriginLon = prev.originLon;

      if (key === "pickup") {
        const curOrigin = { latitude: parseFloat(prev.originLat), longitude: parseFloat(prev.originLon) };
        if (Number.isFinite(curOrigin.latitude) && Number.isFinite(curOrigin.longitude)) {
          const clamped = clampToRadius({ latitude: loc.lat, longitude: loc.lon }, curOrigin, 4000);
          if (clamped.clamped) {
            nextOriginLat = String(clamped.latitude);
            nextOriginLon = String(clamped.longitude);
            setVehicleLat(clamped.latitude);
            setVehicleLon(clamped.longitude);
            addLog("Quy tắc 4 km", "Điểm đón thay đổi khiến khoảng cách xuất phát vượt quá 4 km, đã tự động căn chỉnh lại điểm xuất phát");
          }
        }
      }

      return {
        ...prev,
        originLat: nextOriginLat,
        originLon: nextOriginLon,
        [`${key}Address`]: loc.formatted,
        [`${key}Lat`]: String(loc.lat),
        [`${key}Lon`]: String(loc.lon),
      };
    });

    if (key === "origin") {
      setVehicleLat(loc.lat);
      setVehicleLon(loc.lon);
    }
    setResolvedRoute(null);
    setPlannedDefinitionId(null);
  }, [addLog]);

  const handleStopDrag = useCallback(
    (kind: "initial" | "pickup" | "destination", coords: { latitude: number; longitude: number }) => {
      if (!stopsEditableRef.current) return;
      const key = kind === "initial" ? "origin" : kind === "pickup" ? "pickup" : "dest";
      routeRequestRef.current += 1;

      let finalCoords = coords;
      if (kind === "initial") {
        const pickupLoc = {
          latitude: parseFloat(form.pickupLat),
          longitude: parseFloat(form.pickupLon),
        };
        if (Number.isFinite(pickupLoc.latitude) && Number.isFinite(pickupLoc.longitude)) {
          const clamped = clampToRadius(pickupLoc, coords, 4000);
          if (clamped.clamped) {
            addLog("Quy tắc 4 km", "Vị trí xuất phát cách điểm đón vượt quá 4 km, đã tự động căn chỉnh về mép bán kính 4 km");
          }
          finalCoords = { latitude: clamped.latitude, longitude: clamped.longitude };
        }
      } else if (kind === "pickup") {
        const originLoc = {
          latitude: parseFloat(form.originLat),
          longitude: parseFloat(form.originLon),
        };
        if (Number.isFinite(originLoc.latitude) && Number.isFinite(originLoc.longitude)) {
          const clamped = clampToRadius(coords, originLoc, 4000);
          if (clamped.clamped) {
            addLog("Quy tắc 4 km", "Điểm đón di chuyển cách điểm xuất phát hơn 4 km, đã tự động căn chỉnh lại điểm xuất phát");
            setForm((prev) => ({
              ...prev,
              originLat: String(clamped.latitude),
              originLon: String(clamped.longitude),
            }));
            setVehicleLat(clamped.latitude);
            setVehicleLon(clamped.longitude);
          }
        }
      }

      setForm((prev) => ({
        ...prev,
        [`${key}Address`]: CUSTOM_LOCATION_LABEL,
        [`${key}Lat`]: String(finalCoords.latitude),
        [`${key}Lon`]: String(finalCoords.longitude),
      }));
      if (key === "origin") {
        setVehicleLat(finalCoords.latitude);
        setVehicleLon(finalCoords.longitude);
      }
      setResolvedRoute(null);
      addLog("Vị trí điểm dừng", "Đã di chuyển trên bản đồ, cần chọn lại địa chỉ để xác nhận");
      const requestId = (stopGeocodeRequestRef.current[key] ?? 0) + 1;
      stopGeocodeRequestRef.current[key] = requestId;
      void searchGeocode(`${finalCoords.latitude},${finalCoords.longitude}`, 1)
        .then((results) => {
          if (requestId !== stopGeocodeRequestRef.current[key] || results.length === 0) return;
          applyStop(key, results[0]);
        })
        .catch(() => {
          // The coordinate remains visible as a custom location when reverse lookup is unavailable.
        });
    },
    [form.pickupLat, form.pickupLon, form.originLat, form.originLon, addLog, applyStop]
  );

  // --- Interactive Map Click Handler ---
  const handleMapClick = useCallback(
    (coords: { latitude: number; longitude: number }) => {
      if (status !== "IDLE") return;

      if (setPickupMode) {
        const originLoc = {
          latitude: parseFloat(form.originLat),
          longitude: parseFloat(form.originLon),
        };
        let nextOriginLat = form.originLat;
        let nextOriginLon = form.originLon;

        if (Number.isFinite(originLoc.latitude) && Number.isFinite(originLoc.longitude)) {
          const clamped = clampToRadius(coords, originLoc, 4000);
          if (clamped.clamped) {
            nextOriginLat = String(clamped.latitude);
            nextOriginLon = String(clamped.longitude);
            setVehicleLat(clamped.latitude);
            setVehicleLon(clamped.longitude);
            addLog("Quy tắc 4 km", "Điểm đón mới cách điểm xuất phát hơn 4 km, đã tự động căn chỉnh lại điểm xuất phát");
          }
        }

        setForm((prev) => ({
          ...prev,
          pickupAddress: CUSTOM_LOCATION_LABEL,
          pickupLat: String(coords.latitude),
          pickupLon: String(coords.longitude),
          originLat: nextOriginLat,
          originLon: nextOriginLon,
        }));
        setResolvedRoute(null);
        setSetPickupMode(false);
        addLog("Điểm đón", "Đã đặt vị trí đón khách mới trên bản đồ");

        const requestId = (stopGeocodeRequestRef.current["pickup"] ?? 0) + 1;
        stopGeocodeRequestRef.current["pickup"] = requestId;
        void searchGeocode(`${coords.latitude},${coords.longitude}`, 1)
          .then((results) => {
            if (requestId !== stopGeocodeRequestRef.current["pickup"] || results.length === 0) return;
            applyStop("pickup", results[0]);
          })
          .catch(() => {});
        return;
      }

      if (clickToAddWaypointMode) {
        const originCoord = { latitude: parseFloat(form.originLat), longitude: parseFloat(form.originLon) };
        const pickupCoord = { latitude: parseFloat(form.pickupLat), longitude: parseFloat(form.pickupLon) };
        const destCoord = { latitude: parseFloat(form.destLat), longitude: parseFloat(form.destLon) };

        const defaultLeg = nearestLeg(originCoord, pickupCoord, destCoord, coords);

        setWaypoints((prev) => [
          ...prev,
          {
            id: `wp-${Date.now()}-${prev.length + 1}`,
            name: `Điểm rẽ #${prev.length + 1}`,
            lat: coords.latitude,
            lon: coords.longitude,
            leg: defaultLeg,
          },
        ]);
        setResolvedRoute(null);
        addLog("Thêm điểm rẽ", `Đã thêm điểm rẽ #${waypoints.length + 1} (${defaultLeg === "pickup" ? "Chặng đón" : "Chặng trả"})`);
      }
    },
    [status, setPickupMode, clickToAddWaypointMode, form.originLat, form.originLon, form.pickupLat, form.pickupLon, form.destLat, form.destLon, waypoints.length, addLog, applyStop]
  );

  // --- Chat handlers ---
  const handleDriverSend = (textToSend?: string) => {
    const text = (textToSend || driverChatInput).trim();
    if (!text) return;
    setMessages((prev) => [...prev, { id: `driver-msg-${Date.now()}`, sender: "DRIVER", text, time: new Date().toLocaleTimeString() }]);
    if (!textToSend) setDriverChatInput("");
  };
  const handleCustomerSend = (textToSend?: string) => {
    const text = (textToSend || customerChatInput).trim();
    if (!text) return;
    setMessages((prev) => [...prev, { id: `customer-msg-${Date.now()}`, sender: "CUSTOMER", text, time: new Date().toLocaleTimeString() }]);
    if (!textToSend) setCustomerChatInput("");
  };

  // --- SSE ---
  const connectSSE = useCallback(
    (id: string) => {
      sseRef.current?.abort();
      const controller = new AbortController();
      sseRef.current = controller;
      const seenEventIds = new Set<string>();

      const processEvent = (rawJson: string) => {
        try {
          const evt = JSON.parse(rawJson) as {
            event_type: string;
            event_id?: string;
            step_index: number;
            sample?: { latitude: number; longitude: number; speed_mps: number; heading_deg: number };
            cancellation_actor?: string | null;
            cancellation_reason?: string | null;
            organization_id?: string;
            trip_id?: string;
            simulation_clock?: string;
            state_before?: string;
          };
          if (evt.event_id) {
            if (seenEventIds.has(evt.event_id)) return;
            seenEventIds.add(evt.event_id);
          }
          if (typeof evt.step_index === "number") {
            setCurrentStep(evt.step_index);
          }
          if (evt.sample) {
            const s = evt.sample;
            vehicleLatRef.current = s.latitude;
            vehicleLonRef.current = s.longitude;
            setVehicleLat(s.latitude);
            setVehicleLon(s.longitude);
            setHeading(s.heading_deg);
            setSpeedMpsLive(s.speed_mps);
            setBreadcrumbs((prev) => [...prev, [s.longitude, s.latitude]]);
            setSamples((prev) => [
              ...prev,
              {
                run_id: id,
                step_index: evt.step_index,
                latitude: s.latitude,
                longitude: s.longitude,
                speed_mps: s.speed_mps,
                heading_deg: s.heading_deg,
                is_fault_injected: false,
                fault_type: null,
                emitted_at: new Date().toISOString(),
              },
            ]);
          }
          if (evt.event_type === "run.completed") {
            setStatus("COMPLETED");
            setArrived(true);
            addLog("Chuyến đi hoàn tất", "Đã tới điểm đến");
            void refreshOverview(id);
            void fetchTrace(id);
            controller.abort();
          } else if (evt.event_type === "run.paused") {
            setStatus("PAUSED");
            addLog("Tạm dừng", "Chuyến đi đang tạm dừng");
            void fetchTrace(id);
          } else if (evt.event_type === "run.resumed" || evt.event_type === "step.progress") {
            setStatus("RUNNING");
            void fetchTrace(id);
          } else if (evt.event_type === "run.fast_completed") {
            addLog("Chuyến đi đã xử lý nhanh", "Đang chờ xác nhận điểm đến");
            void fetchTrace(id);
          } else if (evt.event_type === "fault.applied" || evt.event_type === "fault.injected") {
            addLog("Bất thường dữ liệu", "Phát hiện sai lệch trên hành trình");
            void fetchTrace(id);
          } else if (evt.event_type === "run.cancelled") {
            setStatus("CANCELLED");
            addLog(
              "Khách/Tài xế huỷ chuyến",
              `${evt.cancellation_actor === "driver" ? "Tài xế" : "Khách hàng"} huỷ`,
              JSON.stringify({
                event_id: evt.event_id,
                organization_id: evt.organization_id,
                run_id: id,
                trip_id: evt.trip_id,
                occurred_at: evt.simulation_clock,
                actor: evt.cancellation_actor,
                reason: evt.cancellation_reason,
                state_before: evt.state_before,
                resulting_state: "CANCELLED",
                processing: "Not submitted",
              }, null, 2)
            );
            void refreshOverview(id);
            void fetchTrace(id);
            controller.abort();
          } else if (evt.event_type === "run.failed") {
            setStatus("FAILED");
            addLog("Chuyến đi lỗi", "Mô phỏng gặp lỗi");
            void fetchTrace(id);
            controller.abort();
          }
        } catch {
          /* ignore malformed frames */
        }
      };

      void observeTestRun(id, controller.signal, {
        onEvent: (event) => processEvent(JSON.stringify(event)),
        onConnection: setStreamState,
        onReconcile: (run, recordedSamples) => {
          if (controller.signal.aborted) return;
          const nextStatus = run.status as RunStatus;
          setStatus(nextStatus);
          setCurrentStep(run.current_step);
          setTotalSteps(run.total_steps);
          setSamples(recordedSamples);
          setBreadcrumbs(recordedSamples.map((sample) => [sample.longitude, sample.latitude]));
          const latest = recordedSamples.at(-1);
          if (latest) {
            vehicleLatRef.current = latest.latitude;
            vehicleLonRef.current = latest.longitude;
            setVehicleLat(latest.latitude);
            setVehicleLon(latest.longitude);
          }
          setArrived(nextStatus === "COMPLETED");
          void refreshOverview(id);
          void fetchTrace(id);
          if (["COMPLETED", "CANCELLED", "FAILED"].includes(nextStatus)) setStreamState("idle");
        },
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setStreamState("error");
          setError(reason instanceof Error ? reason.message : "Không đọc được dữ liệu mô phỏng");
        }
      });
    },
    [addLog, refreshOverview, fetchTrace]
  );

  useEffect(() => () => sseRef.current?.abort(), []);
  useEffect(() => {
    sseRef.current?.abort();
    setRunId(null);
    setStatus("IDLE");
    setHistory([]);
    setTitle("");
    setTitleDraft("");
    setCurrentStep(0);
    setTotalSteps(0);
    setCancelDialog(null);
    setCancelReason("");
    setSubmitting(false);
    historyCacheRef.current.clear();
    setSamples([]);
    setBreadcrumbs([]);
    setLogs([]);
    setOverview(null);
    setPublishResult(null);
    setMessages(INITIAL_CONVERSATION);
    setArrived(false);
    setStreamState("idle");
  }, [organizationId]);

  // --- Auto-resolve road route ---
  useEffect(() => {
    if (!isLoaded) return;
    const nums = [
      parseFloat(form.originLat),
      parseFloat(form.originLon),
      parseFloat(form.pickupLat),
      parseFloat(form.pickupLon),
      parseFloat(form.destLat),
      parseFloat(form.destLon),
    ];
    if (nums.some((n) => !Number.isFinite(n))) return;
    const timer = setTimeout(() => {
      const requestId = ++routeRequestRef.current;
      setRouteResolving(true);
      resolveTestRoute(
        [nums[1], nums[0]],
        [nums[3], nums[2]],
        [nums[5], nums[4]],
        waypoints.map((w) => ({ lat: w.lat, lon: w.lon, leg: w.leg }))
      )
        .then((res) => {
          if (requestId !== routeRequestRef.current) return;
          setResolvedRoute(res);
          setRouteError(null);
        })
        .catch((err) => {
          if (requestId !== routeRequestRef.current) return;
          setRouteError(err instanceof Error ? err.message : "Chưa có lộ trình đường bộ");
        })
        .finally(() => {
          if (requestId === routeRequestRef.current) setRouteResolving(false);
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [isLoaded, form.originLat, form.originLon, form.pickupLat, form.pickupLon, form.destLat, form.destLon, waypoints]);

  const routeGeometry = useMemo(() => {
    if (!resolvedRoute?.pickup_route?.coordinates || !resolvedRoute?.destination_route?.coordinates) return null;
    return {
      pickup_route: { coordinates: resolvedRoute.pickup_route.coordinates },
      destination_route: { coordinates: resolvedRoute.destination_route.coordinates },
    };
  }, [resolvedRoute]);

  // --- Create run ---
  const handleCreateRun = async () => {
    const scope = organizationId;
    setError(null);
    setSubmitting(true);
    if (!plannedDefinitionId && (!actors || !form.driverId || !form.passengerId || !form.vehicleId || !form.policyVersionId)) {
      setError(!form.driverId ? "Cần chọn tài xế liên kết Clerk." : "Cần chọn đủ tài xế, khách hàng, phương tiện và chính sách.");
      setSubmitting(false);
      return;
    }
    setBreadcrumbs([]);
    setSamples([]);
    setLogs([]);
    setCurrentStep(0);
    setOverview(null);
    setPublishResult(null);
    if (publishTracePollRef.current) {
      clearInterval(publishTracePollRef.current);
      publishTracePollRef.current = null;
    }
    setArrived(false);
    setFollowDriver(true);
    setDockOpen(true);
    setDockTab("log");
    addLog("Bắt đầu mô phỏng", "Khởi tạo chuyến đi");

    const startLat = parseFloat(form.originLat) || 21.0285;
    const startLon = parseFloat(form.originLon) || 105.8524;
    vehicleLatRef.current = startLat;
    vehicleLonRef.current = startLon;
    setVehicleLat(startLat);
    setVehicleLon(startLon);
    setStatus("QUEUED");

    try {
      let defId = plannedDefinitionId;
      if (!defId) {
        const plan = await postTest<{ id: string }>("/plans", {
          name: titleDraft || `Chuyến mô phỏng ${new Date().toISOString()}`,
        });

        if (scope !== organizationRef.current) return;
        let roadGeometry = resolvedRoute?.route_geometry;
        if (!roadGeometry) {
          const res = await resolveTestRoute(
            [parseFloat(form.originLon) || 105.8524, parseFloat(form.originLat) || 21.0285],
            [parseFloat(form.pickupLon) || 105.8497, parseFloat(form.pickupLat) || 21.0118],
            [parseFloat(form.destLon) || 105.8342, parseFloat(form.destLat) || 21.0345],
            waypoints.map((w) => ({ lat: w.lat, lon: w.lon, leg: w.leg }))
          );
          if (res?.route_geometry) {
            roadGeometry = res.route_geometry;
            setResolvedRoute(res);
          }
        }
        if (!roadGeometry) {
          throw new Error("Chưa xác định được lộ trình đường bộ. Hệ thống không tạo đường thẳng thay thế.");
        }

        const defMessages = messages.map((m, idx) => ({
          sender_role: m.sender === "DRIVER" ? "DRIVER" : "PASSENGER",
          content: m.text,
          offset_seconds: idx * 5,
        }));

        const def = await postTest<{ id: string }>("/definitions", {
          plan_id: plan.id,
          route_geometry: roadGeometry,
          driver_config: {
            speed_mps: parseFloat(form.speedMps) || 12,
            update_cadence_s: 1,
            driver_id: form.driverId,
          },
          passenger_config: { passenger_id: form.passengerId || "pass-sim-001", name: "Khách mô phỏng" },
          initial_snapshot: { location: { latitude: startLat, longitude: startLon }, address: form.originAddress },
          pickup_snapshot: { location: { latitude: parseFloat(form.pickupLat), longitude: parseFloat(form.pickupLon) }, address: form.pickupAddress },
          destination_snapshot: { location: { latitude: parseFloat(form.destLat), longitude: parseFloat(form.destLon) }, address: form.destAddress },
          fault_configs: [],
          messages: defMessages,
        });
        defId = def.id;
      }

      const run = await postTest<{ id: string; total_steps: number; title?: string | null }>("/runs", {
        definition_revision_id: defId,
        speed_factor: speedFactor,
        title: titleDraft || null,
        expected_label: expectedLabel || null,
        source: "manual",
      });

      if (scope !== organizationRef.current) return;
      setRunId(run.id);
      setTitle(run.title || titleDraft || "");
      setTitleDraft(run.title || titleDraft || "");
      setTotalSteps(run.total_steps);
      setStatus("RUNNING");
      addLog("Chuyến đi đang chạy", `Tổng ${run.total_steps} bước`);
      void fetchTrace(run.id);
      connectSSE(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không thể bắt đầu mô phỏng");
      setStatus("IDLE");
      addLog("Khởi tạo thất bại", e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setSubmitting(false);
    }
  };

  const handleControl = async (command: "PAUSE" | "RESUME") => {
    if (!runId) return;
    try {
      await postTest(`/runs/${runId}/controls`, { command, payload: {} });
      setStatus(command === "PAUSE" ? "PAUSED" : "RUNNING");
      addLog(command === "PAUSE" ? "Tạm dừng" : "Tiếp tục", "Đã gửi yêu cầu");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không điều khiển được chuyến đi");
    }
  };

  // --- Title persistence ---
  const commitTitle = async () => {
    setEditingTitle(false);
    const next = titleDraft.trim();
    if (!runId || !next || next === title) return;
    try {
      const updated = await updateTestRunTitle(runId, next);
      setTitle(updated.title || next);
      setTitleDraft(updated.title || next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được tên chuyến");
      setTitleDraft(title);
    }
  };

  // --- Complete trips: submit recorded simulation through the pipeline ---
  const handleCompleteTrips = async () => {
    if (!runId) return;
    setSubmittingTrips(true);
    setError(null);
    try {
      const res = await publishSimulationToProduction(runId, {
        pickup: { coordinates: [parseFloat(form.pickupLon), parseFloat(form.pickupLat)] },
        dropoff: { coordinates: [parseFloat(form.destLon), parseFloat(form.destLat)] },
        pickup_address: form.pickupAddress,
        dropoff_address: form.destAddress,
        driver_id: form.driverId,
        passenger_id: form.passengerId,
        vehicle_id: form.vehicleId,
        policy_version_id: form.policyVersionId,
      });
      setPublishResult(res);
      addLog("Gửi chuyến đi", "Đã gửi để xử lý qua mô hình", res.case_id ? `Hồ sơ: ${res.case_id}` : undefined);
      void refreshOverview(runId);
      void fetchTrace(runId);
      // Poll trace until stages 6-9 reach terminal state or max attempts reached
      if (publishTracePollRef.current) {
        clearInterval(publishTracePollRef.current);
      }
      const currentRunId = runId;
      let attempts = 0;
      publishTracePollRef.current = setInterval(async () => {
        attempts += 1;
        try {
          const traceData = await fetchRunTrace(currentRunId);
          if (organizationRef.current === organizationId) {
            setRunTrace(traceData);
          }
          const stages6to9 = traceData.slice(5);
          const allSettled =
            stages6to9.length > 0 &&
            stages6to9.every((s) => s.state === "done" || s.state === "skipped");
          if (allSettled || attempts >= 10) {
            if (publishTracePollRef.current) {
              clearInterval(publishTracePollRef.current);
              publishTracePollRef.current = null;
            }
          }
        } catch {
          if (attempts >= 10 && publishTracePollRef.current) {
            clearInterval(publishTracePollRef.current);
            publishTracePollRef.current = null;
          }
        }
      }, 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gửi chuyến đi thất bại");
    } finally {
      setSubmittingTrips(false);
    }
  };

  // --- Participant cancellation ---
  const confirmCancel = async () => {
    if (!runId || !cancelDialog) return;
    const reason = cancelReason.trim();
    if (!reason) {
      setCancelError("Vui lòng nhập lý do huỷ chuyến.");
      cancelReasonRef.current?.focus();
      return;
    }
    setCancelling(true);
    setCancelError(null);
    try {
      const previousState = status;
      await cancelTestRun(runId, cancelDialog.actor, reason);
      addLog(
        "Huỷ chuyến",
        "Đã xác nhận yêu cầu huỷ; chờ sự kiện terminal",
        JSON.stringify({ run_id: runId, organization_id: organizationId, actor: cancelDialog.actor, reason, acknowledged_at: new Date().toISOString(), state_before: previousState, resulting_state: "CANCELLED", result: "accepted" })
      );
      setCancelDialog(null);
      setCancelReason("");
      void refreshOverview(runId);
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : "Huỷ chuyến thất bại. Vui lòng thử lại.");
    } finally {
      setCancelling(false);
    }
  };

  const handleReset = () => {
    sseRef.current?.abort();
    setStatus("IDLE");
    setRunId(null);
    setPlannedDefinitionId(null);
    setTitle("");
    setTitleDraft("");
    setBreadcrumbs([]);
    setSamples([]);
    setFollowDriver(true);
    setCurrentStep(0);
    setTotalSteps(0);
    setSpeedMpsLive(12);
    setArrived(false);
    setError(null);
    setPublishResult(null);
    setOverview(null);
    setLogs([]);
    setRunTrace([]);
    setClickToAddWaypointMode(false);
    setSetPickupMode(false);
    setIsDraggingOrigin(false);
    setMessages(INITIAL_CONVERSATION);
    vehicleLatRef.current = parseFloat(form.originLat) || 21.0285;
    vehicleLonRef.current = parseFloat(form.originLon) || 105.8524;
    setVehicleLat(vehicleLatRef.current);
    setVehicleLon(vehicleLonRef.current);
  };

  // --- Presets / history loaders ---
  const loadPresets = useCallback(async () => {
    setPresetsLoading(true);
    try {
      const data = await fetchTestPresets(5);
      setPresets(data.presets);
      setPresetSource(data.source);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được danh sách chuyến mẫu");
    } finally {
      setPresetsLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (!organizationId) return;
    setHistoryLoading(true);
    try {
      const cached = historyCacheRef.current.get(organizationId);
      if (cached) {
        setHistory(cached);
        return;
      }
      const runs = await fetchTestRuns(50);
      if (organizationRef.current !== organizationId) return;
      historyCacheRef.current.set(organizationId, runs);
      setHistory(runs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được lịch sử");
    } finally {
      setHistoryLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    if (tab === "presets" && presets.length === 0) void loadPresets();
    if (tab === "history") void loadHistory();
  }, [tab, presets.length, loadPresets, loadHistory]);

  useEffect(() => {
    let active = true;
    setActors(null);
    setForm((previous) => ({ ...previous, driverId: "", passengerId: "", vehicleId: "", policyVersionId: "" }));
    if (!isLoaded || !organizationId) { setActorsLoading(false); return; }
    setActorsLoading(true);
    void fetchTestActors().then((value) => { if (active) setActors(value); }).catch((e) => {
      if (active) setError(e instanceof Error ? e.message : "Không tải được danh sách tác nhân");
    }).finally(() => { if (active) setActorsLoading(false); });
    return () => { active = false; };
  }, [organizationId, isLoaded]);

  const applyPreset = async (preset: TestPreset, chosenTrip?: TestPresetTrip | null) => {
    setSelectedPreset(preset.id);
    const trip = chosenTrip || preset.sample_trips[0];
    if (!trip) return;
    addLog("Lập kế hoạch chuyến mẫu", `${preset.title} · ${trip.trip_ref}`, trip.label);
    try {
      const planRes = await planTestPreset(preset.id, trip.trip_ref);
      setPlannedDefinitionId(planRes.definition.id);
      setTitleDraft(planRes.plan.name);
      setTitle(planRes.plan.name);

      const initSnap = planRes.initial_snapshot || planRes.definition.initial_snapshot;
      const pickSnap = planRes.pickup_snapshot || planRes.definition.pickup_snapshot;
      const destSnap = planRes.destination_snapshot || planRes.definition.destination_snapshot;

      const initLat = initSnap?.location.latitude ?? 21.0285;
      const initLon = initSnap?.location.longitude ?? 105.8524;
      const pickLat = pickSnap?.location.latitude ?? 21.0118;
      const pickLon = pickSnap?.location.longitude ?? 105.8497;
      const destLat = destSnap?.location.latitude ?? 21.0345;
      const destLon = destSnap?.location.longitude ?? 105.8342;

      setForm((prev) => ({
        ...prev,
        originLat: String(initLat),
        originLon: String(initLon),
        originAddress: initSnap?.address || "Điểm xuất phát",
        pickupLat: String(pickLat),
        pickupLon: String(pickLon),
        pickupAddress: pickSnap?.address || "Điểm đón khách",
        destLat: String(destLat),
        destLon: String(destLon),
        destAddress: destSnap?.address || "Điểm trả khách",
        speedMps: String(planRes.definition.driver_config?.speed_mps || 12),
        driverId: prev.driverId || actors?.drivers[0]?.id || planRes.definition.driver_config?.driver_id || "",
        passengerId: prev.passengerId || actors?.passengers[0]?.id || planRes.definition.passenger_config?.passenger_id || "pass-sim-001",
        vehicleId: prev.vehicleId || actors?.vehicles[0]?.id || "veh-sim-001",
        policyVersionId: prev.policyVersionId || actors?.policies[0]?.id || "pol-sim-001",
      }));

      setVehicleLat(initLat);
      setVehicleLon(initLon);
      vehicleLatRef.current = initLat;
      vehicleLonRef.current = initLon;

      const roadGeom = planRes.definition.route_geometry;
      if (roadGeom && roadGeom.coordinates.length >= 2) {
        const midIdx = Math.floor(roadGeom.coordinates.length / 2);
        setResolvedRoute({
          route_geometry: roadGeom,
          pickup_route: {
            coordinates: roadGeom.coordinates.slice(0, midIdx + 1),
            distance_m: planRes.distance_m ? planRes.distance_m * 0.4 : 1000,
            duration_s: 300,
            provider: "osrm",
          },
          destination_route: {
            coordinates: roadGeom.coordinates.slice(midIdx),
            distance_m: planRes.distance_m ? planRes.distance_m * 0.6 : 2000,
            duration_s: 600,
            provider: "osrm",
          },
          provider: "osrm",
        });
      }

      const defMessages = planRes.definition.messages;
      if (defMessages && defMessages.length > 0) {
        setMessages(
          defMessages.map((m, idx: number) => ({
            id: `msg-preset-${idx}`,
            sender: m.sender_role === "DRIVER" ? "DRIVER" : "CUSTOMER",
            text: m.content,
            time: new Date().toLocaleTimeString("vi-VN", { hour12: false }),
          }))
        );
      }

      setTab("manual");
      setDockOpen(true);
      setDockTab("log");
      addLog("Kế hoạch sẵn sàng", `Định nghĩa #${planRes.definition.id.slice(0, 8)}`, "Sẵn sàng bấm Chạy mô phỏng");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể lập kế hoạch chuyến mẫu");
      addLog("Lỗi kế hoạch", err instanceof Error ? err.message : "Thất bại");
    }
  };

  const statusColor: Record<RunStatus, string> = {
    IDLE: "bg-surface-container text-secondary border-outline-variant/60",
    QUEUED: "bg-gs-amber-soft text-gs-amber border-gs-amber/40",
    RUNNING: "bg-primary-fixed text-on-primary-fixed border-primary-fixed-dim",
    PAUSED: "bg-gs-blue-soft text-gs-blue border-gs-blue/30",
    STOP_MOVEMENT: "bg-surface-container text-gs-mute-2 border-gs-line-2",
    COMPLETED: "bg-gs-green-soft text-gs-green border-gs-green/40",
    CANCELLED: "bg-gs-red-soft text-gs-red border-gs-red/40",
    FAILED: "bg-error-container text-error border-error/30",
  };
  const statusLabel: Record<RunStatus, string> = {
    IDLE: "Sẵn sàng",
    QUEUED: "Đang chuẩn bị",
    RUNNING: "Đang chạy",
    PAUSED: "Tạm dừng",
    STOP_MOVEMENT: "Đang dừng",
    CANCELLED: "Đã huỷ",
    COMPLETED: "Hoàn tất",
    FAILED: "Lỗi",
  };

  const canSubmit = arrived || status === "COMPLETED" || status === "CANCELLED";
  const statusLabelFor = (value: string): string => (statusLabel as Record<string, string>)[value] ?? value;

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden bg-background text-on-surface font-sans">
      {/* Header */}
      <div className="h-10 w-full bg-surface-container-lowest border-b border-outline-variant/60 flex items-center justify-between px-3 shrink-0 z-40">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-7 h-7 rounded bg-primary flex items-center justify-center text-white shrink-0">
            <span className="material-symbols-outlined text-[16px]">play_circle</span>
          </span>
          <span className="font-bold text-xs text-primary shrink-0">Bảng mô phỏng chuyến đi</span>
          {runId && (
            <span className={`px-1.5 py-0.5 text-[10px] font-mono font-bold rounded border ${statusColor[status]}`}>
              {statusLabel[status]}
            </span>
          )}
        </div>

        {/* Centered editable title */}
        <div className="flex-1 flex justify-center px-4 min-w-0">
          {runId ? (
            editingTitle ? (
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={commitTitle}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void commitTitle();
                  if (e.key === "Escape") {
                    setTitleDraft(title);
                    setEditingTitle(false);
                  }
                }}
                aria-label="Tên chuyến đi"
                className="w-full max-w-md h-7 px-2 text-xs text-center font-semibold rounded border border-primary bg-white focus:outline-none"
              />
            ) : (
              <button
                type="button"
                onClick={() => {
                  setTitleDraft(title);
                  setEditingTitle(true);
                }}
                className="max-w-md truncate px-2 py-1 text-xs font-semibold text-on-surface hover:bg-surface-container rounded"
                title="Nhấn để đổi tên chuyến"
              >
                {title || "Chuyến chưa đặt tên"}
              </button>
            )
          ) : (
            <span className="text-xs text-secondary italic">Chưa có chuyến đi</span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {streamState === "reconnecting" && <span role="status" className="text-[11px] text-gs-amber">Đang kết nối lại…</span>}
          {streamState === "error" && runId && <button type="button" onClick={() => connectSSE(runId)} className="text-xs underline">Kết nối lại</button>}
          {status === "RUNNING" && (
            <button
              onClick={() => handleControl("PAUSE")}
              className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded border bg-white hover:bg-surface-container-low border-outline-variant/60"
            >
              <Pause className="w-3.5 h-3.5" /> Tạm dừng
            </button>
          )}
          {status === "PAUSED" && (
            <button
              onClick={() => handleControl("RESUME")}
              className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-primary text-white hover:bg-primary-container"
            >
              <Play className="w-3.5 h-3.5" /> Tiếp tục
            </button>
          )}
          {status !== "IDLE" && (
            <button
              onClick={handleReset}
              className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded border bg-white text-secondary hover:bg-surface-container-low border-outline-variant/60"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Làm lại
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="h-9 w-full bg-surface-container-lowest border-b border-outline-variant/60 flex items-center gap-1 px-3 shrink-0 z-30">
        {(
          [
            ["manual", "Chuyến thủ công"],
            ["presets", "Chuyến mẫu"],
            ["history", "Lịch sử"],
          ] as Array<[ConsoleTab, string]>
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-2.5 py-1 text-xs font-semibold rounded ${
              tab === key ? "bg-primary/10 text-primary" : "text-secondary hover:bg-surface-container"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "manual" && (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex min-h-0 flex-1">
            {/* Left: conversations */}
            <div role="complementary" aria-label="Hội thoại chuyến đi" className="w-[270px] min-[1200px]:w-[330px] shrink-0 border-r border-outline-variant/60 bg-surface-container-lowest flex flex-col min-h-0">
              <div className="flex-1 flex flex-col min-h-0 border-b-2 border-gs-line-2 bg-white">
                <div className="p-2.5 border-b border-gs-line-2 bg-primary-fixed flex items-center gap-1.5 shrink-0">
                  <span className="w-5 h-5 rounded-full bg-primary text-white flex items-center justify-center">
                    <Car className="w-3 h-3" />
                  </span>
                  <div>
                    <span className="font-bold text-xs text-on-primary-fixed block leading-none">Màn hình Tài xế</span>
                    <span className="text-[9.5px] font-mono text-on-primary-fixed">{form.driverId}</span>
                  </div>
                </div>
                <div ref={driverScrollRef} className="flex-1 overflow-y-auto p-2.5 space-y-2 bg-surface-container-low/50">
                  {messages.map((m) => {
                    const isMe = m.sender === "DRIVER";
                    return (
                      <div key={m.id} className={`flex flex-col ${isMe ? "items-end" : "items-start"} text-xs`}>
                        <span className="text-[9px] text-gs-mute mb-0.5 px-1 font-mono">
                          {isMe ? m.time : `Khách · ${m.time}`}
                        </span>
                        <div
                          className={`max-w-[85%] px-3 py-1.5 rounded-2xl text-[11px] leading-relaxed ${
                            isMe ? "bg-primary text-white rounded-tr-xs" : "bg-white text-foreground border border-gs-line-2 rounded-tl-xs"
                          }`}
                        >
                          {m.text}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="p-2 border-t border-gs-line-2 bg-white shrink-0 flex items-center gap-1">
                  <input
                    type="text"
                    value={driverChatInput}
                    onChange={(e) => setDriverChatInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleDriverSend()}
                    placeholder="Tài xế gửi tin nhắn…"
                    className="flex-1 h-7 px-2 text-xs rounded border border-gs-line-2 bg-surface-container-low focus:bg-white focus:outline-none focus:border-primary"
                  />
                  <button
                    type="button"
                    onClick={() => handleDriverSend()}
                    aria-label="Gửi tin nhắn tài xế"
                    className="h-7 px-2 rounded bg-primary hover:bg-primary-container text-white"
                  >
                    <Send className="w-3 h-3" />
                  </button>
                </div>
              </div>

              <div className="flex-1 flex flex-col min-h-0 bg-white">
                <div className="p-2.5 border-b border-gs-line-2 bg-gs-blue-soft flex items-center gap-1.5 shrink-0">
                  <span className="w-5 h-5 rounded-full bg-gs-blue text-white flex items-center justify-center">
                    <User className="w-3 h-3" />
                  </span>
                  <div>
                    <span className="font-bold text-xs text-gs-blue block leading-none">Màn hình Khách hàng</span>
                    <span className="text-[9.5px] font-mono text-gs-blue">{form.passengerId}</span>
                  </div>
                </div>
                <div ref={customerScrollRef} className="flex-1 overflow-y-auto p-2.5 space-y-2 bg-surface-container-low/50">
                  {messages.map((m) => {
                    const isMe = m.sender === "CUSTOMER";
                    return (
                      <div key={m.id} className={`flex flex-col ${isMe ? "items-end" : "items-start"} text-xs`}>
                        <span className="text-[9px] text-gs-mute mb-0.5 px-1 font-mono">
                          {isMe ? m.time : `Tài xế · ${m.time}`}
                        </span>
                        <div
                          className={`max-w-[85%] px-3 py-1.5 rounded-2xl text-[11px] leading-relaxed ${
                            isMe ? "bg-gs-blue text-white rounded-tr-xs" : "bg-white text-foreground border border-gs-line-2 rounded-tl-xs"
                          }`}
                        >
                          {m.text}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="p-2 border-t border-gs-line-2 bg-white shrink-0 flex items-center gap-1">
                  <input
                    type="text"
                    value={customerChatInput}
                    onChange={(e) => setCustomerChatInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleCustomerSend()}
                    placeholder="Khách hàng gửi tin nhắn…"
                    className="flex-1 h-7 px-2 text-xs rounded border border-gs-line-2 bg-surface-container-low focus:bg-white focus:outline-none focus:border-gs-blue/30"
                  />
                  <button
                    type="button"
                    onClick={() => handleCustomerSend()}
                    aria-label="Gửi tin nhắn khách hàng"
                    className="h-7 px-2 rounded bg-gs-blue hover:bg-gs-blue/90 text-white"
                  >
                    <Send className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>

            {/* Center: map */}
            <div
              className={`flex-1 min-w-0 relative h-full flex flex-col overflow-hidden bg-surface-container ${
                clickToAddWaypointMode || setPickupMode ? "cursor-crosshair" : ""
              }`}
            >
              <MapLibreView
                className="flex-1 w-full h-full min-h-0"
                driverBreadcrumbs={breadcrumbs}
                driverLocation={{ latitude: vehicleLat, longitude: vehicleLon, bearing: heading, status: "en_route" }}
                vehicleType="car"
                driverInitialLocation={
                  form.originLat ? { latitude: parseFloat(form.originLat), longitude: parseFloat(form.originLon), label: form.originAddress } : undefined
                }
                customerLocation={
                  form.pickupLat ? { latitude: parseFloat(form.pickupLat), longitude: parseFloat(form.pickupLon), label: form.pickupAddress } : undefined
                }
                destinationLocation={
                  form.destLat ? { latitude: parseFloat(form.destLat), longitude: parseFloat(form.destLon), label: form.destAddress } : undefined
                }
                draggableStops={status === "IDLE"}
                onStopDrag={handleStopDrag}
                onStopDragStart={(kind) => {
                  if (kind === "initial") setIsDraggingOrigin(true);
                }}
                onStopDragEnd={(kind) => {
                  if (kind === "initial") setIsDraggingOrigin(false);
                }}
                waypoints={waypoints}
                onMapClick={handleMapClick}
                proximityCircle={
                  isDraggingOrigin && form.pickupLat && form.pickupLon
                    ? {
                        center: { latitude: parseFloat(form.pickupLat), longitude: parseFloat(form.pickupLon) },
                        radiusM: 4000,
                      }
                    : null
                }
                routeGeometry={routeGeometry}
                currentSpeedMps={speedMpsLive}
                followDriver={followDriver}
                onToggleFollowDriver={setFollowDriver}
                showKinematicFooter={false}
              />

              {/* Waypoint Click Mode Banner */}
              {clickToAddWaypointMode && (
                <div
                  data-testid="waypoint-click-banner"
                  className="absolute top-3 left-1/2 -translate-x-1/2 z-30 bg-gs-amber-soft0 text-white font-semibold text-xs px-3 py-1.5 rounded-full shadow-lg flex items-center gap-2 animate-bounce"
                >
                  <span>Nhấp trên bản đồ để thêm điểm rẽ (Điểm #{waypoints.length + 1})</span>
                  <button
                    type="button"
                    onClick={() => setClickToAddWaypointMode(false)}
                    aria-label="Tắt chế độ thêm điểm rẽ"
                    className="w-4 h-4 rounded-full bg-white/20 hover:bg-white/40 flex items-center justify-center text-xs font-bold"
                  >
                    ×
                  </button>
                </div>
              )}

              {/* Set Pickup Click Mode Banner */}
              {setPickupMode && (
                <div
                  data-testid="set-pickup-banner"
                  className="absolute top-3 left-1/2 -translate-x-1/2 z-30 bg-gs-blue text-white font-semibold text-xs px-3 py-1.5 rounded-full shadow-lg flex items-center gap-2 animate-bounce"
                >
                  <span>Nhấp trên bản đồ để đặt vị trí đón khách</span>
                  <button
                    type="button"
                    onClick={() => setSetPickupMode(false)}
                    aria-label="Tắt chế độ chọn điểm đón"
                    className="w-4 h-4 rounded-full bg-white/20 hover:bg-white/40 flex items-center justify-center text-xs font-bold"
                  >
                    ×
                  </button>
                </div>
              )}

              {/* Read-only compass */}
              <div
                className="absolute top-3 right-3 z-20 w-12 h-12 rounded-full bg-white/90 border border-outline-variant/60 shadow-sm flex items-center justify-center"
                role="img"
                aria-label={`La bàn hướng ${heading.toFixed(0)} độ`}
              >
                <Compass
                  className="w-7 h-7 text-primary"
                  style={{ transform: `rotate(${heading}deg)` }}
                  aria-hidden="true"
                />
              </div>

              <div className="absolute top-3 left-3 z-20 bg-white/95 border border-outline-variant/60 shadow-sm rounded-lg p-2.5 max-w-[260px] text-xs">
                <div className="flex items-center justify-between gap-2 border-b border-outline-variant/40 pb-1.5 mb-1.5">
                  <span className="font-bold text-[11px] text-foreground flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${status === "RUNNING" ? "bg-gs-green animate-pulse" : "bg-gs-mute"}`} />
                    Vị trí xe
                  </span>
                  <span className="text-[10px] font-mono px-1 rounded bg-surface-container text-gs-mute-2 font-semibold">
                    {statusLabel[status]}
                  </span>
                </div>
                <div className="space-y-1 font-mono text-[11px] text-gs-mute-2">
                  <div className="flex justify-between">
                    <span>Vận tốc</span>
                    <span className="font-semibold text-foreground">{(speedMpsLive * 3.6).toFixed(1)} km/h</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Tiến độ</span>
                    <span className="text-foreground">{currentStep} / {totalSteps || "—"}</span>
                  </div>
                </div>
              </div>

              {error && (
                <div className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-error-container border border-error/40 px-4 py-2 rounded-lg shadow-md flex items-center gap-2 text-on-error-container text-xs z-30">
                  <AlertTriangle className="w-4 h-4 text-error shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </div>

            {/* Right: controls */}
            <div role="complementary" aria-label="Điểm dừng và điều khiển" className="w-[300px] min-[1200px]:w-[360px] shrink-0 border-l border-outline-variant/60 bg-surface-container-lowest flex flex-col gap-3 p-3 overflow-y-auto text-on-surface">
              <div className="flex items-center justify-between border-b border-outline-variant/40 pb-2">
                <span className="text-xs font-bold flex items-center gap-1.5">
                  <Navigation className="w-3.5 h-3.5 text-primary" /> Điểm dừng &amp; điều khiển
                </span>
              </div>

              <div className="flex flex-col gap-2">
                <StopRow
                  label="Vị trí xuất phát của tài xế"
                  icon={<Car className="w-4 h-4" />}
                  tone="emerald"
                  value={form.originAddress}
                  disabled={status !== "IDLE"}
                  onSelect={(loc) => applyStop("origin", loc)}
                />

                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-secondary font-semibold">Điểm đón khách</span>
                    {status === "IDLE" && (
                      <button
                        type="button"
                        onClick={() => {
                          setSetPickupMode((prev) => !prev);
                          if (clickToAddWaypointMode) setClickToAddWaypointMode(false);
                        }}
                        className={`text-[10px] font-bold px-2 py-0.5 rounded border transition cursor-pointer ${
                          setPickupMode
                            ? "bg-gs-blue text-white border-gs-blue/30"
                            : "bg-white text-gs-blue border-gs-blue/30 hover:bg-gs-blue-soft"
                        }`}
                      >
                        {setPickupMode ? "Đang chọn trên bản đồ…" : "Đặt trên bản đồ"}
                      </button>
                    )}
                  </div>
                  <StopRow
                    label="Điểm đón khách"
                    icon={<User className="w-4 h-4" />}
                    tone="blue"
                    value={form.pickupAddress}
                    disabled={status !== "IDLE"}
                    onSelect={(loc) => applyStop("pickup", loc)}
                  />
                </div>

                <StopRow
                  label="Điểm đến"
                  icon={<MapPin className="w-4 h-4" />}
                  tone="rose"
                  value={form.destAddress}
                  disabled={status !== "IDLE"}
                  onSelect={(loc) => applyStop("dest", loc)}
                />
                <p className="text-[10px] text-secondary">Kéo trực tiếp các điểm trên bản đồ để di chuyển.</p>
              </div>

              {/* Waypoints management */}
              <WaypointPanel
                waypoints={waypoints}
                onToggleClickMode={() => {
                  setClickToAddWaypointMode((prev) => !prev);
                  if (setPickupMode) setSetPickupMode(false);
                }}
                isClickMode={clickToAddWaypointMode}
                onUpdateWaypointLeg={handleUpdateWaypointLeg}
                onRemoveWaypoint={handleRemoveWaypoint}
                onMoveWaypoint={handleMoveWaypoint}
                disabled={status !== "IDLE"}
              />

              {/* Clerk-linked Driver Search */}
              <DriverSearch
                selectedDriver={selectedDriver}
                onSelectDriver={handleSelectDriver}
                disabled={status !== "IDLE"}
              />


              <div className="grid grid-cols-2 gap-1.5">
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px] text-secondary font-semibold">Vận tốc (km/h)</span>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={form.speedMps ? (Number(form.speedMps) * 3.6).toFixed(1) : ""}
                    disabled={status !== "IDLE"}
                    onChange={(e) => setForm((prev) => ({ ...prev, speedMps: String(Number(e.target.value || 0) / 3.6) }))}
                    className="h-7 px-2 text-xs rounded border border-outline-variant/70 bg-white focus:border-primary focus:outline-none"
                  />
                </label>
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px] text-secondary font-semibold">Nhãn kỳ vọng</span>
                  <select
                    role="listbox"
                    aria-label="Nhãn kỳ vọng"
                    value={expectedLabel || ""}
                    disabled={status !== "IDLE"}
                    onChange={(e) => setExpectedLabel((e.target.value as ExpectedLabel) || "")}
                    className="h-7 px-2 text-xs rounded border border-outline-variant/70 bg-white focus:border-primary focus:outline-none"
                  >
                    <option value="">Không gán nhãn (Mặc định)</option>
                    <option value="no_violation">no_violation (Bình thường)</option>
                    <option value="ERR-01">ERR-01 (Sai lộ trình nghiêm trọng)</option>
                    <option value="ERR-02">ERR-02 (Tài xế dừng bất thường)</option>
                    <option value="ERR-03">ERR-03 (Đi ngược chiều / Lạc hướng)</option>
                    <option value="ERR-04">ERR-04 (Hành trình kéo dài quá mức)</option>
                    <option value="ERR-05">ERR-05 (Gian lận khoảng cách / cước)</option>
                    <option value="insufficient_evidence">insufficient_evidence (Không đủ chứng cứ)</option>
                  </select>
                </label>
              </div>

              <div className="grid grid-cols-3 gap-1.5">
                {(["passengerId", "vehicleId", "policyVersionId"] as const).map((key) => {
                  const options = key === "passengerId" ? actors?.passengers : key === "vehicleId" ? actors?.vehicles : actors?.policies;
                  const label = key === "passengerId" ? "Khách" : key === "vehicleId" ? "Xe" : "Chính sách";
                  return (
                    <label key={key} className="flex flex-col gap-0.5">
                      <span className="text-[10px] text-secondary font-semibold">{label}</span>
                      <select
                        aria-label={label}
                        value={form[key]}
                        disabled={!actors || (status !== "IDLE" && status !== "QUEUED")}
                        onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                        className="h-7 px-1 text-xs rounded border border-outline-variant/70 bg-white"
                      >
                        <option value="">{actorsLoading ? "Đang tải…" : "Chọn"}</option>
                        {options?.map((actor) => (
                          <option key={actor.id} value={actor.id}>
                            {actor.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                })}
              </div>

              {resolvedRoute ? (
                <div className="bg-primary-fixed border border-primary-fixed-dim rounded-lg p-2 text-[11px] text-on-primary-fixed flex items-center justify-between">
                  <span className="flex items-center gap-1 font-semibold">
                    <Navigation className="w-3.5 h-3.5 text-primary" /> Lộ trình đường bộ
                  </span>
                  <span>
                    {((resolvedRoute.pickup_route.distance_m + resolvedRoute.destination_route.distance_m) / 1000).toFixed(2)} km
                  </span>
                </div>
              ) : routeResolving ? (
                <div className="bg-gs-blue-soft border border-gs-blue/30 rounded-lg p-2 text-[11px] text-gs-blue flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Đang tìm lộ trình…
                </div>
              ) : routeError ? (
                <div className="bg-gs-amber-soft border border-gs-amber/40 rounded-lg p-2 text-[11px] text-gs-amber">
                  Chưa có lộ trình đường bộ. Hệ thống không hiển thị đường thẳng giả định.
                </div>
              ) : null}

              <button
                onClick={handleCreateRun}
                disabled={submitting || status === "RUNNING" || status === "QUEUED"}
                className="w-full py-2.5 text-xs font-bold rounded bg-primary text-white hover:bg-primary-container disabled:opacity-50 flex items-center justify-center gap-1.5"
              >
                <Play className="w-3.5 h-3.5" />
                {submitting ? "Đang chuẩn bị…" : "Chạy mô phỏng"}
              </button>

              {/* Completion & submission */}
              {runId && (
                <div className="flex flex-col gap-2 border-t border-outline-variant/40 pt-2">
                  <button
                    onClick={handleCompleteTrips}
                    disabled={!canSubmit || submittingTrips}
                    title={canSubmit ? "Gửi chuyến đi đã ghi nhận để xử lý" : "Chỉ bật khi chuyến đi kết thúc"}
                    className="w-full py-2 text-xs font-bold rounded bg-primary text-white hover:bg-primary-container disabled:opacity-50 flex items-center justify-center gap-1.5"
                  >
                    {submittingTrips ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Flag className="w-3.5 h-3.5" />}
                    {status === "CANCELLED" ? "Gửi chuyến đã huỷ" : "Hoàn tất & gửi chuyến"}
                  </button>

                  {(status === "RUNNING" || status === "PAUSED") && (
                    <div className="grid grid-cols-2 gap-1.5">
                      <button
                        onClick={() => {
                          setCancelDialog({ actor: "passenger" });
                          setCancelReason("");
                          setCancelError(null);
                        }}
                        className="py-1.5 text-xs font-semibold rounded border border-gs-line-2 bg-white text-gs-ink-2 hover:bg-surface-container-low"
                      >
                        Khách huỷ chuyến
                      </button>
                      <button
                        onClick={() => {
                          setCancelDialog({ actor: "driver" });
                          setCancelReason("");
                          setCancelError(null);
                        }}
                        className="py-1.5 text-xs font-semibold rounded border border-gs-line-2 bg-white text-gs-ink-2 hover:bg-surface-container-low"
                      >
                        Tài xế huỷ chuyến
                      </button>
                    </div>
                  )}

                  {publishResult && (
                    <Link
                      href={publishResult.destination}
                      className="w-full py-1.5 text-xs text-center font-bold rounded border border-primary-fixed-dim bg-white text-on-primary-fixed hover:bg-primary-fixed flex items-center justify-center gap-1"
                    >
                      <ExternalLink className="w-3.5 h-3.5" /> Xem ở màn hình phân tích
                    </Link>
                  )}
                </div>
              )}

              <div className="border-t border-outline-variant/40 pt-2 space-y-2">
                {totalSteps > 0 && (
                  <div>
                    <div className="flex items-center justify-between text-[11px] text-secondary">
                      <span>Tiến độ</span>
                      <span className="font-mono">{currentStep} / {totalSteps}</span>
                    </div>
                    <div className="w-full h-1.5 bg-surface rounded-full overflow-hidden mt-1">
                      <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${totalSteps > 0 ? (currentStep / totalSteps) * 100 : 0}%` }} />
                    </div>
                  </div>
                )}
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-secondary font-semibold">Tốc độ mô phỏng</span>
                  <SpeedControl
                    value={speedFactor}
                    onChange={handleSetSpeedFactor}
                    disabled={status === "COMPLETED" || status === "CANCELLED"}
                  />
                </div>
              </div>

              {samples.length > 0 && (
                <div className="border-t border-outline-variant/40 pt-2 flex items-center gap-1.5 text-[11px] text-secondary">
                  <Activity className="w-3 h-3" />
                  <span>{samples.length} điểm dữ liệu đã ghi nhận</span>
                </div>
              )}
            </div>
          </div>

          <ResultDock
            open={dockOpen}
            onToggle={() => setDockOpen((prev) => !prev)}
            tab={dockTab}
            onTab={setDockTab}
            logs={logs}
            overview={overview}
            status={status}
            runTrace={runTrace}
          />
        </div>
      )}

      {tab === "presets" && (
        <div className="flex-1 min-h-0 flex overflow-hidden">
          <div className="w-[360px] shrink-0 border-r border-outline-variant/60 bg-surface-container-lowest overflow-y-auto p-3 space-y-2">
            <h2 className="text-xs font-bold text-on-surface">Thư viện chuyến mẫu</h2>
            <p className="text-[11px] text-secondary">Các chuyến ví dụ đã công bố kèm nguồn dữ liệu.</p>
            {presetsLoading && (
              <div className="flex items-center gap-2 text-[11px] text-secondary">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Đang tải…
              </div>
            )}
            {presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                disabled={!preset.available}
                onClick={() => setSelectedPreset(preset.id)}
                className={`w-full text-left rounded-lg border p-2.5 transition ${
                  selectedPreset === preset.id ? "border-primary bg-primary/5" : "border-outline-variant/60 bg-white"
                } ${!preset.available ? "opacity-60 cursor-not-allowed" : "hover:border-primary/60"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-bold">{preset.title}</span>
                  {!preset.available && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gs-amber-soft text-gs-amber">Tạm chưa mở</span>
                  )}
                </div>
                <p className="text-[11px] text-secondary mt-0.5">{preset.description}</p>
                <div className="flex flex-wrap gap-1 mt-1 text-[10px] text-gs-mute-2">
                  <span>{preset.available_trips ?? "?"} chuyến</span>
                  {preset.source_label && <span>· {preset.source_label}</span>}
                  <span>· mẫu: {preset.sample_trips.length}</span>
                </div>
                {!preset.available && preset.unavailable_reason && (
                  <p className="text-[10px] text-gs-amber mt-1">{preset.unavailable_reason}</p>
                )}
              </button>
            ))}
          </div>
          <div className="flex-1 min-w-0 overflow-y-auto p-4">
            {selectedPreset ? (
              <PresetDetail
                presetId={selectedPreset}
                initialPreset={presets.find((p) => p.id === selectedPreset)}
                onOpenInManual={(p, t) => void applyPreset(p, t)}
              />
            ) : (
              <p className="text-xs text-secondary italic">Chọn một chuyến mẫu để xem chi tiết.</p>
            )}
          </div>
        </div>
      )}

      {tab === "history" && (
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-bold">Lịch sử chuyến đi</h2>
            <button type="button" onClick={() => void loadHistory()} className="text-[11px] text-primary hover:underline">
              Tải lại
            </button>
          </div>
          {historyLoading ? (
            <div className="flex items-center gap-2 text-[11px] text-secondary">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Đang tải…
            </div>
          ) : history.length === 0 ? (
            <p className="text-xs text-secondary italic">Chưa có chuyến đi nào trong tổ chức này.</p>
          ) : (
            <HistoryTable runs={history} />
          )}
        </div>
      )}

      {/* Cancellation dialog */}
      {cancelDialog && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Huỷ chuyến"
            onKeyDown={(event) => {
              if (event.key === "Escape") { event.preventDefault(); setCancelDialog(null); }
              if (event.key !== "Tab") return;
              const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), textarea:not(:disabled)"));
              const first = controls[0];
              const last = controls.at(-1);
              if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
              else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
            }}
            className="w-full max-w-md bg-white rounded-lg shadow-xl border border-outline-variant/60 p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold">
                {cancelDialog.actor === "driver" ? "Tài xế huỷ chuyến" : "Khách hàng huỷ chuyến"}
              </h3>
              <button
                type="button"
                onClick={() => setCancelDialog(null)}
                aria-label="Đóng"
                className="p-1 rounded hover:bg-surface-container"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-[11px] text-secondary">Nhập lý do huỷ. Lý do là bắt buộc.</p>
            <textarea
              autoFocus
              value={cancelReason}
              onChange={(e) => {
                setCancelReason(e.target.value);
                if (e.target.value.trim()) setCancelError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") setCancelDialog(null);
              }}
              rows={3}
              placeholder="Lý do huỷ chuyến…"
              aria-label="Lý do huỷ chuyến"
              ref={cancelReasonRef}
              className={`w-full text-xs rounded border p-2 focus:outline-none ${
                cancelError ? "border-error" : "border-outline-variant/70 focus:border-primary"
              }`}
            />
            {cancelError && <p className="text-[11px] text-error">{cancelError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCancelDialog(null)}
                className="px-3 py-1.5 text-xs rounded border border-outline-variant/70 hover:bg-surface-container"
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={confirmCancel}
                disabled={cancelling}
                className="px-3 py-1.5 text-xs font-bold rounded bg-gs-red text-white hover:bg-gs-red/90 disabled:opacity-60 flex items-center gap-1.5"
              >
                {cancelling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                Xác nhận huỷ
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
