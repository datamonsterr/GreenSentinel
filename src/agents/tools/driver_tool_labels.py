"""Natural-language i18n-friendly labels for driver-facing tools."""

from __future__ import annotations

DRIVER_TOOL_LABELS_VI: dict[str, str] = {
    "get_driver_dispute_context": "Đang kiểm tra thông tin vụ việc",
    "corroborate_traffic_conditions": "Đang đối soát tình trạng giao thông",
    "fetch_corridor_historical_traffic": "Đang kiểm tra lịch sử giao thông tuyến đường",
    "query_traffic_incident_feed": "Đang tra cứu cảnh báo sự cố giao thông",
    "inspect_trip_telemetry": "Đang đối soát dữ liệu hành trình",
    "verify_exoneration_rules": "Đang thẩm định điều kiện miễn trừ (Điều 12.2)",
    "submit_driver_statement": "Đang ghi nhận giải trình của tài xế",
    "query_driver_policy": "Đang tra cứu quy chế hỗ trợ đối tác",
    "geocode_address": "Đang xác định vị trí địa chỉ",
    "reverse_geocode_coordinates": "Đang tra cứu toạ độ địa chỉ",
    "match_trip_telemetry": "Đang khớp dữ liệu viễn thông hành trình",
    "list_my_cases": "Đang kiểm tra danh sách vụ việc của bạn",
    "get_case_timeline": "Đang tải tiến trình xử lý vụ việc",
    "explain_case_status": "Đang phân tích trạng thái hồ sơ",
    "get_my_scorecard": "Đang kiểm tra điểm đánh giá hoạt động",
    "list_my_trips": "Đang xem danh sách các chuyến xe",
    "get_trip_summary": "Đang tải tóm tắt chuyến đi",
    "check_weather_condition": "Đang kiểm tra điều kiện thời tiết",
    "check_traffic_situation": "Đang kiểm tra tình hình giao thông",
    "get_forensic_brief": "Đang đối soát dữ liệu bất thường",
    "suggest_dispute_path": "Đang phân tích phương án giải trình",
    "assess_statement_completeness": "Đang kiểm tra nội dung giải trình",
    "get_appeal_options": "Đang tra cứu hướng dẫn khiếu nại",
}

DRIVER_TOOL_LABELS_EN: dict[str, str] = {
    "get_driver_dispute_context": "Checking case details",
    "corroborate_traffic_conditions": "Checking traffic conditions",
    "fetch_corridor_historical_traffic": "Checking historical corridor traffic",
    "query_traffic_incident_feed": "Checking traffic incident feed",
    "inspect_trip_telemetry": "Inspecting trip telemetry",
    "verify_exoneration_rules": "Verifying force majeure exoneration rules",
    "submit_driver_statement": "Submitting driver statement",
    "query_driver_policy": "Reviewing driver policies",
    "geocode_address": "Locating address",
    "reverse_geocode_coordinates": "Resolving coordinates address",
    "match_trip_telemetry": "Matching trip telemetry",
    "list_my_cases": "Checking your cases",
    "get_case_timeline": "Checking case timeline",
    "explain_case_status": "Analyzing case status",
    "get_my_scorecard": "Checking driver scorecard",
    "list_my_trips": "Checking your trips",
    "get_trip_summary": "Retrieving trip summary",
    "check_weather_condition": "Checking weather conditions",
    "check_traffic_situation": "Checking traffic conditions",
    "get_forensic_brief": "Reviewing recorded abnormalities",
    "suggest_dispute_path": "Analyzing dispute options",
    "assess_statement_completeness": "Assessing statement completeness",
    "get_appeal_options": "Checking appeal options",
}


def get_driver_tool_label(name: str, locale: str = "vi") -> str:
    """Return natural-language i18n-friendly label for driver tools.

    Never emit raw internal tool names to the user.
    """
    labels = DRIVER_TOOL_LABELS_EN if str(locale).lower().startswith("en") else DRIVER_TOOL_LABELS_VI
    if name in labels:
        return labels[name]
    clean_name = name.replace("_", " ").strip()
    return f"Checking {clean_name}" if str(locale).lower().startswith("en") else f"Đang kiểm tra {clean_name}"


__all__ = ["DRIVER_TOOL_LABELS_EN", "DRIVER_TOOL_LABELS_VI", "get_driver_tool_label"]
