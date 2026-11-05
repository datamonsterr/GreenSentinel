/**
 * Vietnamese first-person tool label mappings and Lucide icons for AI Copilot tools.
 */

export interface ToolLabelInfo {
  running: string;
  done: string;
  icon: string;
}

export const TOOL_LABELS: Record<string, ToolLabelInfo> = {
  adjudicate_case: {
    running: "Tôi đang phân xử vụ việc",
    done: "Đã phân xử vụ việc",
    icon: "Gavel",
  },
  check_related_cases_to_vehicle: {
    running: "Tôi đang tra cứu các vụ việc liên quan đến phương tiện",
    done: "Đã tra cứu các vụ việc liên quan đến phương tiện",
    icon: "Car",
  },
  check_traffic_situation: {
    running: "Tôi đang kiểm tra tình hình giao thông",
    done: "Đã kiểm tra tình hình giao thông",
    icon: "TrafficCone",
  },
  check_weather_condition: {
    running: "Tôi đang kiểm tra điều kiện thời tiết",
    done: "Đã kiểm tra điều kiện thời tiết",
    icon: "CloudSun",
  },
  claim_case: {
    running: "Tôi đang nhận thụ lý vụ việc",
    done: "Đã nhận thụ lý vụ việc",
    icon: "FolderCheck",
  },
  fetch_corridor_historical_traffic: {
    running: "Tôi đang tải dữ liệu lịch sử giao thông tuyến đường",
    done: "Đã tải dữ liệu lịch sử giao thông tuyến đường",
    icon: "History",
  },
  geocode_address: {
    running: "Tôi đang định vị địa chỉ",
    done: "Đã định vị địa chỉ",
    icon: "MapPin",
  },
  get_audit_log: {
    running: "Tôi đang kiểm tra nhật ký kiểm toán",
    done: "Đã kiểm tra nhật ký kiểm toán",
    icon: "FileClock",
  },
  get_case_context: {
    running: "Tôi đang tải ngữ cảnh vụ việc",
    done: "Đã tải ngữ cảnh vụ việc",
    icon: "Briefcase",
  },
  get_driver_history: {
    running: "Tôi đang tải lịch sử tài xế",
    done: "Đã tải lịch sử tài xế",
    icon: "UserCheck",
  },
  inspect_trip_telemetry: {
    running: "Tôi đang đối soát dữ liệu hành trình",
    done: "Đã đối soát dữ liệu hành trình",
    icon: "Route",
  },
  list_cases: {
    running: "Tôi đang xem danh sách vụ việc",
    done: "Đã xem danh sách vụ việc",
    icon: "List",
  },
  match_trip_telemetry: {
    running: "Tôi đang khớp dữ liệu viễn thông hành trình",
    done: "Đã khớp dữ liệu viễn thông hành trình",
    icon: "Activity",
  },
  query_cases_db: {
    running: "Tôi đang truy vấn cơ sở dữ liệu vụ việc",
    done: "Đã truy vấn cơ sở dữ liệu vụ việc",
    icon: "Database",
  },
  query_traffic_incident_feed: {
    running: "Tôi đang kiểm tra thông tin sự cố giao thông",
    done: "Đã kiểm tra thông tin sự cố giao thông",
    icon: "AlertTriangle",
  },
  record_case_action: {
    running: "Tôi đang ghi nhận hành động xử lý",
    done: "Đã ghi nhận hành động xử lý",
    icon: "ClipboardPen",
  },
  reverse_geocode_coordinates: {
    running: "Tôi đang tra cứu địa chỉ từ toạ độ",
    done: "Đã tra cứu địa chỉ từ toạ độ",
    icon: "LocateFixed",
  },
  search_policy_documents: {
    running: "Tôi đang tìm kiếm tài liệu quy chế",
    done: "Đã tìm kiếm tài liệu quy chế",
    icon: "BookOpen",
  },
  submit_driver_statement: {
    running: "Tôi đang gửi lời trình bày của tài xế",
    done: "Đã gửi lời trình bày của tài xế",
    icon: "Send",
  },
  trigger_simulation: {
    running: "Tôi đang chạy kịch bản mô phỏng",
    done: "Đã chạy kịch bản mô phỏng",
    icon: "Play",
  },
  verify_exoneration_rules: {
    running: "Tôi đang xác minh quy tắc miễn trừ",
    done: "Đã xác minh quy tắc miễn trừ",
    icon: "ShieldCheck",
  },
  write_ticket_for_driver: {
    running: "Tôi đang lập biên bản cho tài xế",
    done: "Đã lập biên bản cho tài xế",
    icon: "FileSpreadsheet",
  },
  get_case_detail: {
    running: "Tôi đang tải chi tiết vụ việc",
    done: "Đã tải chi tiết vụ việc",
    icon: "FileText",
  },
  get_driver_card: {
    running: "Tôi đang tải thẻ thông tin tài xế",
    done: "Đã tải thẻ thông tin tài xế",
    icon: "Contact",
  },
  get_forensic_brief: {
    running: "Tôi đang tóm tắt vụ việc",
    done: "Đã tóm tắt vụ việc",
    icon: "FileSearch",
  },
  get_case_policy: {
    running: "Tôi đang tải quy chế áp dụng cho vụ việc",
    done: "Đã tải quy chế áp dụng cho vụ việc",
    icon: "Scale",
  },
  query_policy: {
    running: "Tôi đang tra cứu quy chế",
    done: "Đã tra cứu quy chế",
    icon: "Search",
  },
  search_policy: {
    running: "Tôi đang tra cứu quy định",
    done: "Đã tra cứu quy định",
    icon: "Search",
  },
  get_telemetry_trace: {
    running: "Tôi đang lấy lộ trình viễn thông",
    done: "Đã lấy lộ trình viễn thông",
    icon: "Route",
  },
  check_driver_suspension: {
    running: "Tôi đang kiểm tra tình trạng đình chỉ tài xế",
    done: "Đã kiểm tra tình trạng đình chỉ tài xế",
    icon: "UserX",
  },
  corroborate_traffic_conditions: {
    running: "Tôi đang đối chiếu điều kiện giao thông",
    done: "Đã đối chiếu điều kiện giao thông",
    icon: "CheckCircle2",
  },
  get_driver_dispute_context: {
    running: "Tôi đang tải ngữ cảnh khiếu nại tài xế",
    done: "Đã tải ngữ cảnh khiếu nại tài xế",
    icon: "FileQuestion",
  },
  query_driver_policy: {
    running: "Tôi đang tra cứu chính sách dành cho tài xế",
    done: "Đã tra cứu chính sách dành cho tài xế",
    icon: "HelpCircle",
  },
  ask_interactive_question: {
    running: "Tôi đang đặt câu hỏi làm rõ",
    done: "Đã đặt câu hỏi làm rõ",
    icon: "MessageSquare",
  },
  preview_case_minutes: {
    running: "Tôi đang xem trước biên bản sự vụ",
    done: "Đã xem trước biên bản sự vụ",
    icon: "Eye",
  },
  draft_case_minutes: {
    running: "Tôi đang soạn thảo biên bản sự vụ",
    done: "Đã soạn thảo biên bản sự vụ",
    icon: "FileEdit",
  },
  request_action_approval: {
    running: "Tôi đang gửi yêu cầu phê duyệt hành động",
    done: "Đã gửi yêu cầu phê duyệt hành động",
    icon: "CheckSquare",
  },
};

export const DEFAULT_TOOL_LABEL: ToolLabelInfo = {
  running: "Tôi đang xử lý yêu cầu",
  done: "Đã xử lý yêu cầu",
  icon: "Wrench",
};

export function getToolLabel(toolId: string): ToolLabelInfo {
  return TOOL_LABELS[toolId] ?? DEFAULT_TOOL_LABEL;
}
