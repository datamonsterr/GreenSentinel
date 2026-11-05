import { AdjudicationCase, DomainEvent, TelemetryEvent } from "@/types/schemas";

export const mockDriverExplanationEvent: DomainEvent<{
  explanation_text: string;
  reason_code?: string;
}> = {
  schema_version: 1,
  event_id: "550e8400-e29b-41d4-a716-446655440010",
  event_type: "driver.explanation_submitted",
  aggregate_type: "case",
  aggregate_id: "550e8400-e29b-41d4-a716-446655440001",
  aggregate_version: 2,
  occurred_at: "2026-09-22T08:15:32Z",
  correlation_id: "550e8400-e29b-41d4-a716-446655440000",
  causation_id: null,
  actor: {
    type: "driver",
    id: "drv-8492-nguyen-van-a",
  },
  payload: {
    explanation_text:
      "Kẹt xe nghiêm trọng tại ngã tư không thể di chuyển được, đường tắc cứng không thể quay đầu hay tiến lên.",
    reason_code: "TRAFFIC_CONGESTION",
  },
  metadata: {
    producer: "driver-mobile-app",
    trace_id: "trace-dic-001",
    simulation_run_id: null,
  },
};

export const mockPassengerCancelEvent: DomainEvent<{
  cancellation_reason: string;
  satisfaction_score?: number;
}> = {
  schema_version: 1,
  event_id: "550e8400-e29b-41d4-a716-446655440011",
  event_type: "passenger.cancelled",
  aggregate_type: "trip",
  aggregate_id: "550e8400-e29b-41d4-a716-446655440002",
  aggregate_version: 3,
  occurred_at: "2026-09-22T08:15:44Z",
  correlation_id: "550e8400-e29b-41d4-a716-446655440000",
  causation_id: null,
  actor: {
    type: "passenger",
    id: "usr-9012-hoang-mai",
  },
  payload: {
    cancellation_reason:
      "Tài xế đứng yên tại chỗ hơn 5 phút không tới đón, gọi điện không bắt máy. Phải tự hủy để đặt xe khác kịp giờ bay.",
    satisfaction_score: 1,
  },
  metadata: {
    producer: "passenger-mobile-app",
    trace_id: "trace-dic-001",
  },
};

export const mockAiAssessmentEvent: DomainEvent<{
  confidence_pct: number;
  primary_violation_code: "ERR-01" | "ERR-02" | "ERR-03" | "ERR-04" | "ERR-05";
  recommended_sanction: string;
  rationale: string;
  policy_citation: string;
}> = {
  schema_version: 1,
  event_id: "550e8400-e29b-41d4-a716-446655440012",
  event_type: "assessment.completed",
  aggregate_type: "assessment",
  aggregate_id: "550e8400-e29b-41d4-a716-446655440003",
  aggregate_version: 1,
  occurred_at: "2026-09-22T08:15:50Z",
  correlation_id: "550e8400-e29b-41d4-a716-446655440000",
  causation_id: "550e8400-e29b-41d4-a716-446655440011",
  actor: {
    type: "service",
    id: "greensm-forensic-copilot",
  },
  payload: {
    confidence_pct: 92,
    primary_violation_code: "ERR-02",
    recommended_sanction: "Disagree (System Error)",
    rationale:
      "Tài xế Nguyễn Văn A nhận cuốc lúc 08:12 tại 12 Bà Triệu. Xe dừng bất động 210s tại ngã tư Bà Triệu - Lý Thường Kiệt dù đường thông thoáng (32 km/h).",
    policy_citation: "Điều 14.2 Quy chế Đối tác GreenSM (Q3/2026)",
  },
  metadata: {
    producer: "langgraph-sentinel-agent",
    trace_id: "trace-dic-001",
  },
};

export const mockTelemetryEvents: TelemetryEvent[] = [
  {
    schema_version: 1,
    event_id: "a1b2c3d4-e5f6-4a1b-8c2d-0e1f2a3b4c5d",
    event_type: "telemetry.observed",
    source: "obd2-sentinel-tracker",
    occurred_at: "2026-09-22T08:12:00Z",
    correlation_id: "550e8400-e29b-41d4-a716-446655440000",
    causation_id: null,
    simulation_run_id: null,
    trip_id: "550e8400-e29b-41d4-a716-446655440002",
    assignment_id: "550e8400-e29b-41d4-a716-446655440004",
    driver_id: "550e8400-e29b-41d4-a716-446655440005",
    sequence: 1,
    payload: {
      position: {
        latitude: 21.0285,
        longitude: 105.8542,
        accuracy_m: 2.1,
      },
      speed_mps: 8.8,
      bearing_deg: 178,
      app_state: "foreground",
      network_state: "online",
      gps_state: "valid",
      mock_location_reported: false,
    },
  },
  {
    schema_version: 1,
    event_id: "b2c3d4e5-f6a1-4b2c-9d3e-1f2a3b4c5d6e",
    event_type: "telemetry.observed",
    source: "obd2-sentinel-tracker",
    occurred_at: "2026-09-22T08:13:30Z",
    correlation_id: "550e8400-e29b-41d4-a716-446655440000",
    causation_id: null,
    simulation_run_id: null,
    trip_id: "550e8400-e29b-41d4-a716-446655440002",
    assignment_id: "550e8400-e29b-41d4-a716-446655440004",
    driver_id: "550e8400-e29b-41d4-a716-446655440005",
    sequence: 2,
    payload: {
      position: {
        latitude: 21.0271,
        longitude: 105.8539,
        accuracy_m: 1.8,
      },
      speed_mps: 0.0,
      bearing_deg: 178,
      app_state: "foreground",
      network_state: "online",
      gps_state: "valid",
      mock_location_reported: false,
    },
  },
];

export const primaryAdjudicationCase: AdjudicationCase = {
  id: "case-8921",
  case_token: "#FC-8921",
  trip_id: "550e8400-e29b-41d4-a716-446655440002",
  assignment_id: "550e8400-e29b-41d4-a716-446655440004",
  driver_id: "550e8400-e29b-41d4-a716-446655440005",
  driver_name: "Nguyễn Văn A",
  vehicle_plate: "29E-123.45",
  severity: "P0",
  locked_by: "Tuấn LM",
  sla_countdown_s: 28,
  initial_sla_budget_s: 45,
  stall_duration_s: 210,
  davi_drift: -0.84,
  pickup_address: "12 Phố Bà Triệu, Hoàn Kiếm",
  dropoff_address: "Sân bay Quốc tế Nội Bài",
  fare_amount_vnd: 340000,
  dispute: {
    driver_explanation: mockDriverExplanationEvent,
    passenger_cancel: mockPassengerCancelEvent,
  },
  telemetry_points: mockTelemetryEvents,
  ai_assessment: mockAiAssessmentEvent,
};

export const mockDriverInitial = {
  latitude: 21.025,
  longitude: 105.8512,
  label: "Vị trí ban đầu tài xế (Bắt đầu nhận cuốc)",
};

export const mockDestination = {
  latitude: 21.035,
  longitude: 105.86,
  label: "Điểm trả khách / Sân bay Nội Bài",
};

export const mockCandidateRoutes = [
  {
    id: "route-opt-shortest",
    name: "Tuyến 1: Ngắn nhất (Trực diện Bà Triệu)",
    type: "shortest" as const,
    rank: 1 as const,
    distance_m: 680,
    duration_s: 150,
    davi: 0.04,
    sdd: 1.02,
    traffic_signals_count: 2,
    congestion_level: "clear" as const,
    color: "#2563eb",
    coordinates: [
      [105.8512, 21.025],
      [105.8522, 21.0262],
      [105.8532, 21.0274],
      [105.8542, 21.0285],
    ] as [number, number][],
  },
  {
    id: "route-arterial",
    name: "Tuyến 2: Đại lộ Trần Hưng Đạo (Rộng rãi)",
    type: "arterial" as const,
    rank: 2 as const,
    distance_m: 910,
    duration_s: 210,
    davi: 0.09,
    sdd: 1.18,
    traffic_signals_count: 3,
    congestion_level: "moderate" as const,
    color: "#0d9488",
    coordinates: [
      [105.8512, 21.025],
      [105.8535, 21.025],
      [105.8542, 21.0285],
    ] as [number, number][],
  },
  {
    id: "route-detour-alt",
    name: "Tuyến 3: Tuyến đường vòng (Hai Bà Trưng)",
    type: "detour" as const,
    rank: 3 as const,
    distance_m: 1350,
    duration_s: 340,
    davi: -0.38,
    sdd: 1.55,
    traffic_signals_count: 4,
    congestion_level: "heavy" as const,
    color: "#8b5cf6",
    coordinates: [
      [105.8512, 21.025],
      [105.848, 21.025],
      [105.848, 21.0285],
      [105.8542, 21.0285],
    ] as [number, number][],
  },
];

export const mockMissingnessAlerts = [
  {
    alert_id: "gap-alert-001",
    start_time: "2026-09-22T08:13:30Z",
    end_time: "2026-09-22T08:14:15Z",
    gap_duration_s: 45,
    reason: "Mất kết nối mạng di động (Network degraded): gián đoạn telemetry 45s",
    severity: "warning" as const,
  },
];

export const mockTrafficCorroboration = {
  road_segment: "Phố Bà Triệu - Lý Thường Kiệt",
  observed_at: "2026-09-22T08:13:30Z",
  suspect_driver: {
    driver_id: "drv-8492-nguyen-van-a",
    speed_kmh: 0.0,
    stall_duration_s: 210,
    claimed_reason: "Kẹt xe nghiêm trọng tại ngã tư không thể di chuyển",
  },
  peer_drivers: [
    {
      driver_id: "drv-peer-01",
      vehicle_plate: "29A-456.78",
      speed_kmh: 34.0,
      passed_at: "08:13:10",
      status: "clear",
    },
    {
      driver_id: "drv-peer-02",
      vehicle_plate: "29E-889.01",
      speed_kmh: 31.5,
      passed_at: "08:14:05",
      status: "clear",
    },
    {
      driver_id: "drv-peer-03",
      vehicle_plate: "29X-112.34",
      speed_kmh: 38.0,
      passed_at: "08:15:20",
      status: "clear",
    },
  ],
  public_service: {
    provider: "Google Maps Traffic Mock",
    average_speed_kmh: 33.2,
    congestion: "clear" as const,
    signal_status: "green_wave_active",
  },
  verdict: "refuted" as const,
  verdict_detail:
    "Tuyên bố kẹt xe bị bác bỏ (Traffic claim refuted): Dịch vụ Google Maps Traffic Mock báo đường thông suốt (33.2 km/h). 3 tài xế khác cùng di chuyển bình thường (>31 km/h), trong khi tài xế dừng bất động 210s.",
};

export const mockTimelineMilestones = [
  {
    id: "ms-start",
    timestamp: "2026-09-22T08:10:00Z",
    sequence: 0,
    type: "start_match" as const,
    title: "",
    description: "Thời gian bắt đầu hành trình",
    lat: 21.025,
    lon: 105.8512,
    speed_mps: 0.0,
    latency_ms: 42.0,
    davi: 0.04,
    is_anomaly: false,
  },
  {
    id: "ms-stall",
    timestamp: "2026-09-22T08:13:30Z",
    sequence: 1,
    type: "stall_anomaly" as const,
    title: "Bất thường dừng đỗ (210s Stall)",
    description: "Phát hiện xe dừng bất động kéo dài 210s tại ngã tư Bà Triệu",
    lat: 21.0268,
    lon: 105.852,
    speed_mps: 0.0,
    latency_ms: 48.0,
    davi: -0.84,
    is_anomaly: true,
  },
  {
    id: "ms-gap-001",
    timestamp: "2026-09-22T08:13:45Z",
    type: "gap_anomaly" as const,
    title: "Mất kết nối mạng (45s Gap)",
    description: "Gián đoạn truyền dữ liệu do mạng di động suy giảm",
    is_anomaly: true,
  },
  {
    id: "ms-pickup",
    timestamp: "2026-09-22T08:16:30Z",
    sequence: 2,
    type: "pickup" as const,
    title: "Điểm đón khách (Pickup Point)",
    description: "12 Phố Bà Triệu, Hoàn Kiếm",
    lat: 21.0285,
    lon: 105.8542,
    speed_mps: 0.0,
    latency_ms: 38.0,
    davi: 0.05,
    is_anomaly: false,
  },
  {
    id: "ms-dropoff",
    timestamp: "2026-09-22T08:35:00Z",
    sequence: 3,
    type: "dropoff_destination" as const,
    title: "Đích đến (Destination)",
    description: "Sân bay Quốc tế Nội Bài",
    lat: 21.035,
    lon: 105.86,
    speed_mps: 11.5,
    latency_ms: 45.0,
    davi: 0.02,
    is_anomaly: false,
  },
];

