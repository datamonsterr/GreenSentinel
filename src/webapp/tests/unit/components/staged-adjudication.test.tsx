import React from "react";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";

// Exercise the real workspace, tabs, data adapters and HTTP client. Only HTTP is
// replaced: jsdom uses MapLibreView's real, accessible no-WebGL fallback.
const caseId = "23600000-0000-4000-8000-000000000001";
const analystId = "23600000-0000-4000-8000-000000000002";
const judgmentId = "23600000-0000-4000-8000-000000000003";
const casePath = `/api/v1/cases/${caseId}`;
const summary = "Xe dừng 210 giây tại điểm đón; khách gửi một tin nhắn.";
const transcript = "Tôi đang chờ tại cửa số 2.";
const caseItem = {
  id: caseId, driver_name: "Driver 236", vehicle_plate: "30A-00236",
  priority: "P1", priority_score: 80, status: "in_review", version: 3,
  category: "ERR-02", confidence: 0.92,
};
const committed = {
  id: judgmentId, case_id: caseId, analyst_id: analystId,
  judgment: "Nghi ngờ vi phạm", note: "", created_at: "2026-10-14T03:00:00Z",
  ai_suggestion: { category: "ERR-02", confidence: 0.92 }, delta: "match",
};
const dossier = {
  case_id: caseId, driver_id: "driver-236", driver_name: "Driver 236",
  dispute_status: "in_dispute", driver_statement: "Đường đang tắc.",
  claim_type: "traffic_gridlock", recommended_action: "Auto-Dismiss",
  transcript: [], matching_factors: ["Same corridor"],
  matched_precedent: {
    precedent_id: "precedent-236", precedent_case_id: "prior-case-236",
    title: "Precedent 236: corridor closure", similarity_score: 0.94,
    matching_factors: ["Same corridor"], recommended_procedure: [],
    precedent_verdict: "exonerated", confidence_rationale: "Road closure recorded",
    model_used: "jev",
  },
};

let judgment: typeof committed | null;
let saveResponse: () => Promise<Response>;
let writes: Array<{ path: string; body: Record<string, unknown> }>;
let unexpectedRequests: string[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
function detail() {
  return {
    case: caseItem, assessment: {
      id: "assessment-236", category: "ERR-02", confidence: 0.92,
      reason_codes: ["stationary_duration_over_180s"], forensic_brief: summary,
    },
    active_lease: { analyst_id: analystId, expires_at: "2099-01-01T00:00:00Z" },
    preliminary_judgment: judgment,
    forensic_brief: { case_id: caseId, summary_text: summary },
    trip: { id: "trip-236", driver_name: "Driver 236", status: "cancelled",
      pickup_address: "Cửa số 2", dropoff_address: "Ga Hà Nội" },
    telemetry_samples: [{ recorded_at: "2026-10-14T02:00:00Z",
      position: { type: "Point", coordinates: [105.8, 21.02] }, speed_mps: 0 }],
    conversation: [{ id: "msg-236", role: "customer", text: transcript,
      occurred_at: "2026-10-14T02:00:00Z" }],
  };
}

beforeEach(() => {
  judgment = null;
  writes = [];
  unexpectedRequests = [];
  saveResponse = async () => { judgment = { ...committed }; return json(judgment); };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (init?.method === "POST") {
      writes.push({ path, body: JSON.parse(String(init.body)) });
      if (path === `${casePath}/preliminary-assessment`) return saveResponse();
      if (path === `${casePath}/adjudicate`) return json({ case_id: caseId, status: "dismissed", version: 4 });
    }
    if (path === "/api/v1/me") return json({ id: analystId, display_name: "Analyst 236", roles: ["analyst"] });
    if (path === "/api/v1/cases") return json({ items: [caseItem], total: 1, limit: 50, offset: 0 });
    if (path === casePath) return json(detail());
    if (path === `${casePath}/agent-session`) return json({ session_id: "session-236", messages: [] });
    if (path === `${casePath}/agent-context`) return json({ prompt_tokens: 100, completion_tokens: 50, total_tokens: 150, context_window: 10000, breakdown: { system: 30, dossier: 40, history: 30, tool_results: 30, query: 20 }, turn_count: 1 });
    if (path === `${casePath}/dispute-dossier`) return json(dossier);
    if (path === `${casePath}/workflow-trace`) return json(null);
    if (path === `${casePath}/driver-scorecard`) return json({ driver_id: "driver-236", past_incidents: [] });
    if (path === `${casePath}/stream`) return new Response("", { headers: { "Content-Type": "text/event-stream" } });
    unexpectedRequests.push(`${init?.method || "GET"} ${path}`);
    return json({ detail: "Unconfigured test HTTP route" }, 500);
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  expect(unexpectedRequests).toEqual([]);
});

async function openWorkspace() {
  const view = render(<CockpitWorkspaceView />);
  await screen.findByRole("button", { name: "Release" });
  // The center wrapper unhides after the detail load settles; allow a beat
  // under parallel workers before asserting visibility.
  await waitFor(() => expect(within(screen.getByLabelText("Forensic Brief")).getByText(summary)).toBeVisible());
  return view;
}
function gate() {
  return screen.getByRole("radiogroup", { name: /phán đoán|judgment/i });
}
function commitButton() {
  return screen.getByRole("button", { name: /Save judgment & view AI|Saving/ });
}
async function openJudgment(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: "Complete" }));
  await user.click(screen.getByRole("button", { name: "View AI results" }));
}
async function chooseJudgment(user: ReturnType<typeof userEvent.setup>) {
  await openJudgment(user);
  await user.click(within(gate()).getByLabelText("Suspected fraud"));
  await user.click(commitButton());
}
function assertOverviewConclusionMasked() {
  // A masked placeholder may retain the section shell. The conclusion itself
  // must not expose category, probability or detection rationale to the DOM.
  for (const label of [
    "Mã danh mục phân loại vi phạm do AI Agent gán",
    "Loại hành vi vi phạm do AI Agent phát hiện",
    "Xác suất nghi vấn vi phạm do AI Agent ước tính (0 - 100%)",
    "Lý do đối soát chi tiết do hệ thống Agent phân tích",
  ]) {
    expect.soft(screen.queryByLabelText(label)).not.toBeInTheDocument();
  }
}
function assertMasked() {
  expect(screen.queryByLabelText(/^AI advice:/)).not.toBeInTheDocument();
  assertOverviewConclusionMasked();
  expect(screen.queryAllByText("ERR-02 (92%)")).toHaveLength(0);
  expect(screen.queryByText(/Rec: Auto-Dismiss/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Jev AI Precedent Match")).not.toBeInTheDocument();
}

describe("#236 independent analyst judgment at workspace boundary", () => {
  it("masks queue/header category and confidence before the claimed case judgment", async () => {
    await openWorkspace();
    expect.soft(screen.queryByLabelText(/^AI advice:/)).not.toBeInTheDocument();
    expect(screen.queryAllByText("ERR-02 (92%)")).toHaveLength(0);
  });

  it("masks overview classification, probability and detection reason", async () => {
    await openWorkspace();
    assertOverviewConclusionMasked();
  });

  it("masks recommended action and precedent while conversation remains readable", async () => {
    const user = userEvent.setup();
    await openWorkspace();
    await user.click(screen.getByRole("tab", { name: "Customer" }));
    expect(screen.getByText(transcript)).toBeVisible();
    expect.soft(screen.queryByText(/Rec: Auto-Dismiss/)).not.toBeInTheDocument();
    expect.soft(screen.queryByLabelText("Jev AI Precedent Match")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Áp dụng quy trình án lệ" })).not.toBeInTheDocument();
  });

  it("keeps objective summary, map, sensor evidence, telemetry and conversation usable (regression control)", async () => {
    const user = userEvent.setup();
    await openWorkspace();
    expect(within(screen.getByLabelText("Forensic Brief")).getByText(summary)).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Maps" }));
    expect(screen.getByTestId("maplibre-view")).toBeVisible();
    expect(screen.getByLabelText("Platform and Sensor Reliability")).toBeVisible();
    const telemetry = screen.getByLabelText("Stall and Drift Telemetry");
    await user.click(within(telemetry).getByRole("button"));
    expect(within(telemetry).getByRole("button")).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("tab", { name: "Customer" }));
    expect(screen.getByText(transcript)).toBeVisible();
  });

  it("reload without persisted judgment stays masked", async () => {
    const first = await openWorkspace();
    first.unmount();
    await openWorkspace();
    assertMasked();
  });

  it("offers three named choices and optional note; keyboard selection commits once", async () => {
    const user = userEvent.setup();
    await openWorkspace();
    await openJudgment(user);
    const choices = within(gate());
    const suspected = choices.getByLabelText("Suspected fraud");
    expect(choices.getByLabelText("No fraud / force majeure")).toBeEnabled();
    expect(choices.getByLabelText("Insufficient evidence")).toBeEnabled();
    expect(commitButton()).toBeDisabled();
    suspected.focus();
    expect(suspected).toHaveFocus();
    await user.keyboard(" ");
    expect(commitButton()).toBeEnabled();
    commitButton().focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(writes.filter(w => w.path.endsWith("/preliminary-assessment"))).toHaveLength(1));
    expect(writes[0].body).toMatchObject({ analyst_id: analystId, judgment: "Nghi ngờ vi phạm" });
    expect(writes.some(w => w.path.endsWith("/adjudicate"))).toBe(false);
  });

  it("reveals conclusion and counterargument immediately after acknowledged commit", async () => {
    const user = userEvent.setup();
    await openWorkspace();
    await chooseJudgment(user);
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    expect(await screen.findByLabelText("AI advice: ERR-02, 92% confidence")).toBeVisible();
    expect(screen.getByRole("region", { name: /phản biện|counterargument/i })).toBeVisible();
    for (const name of ["Overview", "Maps", "Customer", "Driver"]) {
      // The copilot panel also renders a "Driver" tab; scope the center
      // workspace tab to its own tablist.
      const tab = name === "Driver"
        ? within(screen.getByRole("tablist", { name: "Case views" })).getByRole("tab", { name })
        : screen.getByRole("tab", { name });
      await user.click(tab);
      assertMasked();
    }
  });

  it("persisted judgment restores the revealed conclusion and counterargument on reload", async () => {
    judgment = { ...committed };
    const user = userEvent.setup();
    await openWorkspace();
    assertMasked();
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    expect(screen.queryByRole("button", { name: "View AI results" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("AI advice: ERR-02, 92% confidence")).toBeVisible();
    expect(screen.getByRole("region", { name: /phản biện|counterargument/i })).toBeVisible();
  });

  it("shows the persisted independent judgment and note in Complete", async () => {
    judgment = { ...committed, note: "Reviewed against archived evidence." };
    const user = userEvent.setup();
    await openWorkspace();
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    const record = screen.getByRole("region", { name: "Independent judgment" });
    expect(record).toHaveTextContent("Independent judgment");
    expect(record).toHaveTextContent("Suspected fraud");
    expect(record).toHaveTextContent("Reviewed against archived evidence.");
  });

  it("pending save cannot reveal AI or double commit", async () => {
    let finish!: (response: Response) => void;
    saveResponse = () => new Promise<Response>(resolve => { finish = resolve; });
    const user = userEvent.setup();
    await openWorkspace();
    await chooseJudgment(user);
    await waitFor(() => expect(writes).toHaveLength(1));
    assertMasked();
    expect(commitButton()).toBeDisabled();
    await user.click(commitButton());
    expect(writes).toHaveLength(1);
    await act(async () => { judgment = { ...committed }; finish(json(judgment)); });
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    expect(await screen.findByLabelText("AI advice: ERR-02, 92% confidence")).toBeVisible();
  });

  it("failed persistence keeps AI masked and presents a retryable error", async () => {
    saveResponse = async () => json({ detail: "Judgment store unavailable" }, 503);
    const user = userEvent.setup();
    await openWorkspace();
    await chooseJudgment(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Judgment store unavailable|503/);
    assertMasked();
    expect(commitButton()).toBeEnabled();
  });

  it.each([
    ["Dismiss", "DISAGREE"],
    ["Approve conclusion", "AGREE"],
  ])("signed %s persists preliminary judgment reference and rationale", async (action, outcome) => {
    judgment = { ...committed };
    const user = userEvent.setup();
    await openWorkspace();
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    const rationale = screen.getByRole("textbox", { name: "Decision rationale" });
    await user.clear(rationale);
    await user.type(rationale, "123456789");
    expect(screen.getByRole("button", { name: action })).toBeDisabled();
    await user.type(rationale, "0");
    await user.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(writes.some(w => w.path.endsWith("/adjudicate"))).toBe(true));
    expect(writes.find(w => w.path.endsWith("/adjudicate"))?.body).toMatchObject({
      analyst_id: analystId, rationale: "1234567890", preliminary_judgment_id: judgmentId,
      outcome,
    });
  });
});

describe("persisted staged wire contract", () => {
  it.each(["ERR-02", "no_violation"])("computes delta for %s from a record without AI metadata", async category => {
    const sourceFetch = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await sourceFetch(input, init);
      if ((!init?.method || init.method === "GET") && new URL(String(input), "http://localhost").pathname === casePath) {
        return json({ ...detail(), assessment: { ...detail().assessment, category } });
      }
      return response;
    }));
    saveResponse = async () => json({
      id: judgmentId, case_id: caseId, analyst_id: analystId,
      judgment: "Nghi ngờ vi phạm", note: null, created_at: committed.created_at,
    });
    const user = userEvent.setup();
    await openWorkspace();
    await chooseJudgment(user);
    await user.click(screen.getByRole("tab", { name: "Complete" }));
    const panel = await screen.findByRole("region", { name: /phản biện|counterargument/i });
    expect(panel).toHaveTextContent(category === "ERR-02" ? /matches ai recommendation|trùng khớp với khuyến nghị ai/i : /differs from ai recommendation|khác biệt với khuyến nghị ai/i);
  });
});
