import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import { getToolLabel } from "@/lib/copilot/tool-labels";

const REQUIRED_TOOL_IDS = [
  "adjudicate_case",
  "check_related_cases_to_vehicle",
  "check_traffic_situation",
  "check_weather_condition",
  "claim_case",
  "fetch_corridor_historical_traffic",
  "geocode_address",
  "get_audit_log",
  "get_case_context",
  "get_driver_history",
  "inspect_trip_telemetry",
  "list_cases",
  "match_trip_telemetry",
  "query_cases_db",
  "query_traffic_incident_feed",
  "record_case_action",
  "reverse_geocode_coordinates",
  "search_policy_documents",
  "submit_driver_statement",
  "trigger_simulation",
  "verify_exoneration_rules",
  "write_ticket_for_driver",
  "get_case_detail",
  "get_driver_card",
  "get_forensic_brief",
  "get_case_policy",
  "query_policy",
  "check_driver_suspension",
  "corroborate_traffic_conditions",
  "get_driver_dispute_context",
  "query_driver_policy",
  "ask_interactive_question",
  "preview_case_minutes",
  "draft_case_minutes",
  "request_action_approval",
];

describe("tool-labels (copilot tool activity labels)", () => {
  it("reads tool_catalog.py and asserts every canonical id has a label", () => {
    const candidatePaths = [
      path.resolve(process.cwd(), "../../src/services/tool_catalog.py"),
      path.resolve(__dirname, "../../../../../src/services/tool_catalog.py"),
      path.resolve("../../src/services/tool_catalog.py"),
    ];
    const catalogPath = candidatePaths.find((p) => fs.existsSync(p));
    expect(catalogPath, "tool_catalog.py must be found at ../../src/services/tool_catalog.py").toBeDefined();

    const catalogContent = fs.readFileSync(catalogPath!, "utf-8");
    const canonicalIdMatches = [
      ...catalogContent.matchAll(/canonical_id=["']([^"']+)["']/g),
    ].map((m) => m[1]);

    expect(canonicalIdMatches.length).toBeGreaterThan(0);

    for (const canonicalId of canonicalIdMatches) {
      const labelInfo = getToolLabel(canonicalId);
      expect(labelInfo, `Missing label for canonical_id: ${canonicalId}`).toBeDefined();
      expect(labelInfo.running).toMatch(/^Tôi đang /);
      expect(labelInfo.done).toMatch(/^Đã /);
      expect(typeof labelInfo.icon).toBe("string");
      expect(labelInfo.icon.length).toBeGreaterThan(0);
    }
  });

  it("contains all required tools from task specification", () => {
    for (const toolId of REQUIRED_TOOL_IDS) {
      const label = getToolLabel(toolId);
      expect(label.running).toMatch(/^Tôi đang /);
      expect(label.done).toMatch(/^Đã /);
      expect(typeof label.icon).toBe("string");
      expect(label.icon.length).toBeGreaterThan(0);
    }
  });

  it("matches the exact get_forensic_brief example", () => {
    const label = getToolLabel("get_forensic_brief");
    expect(label.running).toBe("Tôi đang tóm tắt vụ việc");
    expect(label.done).toBe("Đã tóm tắt vụ việc");
    expect(typeof label.icon).toBe("string");
  });

  it("falls back gracefully for unknown tools", () => {
    const unknown = getToolLabel("completely_unknown_operation");
    expect(unknown.running).toBe("Tôi đang xử lý yêu cầu");
    expect(unknown.done).toBe("Đã xử lý yêu cầu");
    expect(typeof unknown.icon).toBe("string");
  });
});
