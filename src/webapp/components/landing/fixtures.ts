import type {
  ForensicBriefResponse,
  TrafficCorroboration,
} from "@/types/schemas";

export interface DemoCaseData {
  id: string;
  code: string;
  priority: "P0" | "P1" | "P2";
  driverName: string;
  driverId: string;
  plate: string;
  pickup: string;
  dropoff: string;
  fareVnd: number;
  plannedDistKm: number;
  actualDistKm: number;
  varianceKm: number;
  stallDurationS: number;
  meanSpeedKmh: number;
  outcome: string;
  outcomeChip: "destructive" | "emeraldSoft" | "p0" | "p2Soft";
  statusText: string;
  decisionText: string;
  forensicBrief: ForensicBriefResponse;
  trafficCorroboration?: TrafficCorroboration;
}

export const CASE_1_DETOUR: DemoCaseData = {
  id: "case-94021",
  code: "#FC-8921",
  priority: "P0",
  driverName: "Phạm Văn Bình",
  driverId: "DRV-8492",
  plate: "29E-123.45",
  pickup: "Hanoi Central (Tràng Tiền)",
  dropoff: "Long Biên Bridge",
  fareVnd: 145000,
  plannedDistKm: 4.8,
  actualDistKm: 6.2,
  varianceKm: 1.4,
  stallDurationS: 210,
  meanSpeedKmh: 24,
  outcome: "Fraud case opened",
  outcomeChip: "destructive",
  statusText: "Route deviation & 210s idle stall",
  decisionText: "Dismiss penalty: verified impromptu marathon detour (§14.2 Exemption).",
  forensicBrief: {
    case_id: "case-94021",
    trip_id: "trip-94021",
    driver_id: "DRV-8492",
    suspected_category: "ERR-02",
    generated_at: "2026-10-16T08:15:00Z",
    abnormality_count: 2,
    abnormalities: [
      {
        code: "ANOM-01",
        category: "telemetry",
        severity: "warning",
        label: "Detour variance",
        observed_value: "+1.4 km",
        description: "Actual path deviated from arterial corridor",
        evidence_source: "GPS Telemetry",
      },
      {
        code: "ANOM-02",
        category: "telemetry",
        severity: "critical",
        label: "Stationary stall",
        observed_value: "210s",
        description: "Zero velocity recorded at Bà Triệu intersection",
        evidence_source: "Kinematics",
      },
    ],
    summary_text:
      "Planned 4.8 km vs actual 6.2 km (+1.4 km detour). Stopped 210s at Bà Triệu. Nearby traffic confirms a local marathon.",
    evidence_sources: ["GPS Log", "TomTom Peer Flow", "Driver Statement"],
    motivation_assessment: {
      economic_incentive_reward: 0,
      intent_profile: "possible_accidental",
      natural_vietnamese_narrative:
        "Tài xế báo rẽ do công an phân luồng giải chạy marathon. 14 xe xung quanh cùng ghi nhận ùn tắc.",
    },
  },
};

export const CASE_2_NORMAL: DemoCaseData = {
  id: "case-94022",
  code: "#FC-8924",
  priority: "P2",
  driverName: "Trần Minh Đức",
  driverId: "DRV-3319",
  plate: "30F-982.11",
  pickup: "Hoàn Kiếm",
  dropoff: "Cầu Giấy",
  fareVnd: 85000,
  plannedDistKm: 5.5,
  actualDistKm: 5.6,
  varianceKm: 0.1,
  stallDurationS: 0,
  meanSpeedKmh: 31,
  outcome: "No issue",
  outcomeChip: "emeraldSoft",
  statusText: "Route matched corridor · No anomaly",
  decisionText: "Approved automatically: all telemetry within tolerance bounds.",
  forensicBrief: {
    case_id: "case-94022",
    trip_id: "trip-94022",
    driver_id: "DRV-3319",
    suspected_category: null,
    generated_at: "2026-10-16T08:20:00Z",
    abnormality_count: 0,
    abnormalities: [],
    summary_text:
      "Route matched the plan. Speed was normal. No long stops.",
    evidence_sources: ["GPS Log", "Platform Sensor"],
  },
};

export const DEMO_CASES: DemoCaseData[] = [CASE_1_DETOUR, CASE_2_NORMAL];

export interface ChatStep {
  id: string;
  role: "assistant" | "driver";
  text: string;
  hasTrafficWidget?: boolean;
}

export const DRIVER_CHAT_SCRIPT: ChatStep[] = [
  {
    id: "step-1",
    role: "assistant",
    text: "We noticed a 4-minute pause and 1.4 km detour near Bà Triệu intersection. What happened?",
  },
  {
    id: "step-2",
    role: "driver",
    text: "Traffic police diverted all lanes for morning marathon. No road access directly to bridge entrance.",
  },
  {
    id: "step-3",
    role: "assistant",
    text: `<traffic_widget>{"distance_km":6.2,"baseline_duration_min":14,"observed_speed_kmh":18,"congestion_level":"heavy","verdict":"Other drivers took the same detour. Marathon detour verified."}</traffic_widget>`,
    hasTrafficWidget: true,
  },
];

export const QUICK_REPLY_CHIPS = [
  "Police detour",
  "Customer requested stop",
  "Heavy rain delay",
];

export const JOURNEY_STEPS = [
  { id: "trip-ends", number: "01", label: "Trip ends", shortDesc: "Route check" },
  { id: "ai-checks", number: "02", label: "AI checks", shortDesc: "Trip screening" },
  { id: "driver-explains", number: "03", label: "Driver explains", shortDesc: "Fair hearing" },
  { id: "analyst-decides", number: "04", label: "Analyst decides", shortDesc: "Human cockpit" },
  { id: "team-learns", number: "05", label: "Team learns", shortDesc: "Policy loop" },
] as const;

export const FEATURE_CARDS = [
  {
    key: "workplace",
    title: "Fraud Analyst Workplace",
    route: "/workplace",
    linkLabel: "Open Workplace demo: fraud analyst workplace",
    badge: "Sample data",
    desc: "Single cockpit for triage queues, GIS telemetry, and copilot policy recommendations.",
  },
  {
    key: "driver",
    title: "Driver Support Care",
    route: "/driver",
    linkLabel: "Open Driver demo: driver support agent",
    badge: "Sample data",
    desc: "Instant conversational dispute channel allowing drivers to explain route deviations.",
  },
  {
    key: "test",
    title: "Test Console & Studio",
    route: "/test",
    linkLabel: "Open Test demo: fraud detection and test console",
    badge: "Sample data",
    desc: "Simulate custom trips, inject detours, and evaluate automated detector outputs.",
  },
] as const;
