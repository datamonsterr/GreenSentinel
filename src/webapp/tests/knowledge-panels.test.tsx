import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import vi_ from "@/messages/vi.json";
import en_ from "@/messages/en.json";
import type { KbObject, Proposal } from "@/lib/knowledge-client";

const api = vi.hoisted(() => ({
  parameters: vi.fn(), validateFormula: vi.fn(), listObjects: vi.fn(), versions: vi.fn(), create: vi.fn(), update: vi.fn(),
  clone: vi.fn(), submit: vi.fn(), trial: vi.fn(), publish: vi.fn(), retire: vi.fn(), rollback: vi.fn(), preview: vi.fn(),
  similar: vi.fn(), registry: vi.fn(), seed: vi.fn(), documents: vi.fn(), createDocument: vi.fn(), proposals: vi.fn(),
  acceptProposal: vi.fn(), analyzeDocument: vi.fn(), editProposal: vi.fn(), rejectProposal: vi.fn(), config: vi.fn(), setConfig: vi.fn(), killSwitch: vi.fn(),
  configHistory: vi.fn(), revert: vi.fn(), getObject: vi.fn(),
}));
vi.mock("@/lib/knowledge-client", async (orig) => ({ ...(await orig<typeof import("@/lib/knowledge-client")>()), knowledgeApi: api }));

import { StorePanel } from "@/components/knowledge/store-panel";
import { ConfigPanel } from "@/components/knowledge/config-panel";
import { ProposalsPanel } from "@/components/knowledge/proposals-panel";
import { DocumentsPanel } from "@/components/knowledge/documents-panel";
import { AgentsPanel } from "@/components/knowledge/agents-panel";

const obj = (over: Partial<KbObject> = {}): KbObject => ({
  id: "o1", type: "motive", code: "MOT_A", version: 1, status: "trial", name: "Thưởng mốc", scope: {}, body: { formula: "=trips_today" },
  change_reason: null, author_id: "u-analyst", author_name: "Hà", approver_id: null, approver_name: null, override_reason: null, retired_reason: null,
  replay: { cases_total: 25, matched: 13, changed_scenario: 0, not_computable: 0, est_turns: 0, computable_ratio: 1, gate_passed: true, gate_min: 0.5, run_at: "" },
  history: [{ at: "2026-11-20T00:00:00Z", by: "u-analyst", by_name: "Hà", action: "create", note: "" }],
  created_at: "2026-11-20T00:00:00Z", updated_at: "2026-11-20T00:00:00Z", published_at: null, ...over,
});

const wrap = (ui: React.ReactElement, lang: "vi" | "en" = "vi") => render(
  <NextIntlClientProvider locale={lang} messages={lang === "vi" ? vi_ : en_} timeZone="UTC">{ui}</NextIntlClientProvider>);

const analyst = { id: "u-analyst", roles: ["fraud_analyst"] };
const admin = { id: "u-admin", roles: ["admin"] };

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.parameters.mockResolvedValue({ items: [{ code: "trips_today", name: "Trips today", description: "", unit: "count", source: "trips", owner: "Data", latency: "rt", sample: 7, kind: "case" }] });
  api.validateFormula.mockResolvedValue({ ok: true, errors: [], warnings: [], used_params: ["trips_today"], sample: 7 });
  api.versions.mockResolvedValue({ items: [obj()] });
  api.listObjects.mockResolvedValue({ items: [obj(), obj({ id: "o2", code: "BHV_B", type: "behavior", status: "published", name: "Đứng yên" })] });
});

describe("StorePanel", () => {
  it("lists objects with Vietnamese status chips", async () => {
    wrap(<StorePanel me={analyst} onChanged={() => {}} />);
    expect(await screen.findByTestId("row-MOT_A-v1")).toHaveTextContent("Chạy thử");
    expect(screen.getByTestId("row-BHV_B-v1")).toHaveTextContent("Đã phát hành");
  });

  it("renders English labels when locale is en", async () => {
    wrap(<StorePanel me={analyst} onChanged={() => {}} />, "en");
    expect(await screen.findByTestId("row-MOT_A-v1")).toHaveTextContent("Trial");
  });

  it("author sees the four-eyes notice and no Publish button", async () => {
    wrap(<StorePanel me={analyst} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("row-MOT_A-v1"));
    expect(await screen.findByText(/Chỉ chuyên viên cao cấp hoặc quản trị viên/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phát hành" })).toBeNull();
  });

  it("a different approver can publish; the call is made", async () => {
    api.publish.mockResolvedValue(obj({ status: "published" }));
    wrap(<StorePanel me={admin} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("row-MOT_A-v1"));
    fireEvent.click(await screen.findByRole("button", { name: "Phát hành" }));
    await waitFor(() => expect(api.publish).toHaveBeenCalledWith("o1", ""));
  });

  it("failed trial gate requires an override reason before publishing", async () => {
    const replay = { ...obj().replay!, gate_passed: false, not_computable: 25, computable_ratio: 0 };
    api.listObjects.mockResolvedValue({ items: [obj({ replay })] });
    wrap(<StorePanel me={admin} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("row-MOT_A-v1"));
    const publish = await screen.findByRole("button", { name: "Phát hành" });
    expect(publish).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do vượt cổng"), { target: { value: "Đã kiểm tra thủ công với vận hành" } });
    expect(publish).toBeEnabled();
  });

  it("shows live formula validation errors from the API", async () => {
    api.validateFormula.mockResolvedValue({ ok: false, errors: [{ code: "unknown_param", message: "Unknown parameter 'nope'", position: 1 }], warnings: [], used_params: [], sample: null });
    api.listObjects.mockResolvedValue({ items: [obj({ status: "draft", body: { formula: "=nope+1" } })] });
    wrap(<StorePanel me={analyst} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("row-MOT_A-v1"));
    const check = await screen.findByTestId("formula-check");
    expect(check).toHaveTextContent("unknown_param");
    expect(check).toHaveTextContent("Sửa công thức");
  });

  it("surfaces backend validation issues when submit is refused", async () => {
    api.listObjects.mockResolvedValue({ items: [obj({ status: "draft" })] });
    api.submit.mockRejectedValue(new Error('API Error 422: {"message":"Validation failed","errors":[{"path":"body.formula","code":"div_zero","message":"Division by zero"}]}'));
    wrap(<StorePanel me={analyst} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("row-MOT_A-v1"));
    fireEvent.click(await screen.findByRole("button", { name: "Gửi kiểm thử" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("div_zero");
  });

  it("empty store offers demo seed to admins only", async () => {
    api.listObjects.mockResolvedValue({ items: [] });
    const { unmount } = wrap(<StorePanel me={admin} onChanged={() => {}} />);
    expect(await screen.findByRole("button", { name: "Nạp dữ liệu mẫu" })).toBeInTheDocument();
    unmount();
    wrap(<StorePanel me={analyst} onChanged={() => {}} />);
    await screen.findByTestId("store-empty");
    expect(screen.queryByRole("button", { name: "Nạp dữ liệu mẫu" })).toBeNull();
  });
});

describe("ConfigPanel", () => {
  const item = (over: Record<string, unknown>) => ({ key: "n_max", type: "int", default: 6, min: 1, max: 15, owner: "VH", group: "limits",
    label: { vi: "N_max: số lượt hỏi tối đa / phiên", en: "N_max" }, scope: "global", value: 6, is_default: true, updated_at: null, can_edit: true, ...over });
  beforeEach(() => {
    api.config.mockResolvedValue({ items: [item({}), item({ key: "explain_agent_enabled", type: "bool", default: false, min: null, max: null, owner: "LEAD", group: "kill_switch", value: false, label: { vi: "Agent v2", en: "Agent v2" } })],
      metrics: { window_days: 30, avg_turns: null, pct_exhausted: null, pct_help: null, available: false } });
    api.configHistory.mockResolvedValue({ items: [] });
  });

  it("blocks out-of-bounds values and requires a reason", async () => {
    wrap(<ConfigPanel />);
    const input = await screen.findByLabelText("N_max: số lượt hỏi tối đa / phiên");
    fireEvent.change(input, { target: { value: "0" } });
    expect(await screen.findByText(/Khoảng cho phép là 1 đến 15/)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "4" } });
    const save = screen.getByRole("button", { name: "Lưu" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getAllByLabelText("Lý do thay đổi").at(-1)!, { target: { value: "giảm lượt" } });
    api.setConfig.mockResolvedValue({ value: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(api.setConfig).toHaveBeenCalledWith("n_max", 4, "giảm lượt"));
  });

  it("kill switch needs a reason and calls the API", async () => {
    api.killSwitch.mockResolvedValue({ value: true });
    wrap(<ConfigPanel />);
    const turnOn = await screen.findByRole("button", { name: "Bật" });
    expect(turnOn).toBeDisabled();
    fireEvent.change(screen.getAllByLabelText("Lý do thay đổi")[0], { target: { value: "bắt đầu pilot" } });
    fireEvent.click(turnOn);
    await waitFor(() => expect(api.killSwitch).toHaveBeenCalledWith(true, "bắt đầu pilot"));
  });

  it("lists history with revert action", async () => {
    api.configHistory.mockResolvedValue({ items: [{ id: "h1", key: "n_max", scope: "global", old_value: 6, new_value: 4, reason: "giảm", kind: "change", changed_by_name: "Minh", created_at: "2026-11-20T01:00:00Z" }] });
    wrap(<ConfigPanel />);
    const table = await screen.findByTestId("config-history");
    await waitFor(() => expect(within(table).getByText("giảm")).toBeInTheDocument());
    fireEvent.click(within(table).getByRole("button", { name: "Quay lại" }));
    expect(await screen.findByTestId("revert-form")).toBeInTheDocument();
  });
});

describe("ProposalsPanel", () => {
  const prop = (over: Partial<Proposal> = {}): Proposal => ({ id: "p1", source: "policy_analysis", type: "motive", title: "Động cơ mới", payload: { code: "MOT_X", name: "X", body: { formula: "=trips_today" } },
    source_excerpt: "Điều 3", source_ref: "doc", mapping: "extend", similarity: 0.8, matched_code: "MOT_A", status: "pending", reason_code: null, note: null,
    created_by: "agent", created_at: "2026-11-20T00:00:00Z", resulting_object_id: null, ...over });

  it("accept, and reject requires a reason", async () => {
    api.proposals.mockResolvedValue({ items: [prop()] });
    api.acceptProposal.mockResolvedValue({ proposal: prop({ status: "accepted" }), object: obj() });
    api.rejectProposal.mockResolvedValue(prop({ status: "rejected" }));
    wrap(<ProposalsPanel me={analyst} onChanged={() => {}} />);
    expect(await screen.findByText("Điều 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ" }));
    await screen.findByLabelText("Lý do bỏ");
    const confirmBtn = screen.getAllByRole("button", { name: "Bỏ" }).at(-1)!;
    expect(confirmBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do bỏ"), { target: { value: "duplicate" } });
    fireEvent.change(screen.getByLabelText("Ghi chú"), { target: { value: "đã có" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Bỏ" }).at(-1)!);
    await waitFor(() => expect(api.rejectProposal).toHaveBeenCalledWith("p1", "duplicate", "đã có"));
  });

  it("accept calls the API", async () => {
    api.proposals.mockResolvedValue({ items: [prop()] });
    api.acceptProposal.mockResolvedValue({ proposal: prop({ status: "accepted" }), object: obj() });
    wrap(<ProposalsPanel me={analyst} onChanged={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Chấp nhận" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("p1"));
  });

  it("edit sends the modified payload", async () => {
    api.proposals.mockResolvedValue({ items: [prop()] });
    api.editProposal.mockResolvedValue({ proposal: prop({ status: "edited" }), object: obj() });
    wrap(<ProposalsPanel me={analyst} onChanged={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Sửa" }));
    fireEvent.change(screen.getByLabelText("Sửa nội dung đề xuất (JSON)."), { target: { value: '{"code":"MOT_X","name":"Y","body":{}}' } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu và chấp nhận" }));
    await waitFor(() => expect(api.editProposal).toHaveBeenCalledWith("p1", { code: "MOT_X", name: "Y", body: {} }));
  });
});

const docRow = (over: Record<string, unknown> = {}) => ({ id: "d1", name: "Chính sách thưởng", code: "POL-1", effective_from: null, effective_to: null, region: null,
  service: null, contract_type: null, filename: "a.txt", size_bytes: 10, indexing_status: "embeddings_not_configured", uploaded_by_name: "Hà",
  created_at: "2026-11-20T00:00:00Z", has_text: true, used_by: [], analysis_status: "pending", analysis_error: null, analysis_counts: {}, analyzed_at: null, ...over });

describe("DocumentsPanel analysis", () => {
  it("runs analysis and reloads status with counts", async () => {
    api.documents.mockResolvedValueOnce({ items: [docRow()] }).mockResolvedValue({ items: [docRow({ analysis_status: "done", analysis_counts: { proposals: 3, reuse: 1, extend: 1, new: 1, rejected_citation: 2 } })] });
    api.analyzeDocument.mockResolvedValue({});
    wrap(<DocumentsPanel me={analyst} />);
    fireEvent.click(await screen.findByRole("button", { name: "Phân tích" }));
    await waitFor(() => expect(api.analyzeDocument).toHaveBeenCalledWith("d1"));
    expect(await screen.findByText("Đã phân tích")).toBeInTheDocument();
    expect(screen.getByTestId("analysis-counts-d1")).toHaveTextContent("3");
    expect(screen.getByTestId("analysis-counts-d1")).toHaveTextContent("2");
  });

  it("flags a truncated analysis with chunks done/total", async () => {
    api.documents.mockResolvedValue({ items: [docRow({ analysis_status: "done", analysis_counts: { proposals: 1, chunks: 12, chunks_total: 20, truncated: true } })] });
    wrap(<DocumentsPanel me={analyst} />);
    expect(await screen.findByTestId("analysis-truncated-d1")).toHaveTextContent("12/20");
  });

  it("shows failed status with the error and disables analyze without text", async () => {
    api.documents.mockResolvedValue({ items: [docRow({ analysis_status: "failed", analysis_error: "credentials are not configured", has_text: false })] });
    wrap(<DocumentsPanel me={analyst} />);
    expect(await screen.findByText("Phân tích lỗi")).toBeInTheDocument();
    expect(screen.getByText("credentials are not configured")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Phân tích lại" })).toBeDisabled();
  });
});

describe("DocumentsPanel + AgentsPanel", () => {
  it("shows indexing status and blocks submit until required fields are present", async () => {
    api.documents.mockResolvedValue({ items: [{ id: "d1", name: "Chính sách thưởng", code: "POL-1", effective_from: null, effective_to: null, region: "HN", service: null,
      contract_type: null, filename: "a.txt", size_bytes: 10, indexing_status: "embeddings_not_configured", uploaded_by_name: "Hà", created_at: "2026-11-20T00:00:00Z",
      has_text: true, used_by: [{ vi: "Agent phân tích tri thức", en: "Knowledge analysis agent" }] }] });
    wrap(<DocumentsPanel me={analyst} />);
    expect(await screen.findByText("Chưa cấu hình embeddings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tải lên" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Tên chính sách"), { target: { value: "P" } });
    fireEvent.change(screen.getByLabelText("Mã chính sách"), { target: { value: "P-2" } });
    fireEvent.change(screen.getByLabelText("Hoặc dán nội dung"), { target: { value: "nội dung" } });
    expect(screen.getByRole("button", { name: "Tải lên" })).toBeEnabled();
  });

  it("lists agents with tools and memory layers", async () => {
    api.registry.mockResolvedValue({ published_counts: {}, tool_catalogue: [], agents: [{ id: "driver_agent", name: { vi: "Agent giải trình tài xế", en: "Driver explanation agent" },
      instruction_version: "driver-explain@2.0.0", model: "z-ai/glm-5.3-flash", enabled: false, knowledge_types: ["motive"], knowledge_published: { motive: 2 },
      tools: ["identify_behavior"], memory_layers: ["session"], uses_policy_documents: false, reads: "published" }] });
    wrap(<AgentsPanel />);
    expect(await screen.findByTestId("agent-driver_agent")).toHaveTextContent("Agent giải trình tài xế");
    expect(screen.getByText("identify_behavior")).toBeInTheDocument();
    expect(screen.getByText("Đang tắt (kill switch)")).toBeInTheDocument();
    expect(screen.getByText("Động cơ: 2")).toBeInTheDocument();
  });
});
