-- Migration: 20260926220000_poc_v2_precedent_workflows_and_trace.sql
-- Description: Add workflow_trace to app.fraud_cases and create app.precedent_workflows table with seeded precedents

SET search_path = app, extensions, public;

-- 1. Add workflow_trace JSONB column to fraud_cases
ALTER TABLE app.fraud_cases 
ADD COLUMN IF NOT EXISTS workflow_trace JSONB;

CREATE INDEX IF NOT EXISTS idx_fraud_cases_workflow_trace_gin 
ON app.fraud_cases USING gin (workflow_trace);

-- 2. Create app.precedent_workflows table
CREATE TABLE IF NOT EXISTS app.precedent_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES app.fraud_cases(id) ON DELETE SET NULL,
    violation_code VARCHAR(32) NOT NULL,
    claim_type VARCHAR(64) NOT NULL,
    district VARCHAR(64),
    title VARCHAR(255) NOT NULL,
    driver_statement_summary TEXT,
    workflow_trace JSONB NOT NULL,
    verdict VARCHAR(64) NOT NULL,
    confidence_score NUMERIC(4,3) DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_precedent_workflows_violation_claim 
ON app.precedent_workflows(violation_code, claim_type);

CREATE INDEX IF NOT EXISTS idx_precedent_workflows_trace_gin 
ON app.precedent_workflows USING gin (workflow_trace);

-- 3. Seed 5 realistic historical precedent workflows
INSERT INTO app.precedent_workflows (
    id,
    violation_code,
    claim_type,
    district,
    title,
    driver_statement_summary,
    workflow_trace,
    verdict,
    confidence_score
)
VALUES 
-- Precedent 1: Kim Ma Traffic Gridlock (Auto-Exoneration)
(
    '018f2f4e-9100-7000-8000-000000000001',
    'ERR-02',
    'traffic_gridlock',
    'Ba Dinh',
    'Ùn tắc giao thông nghiêm trọng giờ cao điểm đường Kim Mã',
    'Đoạn đường Kim Mã - Liễu Giai bị kẹt xe kéo dài, xe điện di chuyển dưới 5km/h trong hơn 25 phút.',
    '{
        "agent_tools_called": [
            {
                "tool_name": "corroborate_traffic_conditions",
                "input_summary": "corridor=Kim Ma, start_time=17:30, end_time=18:15",
                "output_summary": "speed=2.1 km/h, ratio=2.7x, congestion=heavy, gps_valid=true, prior_sanctions=0",
                "executed_at": "2026-09-24T18:16:00Z",
                "status": "success"
            },
            {
                "tool_name": "query_driver_policy",
                "input_summary": "query=traffic congestion stall leeway",
                "output_summary": "GSM-POL-042 clause 3.2 allows 100% waiver when speed < 5km/h and duration ratio >= 2.0x",
                "executed_at": "2026-09-24T18:16:05Z",
                "status": "success"
            }
        ],
        "human_actions_performed": [
            {
                "actor_role": "driver",
                "action_type": "dispute_statement",
                "summary": "Tài xế bấm nút báo kẹt xe Kim Mã trên ứng dụng Driver App",
                "timestamp": "2026-09-24T18:15:30Z"
            }
        ],
        "driver_response_summary": "Đoạn đường Kim Mã - Liễu Giai bị kẹt xe kéo dài, xe điện di chuyển dưới 5km/h trong hơn 25 phút.",
        "related_policies": [
            {
                "policy_code": "GSM-POL-042",
                "clause": "3.2 (Bất khả kháng do giao thông đô thị)",
                "rationale": "Miễn trừ chế tài trễ đón khách khi vận tốc dưới 5 km/h và tỷ lệ vượt trên 2.0x",
                "relevance_score": 0.98
            }
        ],
        "final_decision": {
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Xác thực kẹt xe Kim Mã tự động từ viễn thông thực tế (tốc độ TB 2.1 km/h, tỷ lệ 2.7x). Miễn trừ toàn bộ chế tài.",
            "decided_by": "system_autonomous_agent",
            "decided_at": "2026-09-24T18:16:10Z"
        }
    }'::jsonb,
    'exonerated',
    0.98
),
-- Precedent 2: Nguyen Chi Thanh Stalled Bus Breakdown (Analyst Guided Exoneration)
(
    '018f2f4e-9100-7000-8000-000000000002',
    'ERR-02',
    'traffic_gridlock',
    'Dong Da',
    'Xe buýt chết máy chắn lối rẽ Nguyễn Chí Thanh',
    'Sự cố xe buýt chết máy chắn ngang đường Nguyễn Chí Thanh khiến phương tiện không thể quay đầu đón khách đúng hẹn.',
    '{
        "agent_tools_called": [
            {
                "tool_name": "corroborate_traffic_conditions",
                "input_summary": "corridor=Nguyen Chi Thanh, start_time=08:10, end_time=08:40",
                "output_summary": "speed=3.4 km/h, ratio=2.3x, congestion=heavy, gps_valid=true, prior_sanctions=0",
                "executed_at": "2026-09-25T08:42:00Z",
                "status": "success"
            },
            {
                "tool_name": "query_driver_policy",
                "input_summary": "query=road obstacle obstruction policy",
                "output_summary": "GSM-POL-042 clause 3.4 permits waiver upon third-party incident verification",
                "executed_at": "2026-09-25T08:42:15Z",
                "status": "success"
            }
        ],
        "human_actions_performed": [
            {
                "actor_role": "driver",
                "action_type": "dispute_statement",
                "summary": "Tài xế giải trình bị kẹt do xe buýt chết máy chắn ngang lối rẽ",
                "timestamp": "2026-09-25T08:41:00Z"
            },
            {
                "actor_role": "analyst",
                "action_type": "delegate_inquiry",
                "summary": "Chuyên viên yêu cầu cung cấp vị trí chính xác của xe buýt gặp sự cố",
                "timestamp": "2026-09-25T08:45:00Z"
            },
            {
                "actor_role": "driver",
                "action_type": "driver_response",
                "summary": "Tài xế phản hồi vị trí lối rẽ trước cổng Học viện Phụ nữ Việt Nam",
                "timestamp": "2026-09-25T08:48:00Z"
            }
        ],
        "driver_response_summary": "Tôi bị kẹt ở lối rẽ Nguyễn Chí Thanh trước cổng Học viện Phụ nữ do có xe buýt chết máy chắn ngang.",
        "related_policies": [
            {
                "policy_code": "GSM-POL-042",
                "clause": "3.4 (Chướng ngại vật và sự cố giao thông đột xuất)",
                "rationale": "Chấp thuận giải trình sự cố chắn đường khi telemetry xác nhận đứng yên trên tuyến",
                "relevance_score": 0.94
            }
        ],
        "final_decision": {
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Đã xác minh nguyên nhân kẹt xe đột xuất từ giải trình bổ sung của tài xế và dữ liệu viễn thông. Chấp thuận miễn trừ trách nhiệm.",
            "decided_by": "018f2f4e-1000-7000-8000-000000000001",
            "decided_at": "2026-09-25T08:52:00Z"
        }
    }'::jsonb,
    'exonerated',
    0.95
),
-- Precedent 3: Vincom Royal City Basement GPS Dropout (Exonerated)
(
    '018f2f4e-9100-7000-8000-000000000003',
    'ERR-05',
    'gps_issue',
    'Thanh Xuan',
    'Mất tín hiệu GPS tầng hầm B2 trung tâm thương mại Vincom Royal City',
    'Tài xế vào hầm B2 đón khách dẫn đến tín hiệu GPS bị gián đoạn và nhảy tọa độ ngoài ý muốn.',
    '{
        "agent_tools_called": [
            {
                "tool_name": "get_driver_dispute_context",
                "input_summary": "case_id=018f2f4e-..., district=Thanh Xuan",
                "output_summary": "Alleged violation ERR-05 at Royal City basement B2",
                "executed_at": "2026-09-23T14:10:00Z",
                "status": "success"
            },
            {
                "tool_name": "query_driver_policy",
                "input_summary": "query=underground basement gps signal drop",
                "output_summary": "GSM-POL-088 clause 2.1 recognizes GPS attenuation in subterranean parking structures",
                "executed_at": "2026-09-23T14:10:15Z",
                "status": "success"
            }
        ],
        "human_actions_performed": [
            {
                "actor_role": "driver",
                "action_type": "dispute_statement",
                "summary": "Tài xế báo cáo mất sóng GPS khi vào hầm B2 đón khách",
                "timestamp": "2026-09-23T14:09:00Z"
            }
        ],
        "driver_response_summary": "Đón khách ở sảnh R3 hầm B2 Royal City, dưới hầm mất sóng GPS nên bản đồ không cập nhật vị trí.",
        "related_policies": [
            {
                "policy_code": "GSM-POL-088",
                "clause": "2.1 (Hao suy tín hiệu GPS trong công trình ngầm)",
                "rationale": "Cho phép miễn trừ vi phạm mất tín hiệu GPS khi điểm đón/trả nằm tại tầng hầm TTTM",
                "relevance_score": 0.96
            }
        ],
        "final_decision": {
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Xác nhận điểm đón tại hầm B2 Vincom Royal City. Hiện tượng mất sóng GPS phù hợp với đặc điểm địa hình công trình ngầm.",
            "decided_by": "018f2f4e-1000-7000-8000-000000000001",
            "decided_at": "2026-09-23T14:15:00Z"
        }
    }'::jsonb,
    'exonerated',
    0.93
),
-- Precedent 4: Tay Ho Fake GPS Spoofing (Penalty Applied)
(
    '018f2f4e-9100-7000-8000-000000000004',
    'ERR-05',
    'gps_issue',
    'Tay Ho',
    'Sử dụng phần mềm giả lập vị trí GPS (Mock Location)',
    'Thiết bị ghi nhận cờ mock_location_reported = true và bước nhảy tọa độ 120km/h phi thực tế.',
    '{
        "agent_tools_called": [
            {
                "tool_name": "corroborate_traffic_conditions",
                "input_summary": "case_id=..., check_mock=true",
                "output_summary": "mock_location_reported=true, teleportation_detected=true, speed=120.0 km/h",
                "executed_at": "2026-09-22T10:15:00Z",
                "status": "success"
            },
            {
                "tool_name": "query_driver_policy",
                "input_summary": "query=mock location fake gps penalty",
                "output_summary": "GSM-POL-019 clause 4.3 mandates Level 2 penalty (500,000 VND + 3-day account suspension)",
                "executed_at": "2026-09-22T10:15:30Z",
                "status": "success"
            }
        ],
        "human_actions_performed": [
            {
                "actor_role": "driver",
                "action_type": "dispute_statement",
                "summary": "Tài xế khiếu nại do điện thoại bị lỗi định vị",
                "timestamp": "2026-09-22T10:12:00Z"
            },
            {
                "actor_role": "analyst",
                "action_type": "decision_submit",
                "summary": "Chuyên viên đối soát log hệ thống phát hiện can thiệp ứng dụng bên thứ 3",
                "timestamp": "2026-09-22T10:20:00Z"
            }
        ],
        "driver_response_summary": "Điện thoại của tôi bị lỗi định vị nhảy vị trí, không phải do tôi cài phần mềm giả lập.",
        "related_policies": [
            {
                "policy_code": "GSM-POL-019",
                "clause": "4.3 (Gian lận vị trí viễn thông)",
                "rationale": "Xử phạt nghiêm đối với hành vi sử dụng mock location hoặc can thiệp định vị",
                "relevance_score": 0.99
            }
        ],
        "final_decision": {
            "verdict": "penalty_applied",
            "penalty_amount": 500000,
            "rationale": "Dữ liệu viễn thông ghi nhận cờ giả lập tọa độ (Mock Location Flag: True) và tốc độ tức thời 120km/h trên phố đi bộ Hồ Tây. Bác khiếu nại, áp dụng chế tài Mức 2.",
            "decided_by": "018f2f4e-1000-7000-8000-000000000001",
            "decided_at": "2026-09-22T10:25:00Z"
        }
    }'::jsonb,
    'penalty_applied',
    0.99
),
-- Precedent 5: Cau Giay Extended Passenger Wait (Exonerated)
(
    '018f2f4e-9100-7000-8000-000000000005',
    'ERR-02',
    'passenger_wait',
    'Cau Giay',
    'Khách hàng yêu cầu chờ quá 15 phút tại cổng trường Đại học Quốc gia',
    'Khách hàng nhắn tin qua ứng dụng yêu cầu tài xế đỗ chờ để lấy đồ trong ký túc xá.',
    '{
        "agent_tools_called": [
            {
                "tool_name": "get_driver_dispute_context",
                "input_summary": "case_id=..., passenger_wait=true",
                "output_summary": "Pickup wait time: 18 mins, passenger chat confirmed wait request",
                "executed_at": "2026-09-21T16:20:00Z",
                "status": "success"
            },
            {
                "tool_name": "query_driver_policy",
                "input_summary": "query=passenger requested wait pickup delay",
                "output_summary": "GSM-POL-012 clause 1.4 exempts driver stall when customer explicitly requested wait via in-app chat",
                "executed_at": "2026-09-21T16:20:30Z",
                "status": "success"
            }
        ],
        "human_actions_performed": [
            {
                "actor_role": "driver",
                "action_type": "dispute_statement",
                "summary": "Tài xế báo cáo khách hàng gọi điện/nhắn tin nhờ chờ lấy hành lý",
                "timestamp": "2026-09-21T16:18:00Z"
            }
        ],
        "driver_response_summary": "Khách hàng nhắn tin nhờ chờ ở cổng ký túc xá ĐHQG để mang vali xuống. Tôi có giữ tin nhắn của khách.",
        "related_policies": [
            {
                "policy_code": "GSM-POL-012",
                "clause": "1.4 (Chờ khách theo thỏa thuận)",
                "rationale": "Không tính lỗi cố tình ngâm chuyến khi khách hàng yêu cầu chờ và có tin nhắn xác thực",
                "relevance_score": 0.95
            }
        ],
        "final_decision": {
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Tin nhắn trong chuyến đi xác nhận khách hàng chủ động yêu cầu tài xế chờ tại điểm đón. Miễn trừ toàn bộ chế tài vi phạm ERR-02.",
            "decided_by": "018f2f4e-1000-7000-8000-000000000001",
            "decided_at": "2026-09-21T16:25:00Z"
        }
    }'::jsonb,
    'exonerated',
    0.94
)
ON CONFLICT (id) DO NOTHING;
