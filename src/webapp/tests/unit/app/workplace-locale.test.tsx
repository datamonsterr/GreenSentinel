import React from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LocaleProvider } from "@/lib/locale";
import WorkplacePage from "@/app/workplace/page";
import * as api from "@/lib/api-client";

const auth = vi.hoisted(() => ({ isLoaded: true, getToken: vi.fn(async () => null) }));
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  OrganizationSwitcher: () => <span>Organization account</span>,
  UserButton: () => <span>User account</span>,
}));
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: ({ caseId }: { caseId?: string }) => <div data-testid="map-boundary" data-case-id={caseId} />,
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api-client")>(),
  setApiTokenProvider: vi.fn(), fetchCases: vi.fn(), fetchCurrentAnalyst: vi.fn(),
  fetchCaseDetail: vi.fn(), fetchForensicBrief: vi.fn(), fetchCasePolicy: vi.fn(),
  fetchAgentSession: vi.fn(), getDisputeDossier: vi.fn(), getCaseWorkflowTrace: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
}));

beforeEach(() => {
  vi.clearAllMocks();
  auth.isLoaded = true;
  localStorage.clear();
  window.history.replaceState(null, "", "/workplace?caseId=case-two");
  const first = { id: "case-one", driver_name: "First driver", vehicle_plate: "30A-12345", priority: "P1", priority_score: 1, status: "ready", version: 1 };
  const second = { ...first, id: "case-two", driver_name: "Second driver" };
  vi.mocked(api.fetchCases).mockResolvedValue({ items: [first, second], total: 2, limit: 50, offset: 0 });
  vi.mocked(api.fetchCurrentAnalyst).mockResolvedValue({ id: "analyst-test", name: "Analyst", role: "analyst", roles: ["analyst"] });
  vi.mocked(api.fetchCaseDetail).mockResolvedValue({ case: second, active_lease: { analyst_id: "analyst-test", expires_at: "2099-01-01" }, preliminary_judgment: null, trip: {}, conversation: [{ role: "driver", text: "Original Driver evidence", occurred_at: "2026-10-15T00:00:00Z" }] });
  vi.mocked(api.fetchForensicBrief).mockResolvedValue({ case_id: "case-two", generated_at: "2026-10-15T00:00:00Z", abnormalities: [], abnormality_count: 0, evidence_sources: [], summary_text: "" });
  vi.mocked(api.fetchCasePolicy).mockResolvedValue({ case_id: "case-two", action_matrix: {}, applicable_action_rule: {}, clauses: [], related_policies: [], source: "unit fixture" });
  vi.mocked(api.fetchAgentSession).mockResolvedValue({ session_id: "session-test", messages: [] });
  vi.mocked(api.getDisputeDossier).mockRejectedValue(new Error("Optional dispute unavailable in fixture"));
  vi.mocked(api.getCaseWorkflowTrace).mockResolvedValue({ agent_tools_called: [], human_actions_performed: [], driver_response_summary: "", related_policies: [] });
});
afterEach(() => { vi.unstubAllEnvs(); window.history.replaceState(null, "", "/"); });

test("switches all navigation labels while retaining the case, draft, search, and stream", async () => {
  const user = userEvent.setup();
  render(<LocaleProvider><WorkplacePage /></LocaleProvider>);
  await user.click(await screen.findByRole("button", { name: /#case-two/i }));
  await screen.findByRole("tab", { name: /^overview$/i });
  await user.click(screen.getByRole("tab", { name: /^customer$/i }));
  await screen.findByText("Original Driver evidence");
  await user.click(screen.getByRole("tab", { name: /Complete/i }));
  const rationale = screen.getByLabelText("Decision rationale");
  await user.type(rationale, "Independent draft");
  const search = screen.getByRole("textbox", { name: "Search workspace" });
  await user.type(search, "usr:8492");
  await user.click(screen.getByRole("tab", { name: "Maps" }));
  const map = screen.getByTestId("map-boundary");
  const subscriptions = vi.mocked(api.subscribeCaseStream).mock.calls.length;
  await user.click(screen.getByRole("button", { name: "GreenSentinel app catalog" }));
  expect(screen.getByRole("button", { name: /Unified Adjudication/ })).toBeVisible();
  const url = window.location.href;
  await user.click(screen.getByRole("button", { name: "Switch language to Vietnamese" }));
  expect(screen.getByRole("button", { name: "Chuyển ngôn ngữ sang tiếng Việt" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Chuyển ngôn ngữ sang tiếng Anh" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByText("Ứng dụng GreenSentinel")).toBeVisible();
  expect(screen.getByRole("button", { name: /Xét duyệt hợp nhất/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /Dữ liệu đội xe và phân tích/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /Hồ sơ chuyên viên và nhật ký/ })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Tìm kiếm không gian làm việc" })).toHaveValue("usr:8492");
  expect(screen.getByLabelText("Lý do thẩm định")).toBe(rationale);
  expect(rationale).toHaveValue("Independent draft");
  expect(screen.getByTestId("map-boundary")).toBe(map);
  expect(map).toHaveAttribute("data-case-id", "case-two");
  expect(api.subscribeCaseStream).toHaveBeenCalledTimes(subscriptions);
  await user.click(screen.getByRole("tab", { name: "Khách hàng" }));
  expect(screen.getByText("Original Driver evidence")).toBeVisible();
  expect(window.location.href).toBe(url);
  await user.click(screen.getByRole("button", { name: "Chuyển ngôn ngữ sang tiếng Anh" }));
  expect(screen.getByRole("button", { name: "Switch language to English" })).toHaveAttribute("aria-pressed", "true");
  expect(rationale).toHaveValue("Independent draft");
});

test("saved locale translates loading state while Clerk is still loading", () => {
  auth.isLoaded = false;
  localStorage.setItem("greensentinel.locale", "vi");
  render(<LocaleProvider><WorkplacePage /></LocaleProvider>);
  expect(screen.getByText("Đang mở không gian làm việc…")).toBeInTheDocument();
});

test("keyboard switching translates the local E2E indicator", async () => {
  vi.stubEnv("NEXT_PUBLIC_E2E_TEST", "true");
  const user = userEvent.setup();
  render(<LocaleProvider><WorkplacePage /></LocaleProvider>);
  const button = await screen.findByRole("button", { name: "Switch language to Vietnamese" });
  button.focus();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(screen.getByTestId("e2e-auth-indicator")).toHaveTextContent("Chế độ E2E"));
});
