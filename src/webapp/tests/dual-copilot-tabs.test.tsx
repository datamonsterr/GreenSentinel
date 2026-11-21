import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import * as api from "@/lib/api-client";
import type {
  AgentSessionResponse,
  CaseDetailResponse,
  CaseProgressEvent,
  DisputeDossierResponse,
  FraudCaseSummary,
} from "@/types/schemas";

// Only the HTTP/SSE boundary and the WebGL adapter are replaced. Both chat UIs
// remain real; assertions exercise rendering and user actions, not mock results.
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: () => <div data-testid="mock-maplibre-view" />,
}));
vi.mock("@/lib/api-client", () => ({
  fetchCases: vi.fn(),
  fetchCaseHistory: vi.fn(),
  fetchCaseDetail: vi.fn(),
  fetchForensicBrief: vi.fn(),
  fetchCasePolicy: vi.fn(),
  fetchCurrentAnalyst: vi.fn(),
  fetchAgentSession: vi.fn(),
  claimCase: vi.fn(),
  releaseCase: vi.fn(),
  adjudicateCase: vi.fn(),
  recordCaseAction: vi.fn(),
  subscribeCaseStream: vi.fn(),
  streamPolicyChat: vi.fn(),
  delegateAnalystInquiry: vi.fn(),
  getDisputeDossier: vi.fn(),
  getCaseWorkflowTrace: vi.fn(),
  applyPrecedentProcedure: vi.fn(),
  getApiBaseUrl: vi.fn(() => ""),
  authorizedHeaders: vi.fn(async () => ({ "Content-Type": "application/json" })),
}));

vi.mock("@/lib/copilot/context-api", () => ({
  getAgentContext: vi.fn().mockResolvedValue({
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    context_window: 10000,
    breakdown: { system: 30, dossier: 40, history: 30, tool_results: 30, query: 20 },
    turn_count: 1,
  }),
  clearAgentContext: vi.fn().mockResolvedValue({ deleted_turns: 1, deleted_messages: 1 }),
}));

const caseItem: FraudCaseSummary = {
  id: "case-193",
  driver_id: "driver-193",
  driver_name: "Nguyễn Văn An",
  vehicle_plate: "30A-19300",
  priority: "P1",
  priority_score: 1,
  status: "ready",
  version: 4,
};
const caseDetail: CaseDetailResponse = {
  case: caseItem,
  trip: {
    driver_statement: "Đường đến điểm đón đang tắc.",
    passenger_statement: "Tôi chờ ở cổng chính.",
  },
  conversation: [
    { role: "customer", text: "Anh đón tôi ở cổng số 2 nhé.", occurred_at: "2026-10-14T01:00:00Z" },
    { role: "driver", text: "Tôi sẽ đến cổng số 2 sau 3 phút.", occurred_at: "2026-10-14T01:00:10Z" },
  ],
  active_lease: {
    analyst_id: "analyst-193",
    expires_at: "2099-01-01T00:00:00Z",
  },
};
const dossier: DisputeDossierResponse = {
  case_id: "case-193",
  driver_id: "driver-193",
  driver_name: "Nguyễn Văn An",
  dispute_status: "in_dispute",
  driver_statement: "Đường đến điểm đón đang tắc.",
  claim_type: "traffic_gridlock",
  traffic_corroboration: {},
  precedent_score: 0,
  recommended_action: "Review",
  transcript: [
    { turn_id: "relay-driver-1", role: "driver", text: "Tôi đang gửi ảnh hiện trường cho GSupport.", timestamp: "2026-10-14T01:01:00Z" },
    { turn_id: "relay-agent-1", role: "agent", text: "GSupport đã nhận ảnh, vui lòng giữ liên lạc.", timestamp: "2026-10-14T01:01:10Z" },
  ],
};
const agentSession: AgentSessionResponse = {
  session_id: "copilot-session-193",
  messages: [
    { id: "copilot-question", turn_id: "copilot-turn-1", role: "user", content: "Review the pickup evidence internally.", created_at: "2026-10-14T01:02:00Z" },
    { id: "copilot-answer", turn_id: "copilot-turn-1", role: "assistant", content: "Internal policy draft: compare the GIS route with clause 5.2.", created_at: "2026-10-14T01:02:01Z" },
  ],
};

// The issue supplies Vietnamese labels without accents. Accept the same literal
// wording with Vietnamese diacritics, without accepting synonyms or extra text.
function normalizeVietnameseLabel(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/g, "d").replace(/Đ/g, "D").replace(/\s+/g, " ").trim();
}

function renderCustomerConversation(detail = caseDetail) {
  render(<ConversationTab caseDetail={detail} disputeDossier={dossier} activeCaseDriverName="Nguyễn Văn An" />);
  return within(screen.getByRole("region", { name: "Driver–customer conversation" }));
}

async function renderWorkspace() {
  render(<CockpitWorkspaceView />);
  // Existing, observable readiness checks prevent loading failures from being
  // mistaken for the missing drawer-tab behavior.
  await screen.findByRole("tab", { name: "Customer" });
  await screen.findByText("Internal policy draft: compare the GIS route with clause 5.2.");
}

// The center workspace also renders a "Driver" tab, so drawer tabs are
// scoped to the copilot panel's own tablist.
function agentTabs() {
  return within(screen.getByRole("tablist", { name: "Agent panels" }));
}

async function openDriverRelay(user: ReturnType<typeof userEvent.setup>) {
  await renderWorkspace();
  await user.click(agentTabs().getByRole("tab", { name: "Driver" }));
  return within(screen.getByRole("tabpanel", { name: "Driver" }));
}

function withAnalystTurn(instruction: string): DisputeDossierResponse {
  return {
    ...dossier,
    transcript: [
      ...dossier.transcript,
      { turn_id: "relay-analyst-1", role: "analyst", sender: "analyst", text: instruction, timestamp: "2026-10-14T01:03:00Z" },
    ],
  };
}

function configureSecondCase() {
  const secondCase = { ...caseItem, id: "case-194", driver_id: "driver-194", driver_name: "Lê Văn Bình" };
  const secondDossier = { ...dossier, case_id: "case-194", driver_id: "driver-194", transcript: [{ turn_id: "second-driver", role: "driver", text: "Hội thoại riêng của hồ sơ thứ hai." }] };
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [caseItem, secondCase], total: 2, limit: 50, offset: 0 });
  vi.mocked(api.fetchCaseDetail).mockImplementation(async (id) => id === "case-194" ? { ...caseDetail, case: secondCase } : caseDetail);
  vi.mocked(api.getDisputeDossier).mockImplementation(async (id) => id === "case-194" ? secondDossier : dossier);
  return { secondDossier };
}

async function selectQueuedCase(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(within(screen.getByRole("region", { name: "Triage queue" })).getByRole("button", { name: new RegExp(name) }));
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [caseItem], total: 1, limit: 50, offset: 0 });
  vi.mocked(api.fetchCaseHistory).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  vi.mocked(api.fetchCaseDetail).mockResolvedValue(caseDetail);
  vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: "analyst-193", name: "Analyst 193", role: "analyst", roles: ["analyst"] });
  vi.mocked(api.fetchAgentSession).mockResolvedValue(agentSession);
  vi.mocked(api.fetchForensicBrief).mockResolvedValue({ case_id: "case-193", generated_at: "2026-10-14T01:02:00Z", abnormalities: [], abnormality_count: 0, evidence_sources: [], summary_text: "" });
  vi.mocked(api.getDisputeDossier).mockResolvedValue(dossier);
  vi.mocked(api.getCaseWorkflowTrace).mockRejectedValue(new Error("No workflow trace for this case"));
  vi.mocked(api.subscribeCaseStream).mockImplementation(() => () => {});
  vi.mocked(api.streamPolicyChat).mockImplementation(() => () => {});
  vi.mocked(api.delegateAnalystInquiry).mockResolvedValue({ status: "inquiry_delegated", case_id: "case-193" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("#193 read-only customer conversation", () => {
  it("preserves verbatim driver and customer turns", () => {
    const conversation = renderCustomerConversation();
    const feed = within(conversation.getByTestId("conversation-chat-feed"));
    expect(feed.getByText("Anh đón tôi ở cổng số 2 nhé.")).toBeVisible();
    expect(feed.getByText("Tôi sẽ đến cổng số 2 sau 3 phút.")).toBeVisible();
  });

  it("removes the customer-conversation composer and send action", () => {
    const conversation = renderCustomerConversation();
    expect(conversation.queryByRole("textbox")).not.toBeInTheDocument();
    expect(conversation.queryByTestId("conversation-chat-input")).not.toBeInTheDocument();
    expect(conversation.queryByRole("button", { name: /Gửi|Send/i })).not.toBeInTheDocument();
    expect(api.delegateAnalystInquiry).not.toHaveBeenCalled();
  });

  it("summarizes only the two trip customer interactions in the header badge", () => {
    const conversation = renderCustomerConversation();
    expect(conversation.getByText("2 turns")).toBeVisible();
    const summary = conversation.getByRole("status", { name: "Conversation summary" });
    expect(summary).toHaveTextContent("Driver: 1 · Customer: 1");
    expect(summary).toHaveTextContent("Latest (Driver): Tôi sẽ đến cổng số 2 sau 3 phút.");
    expect(summary).not.toHaveTextContent("GSupport");
    expect(conversation.queryByText("Live Conversation Chat")).not.toBeInTheDocument();
  });

  it("keeps GSupport relay turns out of the customer evidence feed", () => {
    const conversation = renderCustomerConversation();
    const feed = within(conversation.getByTestId("conversation-chat-feed"));
    expect(feed.queryByText("Tôi đang gửi ảnh hiện trường cho GSupport.")).not.toBeInTheDocument();
    expect(feed.queryByText("GSupport đã nhận ảnh, vui lòng giữ liên lạc.")).not.toBeInTheDocument();
  });

  it.each([
    { label: "empty", conversation: [] },
    { label: "null", conversation: null },
    { label: "missing", conversation: undefined },
  ])("renders the specified empty state for $label customer history despite a populated relay", ({ conversation }) => {
    // Null is a supported runtime edge case in the DoD, even though the current
    // TypeScript response only permits an array or an omitted property.
    const detail = { ...caseDetail, conversation } as unknown as CaseDetailResponse;
    const customerConversation = renderCustomerConversation(detail);
    expect(customerConversation.getByText("No driver/customer conversation recorded.")).toBeVisible();
    expect(customerConversation.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

describe("#193 dual-tab copilot drawer", () => {
  it("opens AI Copilot by default with two accessible drawer tabs", async () => {
    await renderWorkspace();
    const copilotTab = screen.getByRole("tab", { name: "Analyst Copilot" });
    const relayTab = agentTabs().getByRole("tab", { name: "Driver" });
    expect(copilotTab).toHaveTextContent("Analyst Copilot");
    expect(relayTab).toHaveTextContent("Driver");
    const panel = screen.getByRole("tabpanel", { name: "Analyst Copilot" });
    expect(copilotTab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", copilotTab.id);
    const relayPanel = document.getElementById(relayTab.getAttribute("aria-controls") || "");
    expect(relayPanel).toHaveAttribute("aria-labelledby", relayTab.id);
    expect(copilotTab).toHaveAttribute("aria-selected", "true");
    expect(relayTab).toHaveAttribute("aria-selected", "false");
    const copilot = within(screen.getByRole("tabpanel", { name: "Analyst Copilot" }));
    expect(copilot.getByText("Internal policy draft: compare the GIS route with clause 5.2.")).toBeVisible();
    expect(copilot.getByRole("textbox")).toBeEnabled();
    expect(copilot.queryByText("GSupport đã nhận ảnh, vui lòng giữ liên lạc.")).not.toBeInTheDocument();
  });

  it("switches to live GSupport history and preserves the internal copilot draft", async () => {
    const user = userEvent.setup();
    await renderWorkspace();
    const copilot = within(screen.getByRole("tabpanel", { name: "Analyst Copilot" }));
    await user.type(copilot.getByRole("textbox"), "Inspect the GIS route internally");
    await user.click(agentTabs().getByRole("tab", { name: "Driver" }));
    const relay = within(screen.getByRole("tabpanel", { name: "Driver" }));
    expect(agentTabs().getByRole("tab", { name: "Driver" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Analyst Copilot" })).toHaveAttribute("aria-selected", "false");
    expect(relay.getByText("Tôi đang gửi ảnh hiện trường cho GSupport.")).toBeVisible();
    expect(relay.getByText("GSupport đã nhận ảnh, vui lòng giữ liên lạc.")).toBeVisible();
    expect(relay.getByRole("textbox")).toHaveValue("");
    expect(relay.queryByText("Internal policy draft: compare the GIS route with clause 5.2.")).not.toBeInTheDocument();
    expect(relay.queryByText("Anh đón tôi ở cổng số 2 nhé.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Analyst Copilot" }));
    const restored = within(screen.getByRole("tabpanel", { name: "Analyst Copilot" }));
    expect(restored.getByRole("textbox")).toHaveValue("Inspect the GIS route internally");
    expect(restored.getByText("Review the pickup evidence internally.")).toBeVisible();
  });

  it("keeps RAG tool output and internal drafts in AI Copilot without contacting the driver", async () => {
    const user = userEvent.setup();
    await renderWorkspace();
    const copilot = within(screen.getByRole("tabpanel", { name: "Analyst Copilot" }));
    await user.type(copilot.getByRole("textbox"), "Draft a question from GIS and policy evidence");

    const sseChunks = [
      'event: tool.start\ndata: {"tool_call_id": "call-1", "tool_name": "search_policy"}\n\n',
      'event: tool.end\ndata: {"tool_call_id": "call-1", "status": "completed"}\n\n',
      'event: tool.start\ndata: {"tool_call_id": "call-2", "tool_name": "get_telemetry_trace"}\n\n',
      'event: tool.end\ndata: {"tool_call_id": "call-2", "status": "completed"}\n\n',
      'event: text.delta\ndata: {"delta": "Draft for analyst review: ask for the pickup photo."}\n\n',
      'event: run.completed\ndata: {}\n\n',
    ].join("");

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(sseChunks));
            controller.close();
          },
        })
      )
    );

    await user.click(copilot.getByRole("button", { name: /Send message|Gửi/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/policy/chat/stream"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"query":"Draft a question from GIS and policy evidence"'),
        })
      );
    });

    expect(await copilot.findByText("Đã dùng 2 công cụ")).toBeVisible();
    await user.click(copilot.getByText("Đã dùng 2 công cụ"));
    expect(await copilot.findByText("Đã tra cứu quy định")).toBeVisible();
    expect(await copilot.findByText("Đã lấy lộ trình viễn thông")).toBeVisible();
    expect(await copilot.findByText("Draft for analyst review: ask for the pickup photo.")).toBeVisible();
    expect(api.delegateAnalystInquiry).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("isolates mixed dossier history, renders canonical driver turns and deduplicates echoes", async () => {
    const error = vi.spyOn(console, "error");
    vi.mocked(api.getDisputeDossier).mockResolvedValue({
      ...dossier,
      transcript: [
        ...dossier.transcript,
        dossier.transcript[0],
        { id: "canonical-driver", turn_id: "shared-turn", role: "driver_agent", content: "Trả lời từ phiên tài xế.", created_at: "2026-10-14T03:45:00Z" },
        { id: "canonical-analyst", turn_id: "shared-turn", role: "analyst", content: "Xin bổ sung chứng từ." },
        { id: "internal-user", role: "user", sender: "analyst", content: "Private analyst policy question" },
        { id: "internal-assistant", role: "assistant", content: "Private copilot reasoning" },
      ],
    });
    const relay = await openDriverRelay(userEvent.setup());
    expect(relay.getByText("Trả lời từ phiên tài xế.")).toBeVisible();
    expect(relay.getByText("Trả lời từ phiên tài xế.")).toHaveClass("border-gs-line-2");
    const time = new Date("2026-10-14T03:45:00Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    expect(relay.getByText(`• ${time}`)).toBeVisible();
    expect(relay.getByText("Xin bổ sung chứng từ.")).toBeVisible();
    expect(relay.getAllByText("Tôi đang gửi ảnh hiện trường cho GSupport.")).toHaveLength(1);
    expect(relay.queryByText("Private analyst policy question")).not.toBeInTheDocument();
    expect(relay.queryByText("Private copilot reasoning")).not.toBeInTheDocument();
    expect(error.mock.calls.flat().join(" ")).not.toMatch(/same key/);
  });

  it("switches linked drawer panels with arrow keys", async () => {
    const user = userEvent.setup();
    await renderWorkspace();
    screen.getByRole("tab", { name: "Analyst Copilot" }).focus();
    await user.keyboard("{ArrowRight}");
    const relayTab = agentTabs().getByRole("tab", { name: "Driver" });
    expect(relayTab).toHaveFocus();
    expect(relayTab).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "Driver" });
    expect(relayTab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", relayTab.id);
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Analyst Copilot" })).toHaveFocus();
  });

  it("sends a relay inquiry through delegateAnalystInquiry with the current analyst identity", async () => {
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    vi.mocked(api.getDisputeDossier).mockResolvedValue(withAnalystTurn("Vui lòng gửi ảnh điểm đón."));
    await user.type(relay.getByRole("textbox"), "  Vui lòng gửi ảnh điểm đón.  ");
    await user.click(relay.getByRole("button", { name: /Gửi|Send/i }));
    await waitFor(() => expect(api.delegateAnalystInquiry).toHaveBeenCalledExactlyOnceWith("case-193", expect.objectContaining({
      case_id: "case-193", analyst_id: "analyst-193", instruction: "Vui lòng gửi ảnh điểm đón.",
    })));
    await waitFor(() => expect(relay.getByRole("textbox")).toHaveValue(""));
    expect(await relay.findByText("[Chuyen vien Tham dinh]", { normalizer: normalizeVietnameseLabel })).toBeVisible();
    expect(relay.getAllByText("Vui lòng gửi ảnh điểm đón.")).toHaveLength(1);
    expect(api.streamPolicyChat).not.toHaveBeenCalled();
  });

  it("labels persisted sender=analyst turns with the analyst badge", async () => {
    vi.mocked(api.getDisputeDossier).mockResolvedValue({
      ...dossier,
      transcript: [...dossier.transcript, {
        turn_id: "persisted-analyst-turn", role: "agent", sender: "analyst",
        text: "Xin xác nhận thời gian dừng xe.", timestamp: "2026-10-14T01:03:00Z",
      }],
    });
    const relay = await openDriverRelay(userEvent.setup());
    expect(relay.getByText("Xin xác nhận thời gian dừng xe.")).toBeVisible();
    expect(relay.getByText("[Chuyen vien Tham dinh]", { normalizer: normalizeVietnameseLabel })).toBeVisible();
  });

  it("refreshes live driver replies on a case stream update without duplicating echoed turns", async () => {
    const relay = await openDriverRelay(userEvent.setup());
    vi.mocked(api.getDisputeDossier).mockResolvedValue({
      ...dossier,
      transcript: [...dossier.transcript, { turn_id: "relay-driver-2", role: "driver", text: "Ảnh điểm đón đã được gửi.", timestamp: "2026-10-14T01:04:00Z" }],
    });
    const onEvent = vi.mocked(api.subscribeCaseStream).mock.calls[0][1];
    const update: CaseProgressEvent = { case_id: "case-193", status: "evidence_requested", progress: 100, message: "Driver reply received", timestamp: "2026-10-14T01:04:00Z" };
    await act(async () => { onEvent(update); });
    expect(await relay.findByText("Ảnh điểm đón đã được gửi.")).toBeVisible();
    await act(async () => { onEvent(update); });
    await waitFor(() => expect(api.getDisputeDossier).toHaveBeenCalledTimes(3));
    expect(relay.getAllByText("Ảnh điểm đón đã được gửi.")).toHaveLength(1);
  });

  it("polls driver replies every 10 seconds after the finite case stream closes, without echoes", async () => {
    await renderWorkspace();
    expect(api.getDisputeDossier).toHaveBeenCalledTimes(1);
    vi.useFakeTimers();
    fireEvent.click(agentTabs().getByRole("tab", { name: "Driver" }));
    const relay = within(screen.getByRole("tabpanel", { name: "Driver" }));
    const reply = { turn_id: "polled-driver-turn", role: "driver", text: "Vé cầu đường đã gửi." };
    vi.mocked(api.getDisputeDossier).mockResolvedValue({ ...dossier, transcript: [...dossier.transcript, reply, reply] });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(relay.getByText("Vé cầu đường đã gửi.")).toBeVisible();
    expect(api.getDisputeDossier).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(api.getDisputeDossier).toHaveBeenCalledTimes(3);
    expect(relay.getAllByText("Vé cầu đường đã gửi.")).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: "Analyst Copilot" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(api.getDisputeDossier).toHaveBeenCalledTimes(3);
  });

  it("reuses the inquiry UUID after acceptance with a lost response and renders one turn", async () => {
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    const persisted = new Map<string, DisputeDossierResponse["transcript"][number]>();
    let attempts = 0;
    vi.mocked(api.delegateAnalystInquiry).mockImplementation(async (_caseId, request) => {
      const { turn_id } = request as typeof request & { turn_id: string };
      persisted.set(turn_id, { id: `message-${turn_id}`, turn_id, role: "analyst", text: request.instruction });
      vi.mocked(api.getDisputeDossier).mockResolvedValue({ ...dossier, transcript: [...dossier.transcript, ...persisted.values()] });
      if (++attempts === 1) throw new TypeError("Accepted, then response lost");
      return { status: "inquiry_delegated", case_id: "case-193" };
    });
    await user.type(relay.getByRole("textbox"), "Vui lòng bổ sung biên lai.");
    await user.click(relay.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Accepted, then response lost");
    const onEvent = vi.mocked(api.subscribeCaseStream).mock.calls[0][1];
    await act(async () => { onEvent({ case_id: "case-193", status: "evidence_requested", progress: 100, message: "Accepted", timestamp: "2026-10-14T01:04:00Z" }); });
    expect(relay.getByText("Vui lòng bổ sung biên lai.")).toBeVisible();
    await user.click(relay.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(relay.getByRole("textbox")).toHaveValue(""));
    const first = vi.mocked(api.delegateAnalystInquiry).mock.calls[0][1] as { turn_id?: string };
    const retry = vi.mocked(api.delegateAnalystInquiry).mock.calls[1][1] as { turn_id?: string };
    expect(first.turn_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(retry.turn_id).toBe(first.turn_id);
    expect(persisted.size).toBe(1);
    expect(relay.getAllByText("Vui lòng bổ sung biên lai.")).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("resets pending relay state on case switch and ignores an old send failure", async () => {
    const { secondDossier } = configureSecondCase();
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    let rejectFirst!: (error: Error) => void;
    let resolveSecond!: (result: { status: string; case_id: string }) => void;
    vi.mocked(api.delegateAnalystInquiry)
      .mockReturnValueOnce(new Promise((_resolve, reject) => { rejectFirst = reject; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
    await user.type(relay.getByRole("textbox"), "Yêu cầu hồ sơ thứ nhất.");
    await user.click(relay.getByRole("button", { name: "Gửi" }));
    expect(relay.getByRole("textbox")).toBeDisabled();
    await selectQueuedCase(user, "Lê Văn Bình");
    const nextRelay = within(await screen.findByRole("tabpanel", { name: "Driver" }));
    expect(await nextRelay.findByText("Hội thoại riêng của hồ sơ thứ hai.")).toBeVisible();
    expect(nextRelay.getByRole("textbox")).toBeEnabled();
    expect(nextRelay.getByRole("textbox")).toHaveValue("");
    await user.type(nextRelay.getByRole("textbox"), "Yêu cầu hồ sơ thứ hai.");
    await user.click(nextRelay.getByRole("button", { name: "Gửi" }));
    expect(api.delegateAnalystInquiry).toHaveBeenNthCalledWith(2, "case-194", expect.objectContaining({ case_id: "case-194", instruction: "Yêu cầu hồ sơ thứ hai." }));
    await act(async () => { rejectFirst(new TypeError("Old case send failed")); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(nextRelay.getByRole("textbox")).toHaveValue("Yêu cầu hồ sơ thứ hai.");
    expect(nextRelay.getByRole("button", { name: "Gửi" })).toBeDisabled();
    vi.mocked(api.getDisputeDossier).mockResolvedValue({ ...secondDossier, transcript: [...secondDossier.transcript, { role: "analyst", turn_id: "second-analyst", text: "Yêu cầu hồ sơ thứ hai." }] });
    await act(async () => { resolveSecond({ status: "inquiry_delegated", case_id: "case-194" }); });
    await waitFor(() => expect(nextRelay.getByRole("textbox")).toHaveValue(""));
    expect(nextRelay.getByText("Yêu cầu hồ sơ thứ hai.")).toBeVisible();
    expect(nextRelay.queryByText("Yêu cầu hồ sơ thứ nhất.")).not.toBeInTheDocument();
  });

  it("clears an originating-case retry when another case is selected", async () => {
    configureSecondCase();
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    vi.mocked(api.delegateAnalystInquiry).mockRejectedValueOnce(new TypeError("First case disconnected"));
    await user.type(relay.getByRole("textbox"), "Câu hỏi dành cho hồ sơ thứ nhất.");
    await user.click(relay.getByRole("button", { name: "Gửi" }));
    expect(await relay.findByRole("button", { name: "Thử lại" })).toBeVisible();
    await selectQueuedCase(user, "Lê Văn Bình");
    const nextRelay = within(await screen.findByRole("tabpanel", { name: "Driver" }));
    expect(await nextRelay.findByText("Hội thoại riêng của hồ sơ thứ hai.")).toBeVisible();
    expect(nextRelay.queryByRole("button", { name: "Thử lại" })).not.toBeInTheDocument();
    expect(nextRelay.getByRole("textbox")).toHaveValue("");
    await user.type(nextRelay.getByRole("textbox"), "Câu hỏi mới cho hồ sơ thứ hai.");
    await user.click(nextRelay.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(api.delegateAnalystInquiry).toHaveBeenCalledTimes(2));
    expect(api.delegateAnalystInquiry).toHaveBeenNthCalledWith(2, "case-194", expect.objectContaining({ case_id: "case-194", instruction: "Câu hỏi mới cho hồ sơ thứ hai." }));
    const first = vi.mocked(api.delegateAnalystInquiry).mock.calls[0][1] as { turn_id?: string };
    const second = vi.mocked(api.delegateAnalystInquiry).mock.calls[1][1] as { turn_id?: string };
    expect(first.turn_id).toBeTypeOf("string");
    expect(second.turn_id).not.toBe(first.turn_id);
  });

  it("ignores stale dossier refreshes even after switching away and back to the same case", async () => {
    configureSecondCase();
    const user = userEvent.setup();
    await openDriverRelay(user);
    let resolveStale!: (result: DisputeDossierResponse) => void;
    vi.mocked(api.getDisputeDossier).mockReturnValueOnce(new Promise((resolve) => { resolveStale = resolve; }));
    const onEvent = vi.mocked(api.subscribeCaseStream).mock.calls[0][1];
    await act(async () => { onEvent({ case_id: "case-193", status: "evidence_requested", progress: 100, message: "Old refresh", timestamp: "2026-10-14T01:04:00Z" }); });
    await selectQueuedCase(user, "Lê Văn Bình");
    expect(await screen.findByText("Hội thoại riêng của hồ sơ thứ hai.")).toBeVisible();
    await selectQueuedCase(user, "Nguyễn Văn An");
    expect(await screen.findByText("GSupport đã nhận ảnh, vui lòng giữ liên lạc.")).toBeVisible();
    await act(async () => { resolveStale({ ...dossier, transcript: [{ role: "driver", text: "Stale dossier from previous case generation." }] }); });
    const relay = within(screen.getByRole("tabpanel", { name: "Driver" }));
    expect(relay.queryByText("Stale dossier from previous case generation.")).not.toBeInTheDocument();
    expect(relay.getByText("GSupport đã nhận ảnh, vui lòng giữ liên lạc.")).toBeVisible();
  });

  it("shows a network error toast and retries the same inquiry without duplicating it", async () => {
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    vi.mocked(api.delegateAnalystInquiry).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await user.type(relay.getByRole("textbox"), "Xin gửi lại ảnh hiện trường.");
    await user.click(relay.getByRole("button", { name: /Gửi|Send/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Failed to fetch|network|mạng|kết nối/i);
    expect(api.delegateAnalystInquiry).toHaveBeenCalledTimes(1);
    vi.mocked(api.getDisputeDossier).mockResolvedValue(withAnalystTurn("Xin gửi lại ảnh hiện trường."));
    await user.click(screen.getByRole("button", { name: /Retry|Thử kết nối lại|Thử lại/i }));
    await waitFor(() => expect(api.delegateAnalystInquiry).toHaveBeenCalledTimes(2));
    expect(api.delegateAnalystInquiry).toHaveBeenNthCalledWith(1, "case-193", expect.objectContaining({ analyst_id: "analyst-193", instruction: "Xin gửi lại ảnh hiện trường." }));
    expect(api.delegateAnalystInquiry).toHaveBeenNthCalledWith(2, "case-193", expect.objectContaining({ analyst_id: "analyst-193", instruction: "Xin gửi lại ảnh hiện trường." }));
    await waitFor(() => expect(api.getDisputeDossier).toHaveBeenCalledTimes(2));
    expect(relay.getAllByText("Xin gửi lại ảnh hiện trường.")).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.streamPolicyChat).not.toHaveBeenCalled();
  });

  it("blocks repeated sends while a relay inquiry is pending", async () => {
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    let resolveInquiry!: (result: { status: string; case_id: string }) => void;
    vi.mocked(api.delegateAnalystInquiry).mockReturnValueOnce(new Promise((resolve) => { resolveInquiry = resolve; }));
    vi.mocked(api.getDisputeDossier).mockResolvedValue(withAnalystTurn("Xác nhận vị trí hiện tại."));
    await user.type(relay.getByRole("textbox"), "Xác nhận vị trí hiện tại.");
    const send = relay.getByRole("button", { name: /Gửi|Send/i });
    await user.dblClick(send);
    expect(send).toBeDisabled();
    expect(api.delegateAnalystInquiry).toHaveBeenCalledTimes(1);
    await act(async () => { resolveInquiry({ status: "inquiry_delegated", case_id: "case-193" }); });
    await waitFor(() => expect(api.getDisputeDossier).toHaveBeenCalledTimes(2));
    expect(relay.getAllByText("Xác nhận vị trí hiện tại.")).toHaveLength(1);
  });

  it.each([
    { label: "resolved case", caseStatus: "resolved", disputeStatus: "in_dispute" },
    { label: "closed case", caseStatus: "closed", disputeStatus: "in_dispute" },
    { label: "resolved session", caseStatus: "ready", disputeStatus: "resolved" },
    { label: "closed session", caseStatus: "ready", disputeStatus: "closed" },
  ])("disables relay input and shows the ended-session banner for a $label", async ({ caseStatus, disputeStatus }) => {
    vi.mocked(api.fetchCaseDetail).mockResolvedValue({ ...caseDetail, case: { ...caseItem, status: caseStatus } });
    vi.mocked(api.getDisputeDossier).mockResolvedValue({ ...dossier, dispute_status: disputeStatus });
    const user = userEvent.setup();
    const relay = await openDriverRelay(user);
    expect(relay.getByText("Phien trao doi da ket thuc", { normalizer: normalizeVietnameseLabel })).toBeVisible();
    const input = relay.getByRole("textbox");
    const send = relay.getByRole("button", { name: /Gửi|Send/i });
    expect(input).toBeDisabled();
    expect(send).toBeDisabled();
    await user.type(input, "This inquiry must not be sent");
    await user.click(send);
    expect(input).toHaveValue("");
    expect(api.delegateAnalystInquiry).not.toHaveBeenCalled();
  });
});

describe("#193 existing delegate-inquiry transport contract", () => {
  it("POSTs the raw inquiry to the case endpoint using the real API client", async () => {
    // The UI uses the mocked client above. This contract check loads the real
    // client and mocks fetch, so it does not assert a mocked function's result.
    const realApi = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
    realApi.setApiTokenProvider(null);
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: "inquiry_delegated", case_id: "case-193" }) });
    vi.stubGlobal("fetch", fetchMock);
    await realApi.delegateAnalystInquiry("case-193", { case_id: "case-193", analyst_id: "analyst-193", instruction: "Vui lòng gửi ảnh điểm đón." });
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/v1/cases/case-193/delegate-inquiry", expect.objectContaining({
      method: "POST",
      body: '{"case_id":"case-193","analyst_id":"analyst-193","instruction":"Vui lòng gửi ảnh điểm đón."}',
    }));
  });
});
