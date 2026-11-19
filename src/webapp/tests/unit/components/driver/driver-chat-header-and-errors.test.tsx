import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import viMessages from "@/messages/vi.json";
import enMessages from "@/messages/en.json";
import * as apiClient from "@/lib/api-client";

const mockPush = vi.fn();
const mockBack = vi.fn();
let mockStatus = "ready";
let mockError: any = null;

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: [],
    setMessages: vi.fn(),
    sendMessage: vi.fn(),
    regenerate: vi.fn(),
    status: mockStatus,
    error: mockError,
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: () => ({ user: { firstName: "An" }, isLoaded: true }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: mockBack }),
}));

vi.mock("@/lib/api-client", () => ({
  fetchDriverSession: vi.fn().mockResolvedValue({ messages: [] }),
  getDriverDisputeContext: vi.fn(),
}));

import { DriverChatView } from "@/components/driver/chat/driver-chat-view";

describe("DriverChatView — F1, F2, F3, F4", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatus = "ready";
    mockError = null;
    vi.mocked(apiClient.fetchDriverSession).mockResolvedValue({ messages: [] } as any);
  });

  it("F3 & F4: renders header pill with whitespace-nowrap shrink-0 and title with min-w-0 truncate", async () => {
    vi.mocked(apiClient.getDriverDisputeContext).mockResolvedValue({
      case_id: "018f2f4e-a000-7000-8000-000000001234",
      driver_id: "drv-1",
      driver_name: "An",
      trip_id: "trip-1",
      violation_code: "ERR-01",
      violation_title: "Chậm đón khách (Pickup delay)",
      dispute_status: "in_dispute",
      allowed_claim_types: [],
      alleged_time: null,
      alleged_location: null,
      dispute_deadline: null,
    });

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView caseId="018f2f4e-a000-7000-8000-000000001234" />
      </DriverI18nProvider>
    );

    // Title from VIOLATION_TITLE_MAP for ERR-01 in vi
    const expectedTitleVi = "Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt";
    expect(await screen.findByText(expectedTitleVi)).toBeInTheDocument();

    const titleEl = screen.getByText(expectedTitleVi);
    expect(titleEl).toHaveClass("min-w-0");
    expect(titleEl).toHaveClass("truncate");

    // Status pill
    const pill = screen.getByTestId("case-status-pill");
    expect(pill).toHaveClass("whitespace-nowrap");
    expect(pill).toHaveClass("shrink-0");

    // Back button replaces the case chip
    expect(screen.queryByTestId("case-chip")).toBeNull();
    const back = screen.getByRole("button", { name: "Quay lại" });
    expect(back).toHaveAttribute("aria-label", "Quay lại");
  });

  it("F4: renders English violation title in header when locale is en", async () => {
    vi.mocked(apiClient.getDriverDisputeContext).mockResolvedValue({
      case_id: "case-alpha-1234",
      driver_id: "drv-1",
      driver_name: "An",
      trip_id: "trip-1",
      violation_code: "ERR-02",
      violation_title: "Lái xe lệch tuyến (Route deviation)",
      dispute_status: "in_dispute",
      allowed_claim_types: [],
      alleged_time: null,
      alleged_location: null,
      dispute_deadline: null,
    });

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView caseId="case-alpha-1234" />
      </DriverI18nProvider>
    );

    // Title from VIOLATION_TITLE_MAP for ERR-02 in en
    const expectedTitleEn = "Route deviation / stall-to-cancel";
    expect(await screen.findByText(expectedTitleEn)).toBeInTheDocument();
  });

  it("F4: falls back to violation_title with English parenthetical stripped when code is unknown", async () => {
    vi.mocked(apiClient.getDriverDisputeContext).mockResolvedValue({
      case_id: "case-custom-999",
      driver_id: "drv-1",
      driver_name: "An",
      trip_id: "trip-1",
      violation_code: "CUSTOM_UNKNOWN",
      violation_title: "Khách phản ánh thái độ (Customer complaint about attitude)",
      dispute_status: "in_dispute",
      allowed_claim_types: [],
      alleged_time: null,
      alleged_location: null,
      dispute_deadline: null,
    });

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView caseId="case-custom-999" />
      </DriverI18nProvider>
    );

    expect(await screen.findByText("Khách phản ánh thái độ")).toBeInTheDocument();
    expect(screen.queryByText(/Customer complaint/i)).not.toBeInTheDocument();
  });

  it("F1: maps 404/403 stream error to localized next-intl text in vi", async () => {
    mockStatus = "error";
    mockError = new Error("Driver chat stream failed with status 404");

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    const alert = screen.getByTestId("driver-chat-error");
    expect(alert).toBeInTheDocument();
    expect(
      screen.getByText("Không tìm thấy vụ việc hoặc bạn không có quyền xem vụ việc này")
    ).toBeInTheDocument();
    // Never renders developer English or status code
    expect(screen.queryByText(/404/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Driver chat stream failed/i)).not.toBeInTheDocument();
  });

  it("F1: maps 404/403 stream error to localized next-intl text in en", async () => {
    mockStatus = "error";
    mockError = new Error("Driver chat stream failed with status 403");

    render(
      <DriverI18nProvider locale="en" messages={enMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(
      screen.getByText("This case was not found or you do not have access")
    ).toBeInTheDocument();
    expect(screen.queryByText(/403/)).not.toBeInTheDocument();
  });

  it("F1: maps 401 error to session expired text", async () => {
    mockStatus = "error";
    mockError = new Error("Driver chat stream failed with status 401");

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(
      screen.getByText("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại")
    ).toBeInTheDocument();
  });

  it("F1: maps 5xx and network errors to assistant unavailable text", async () => {
    mockStatus = "error";
    mockError = new TypeError("Failed to fetch");

    render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    expect(
      screen.getByText("Không kết nối được trợ lý, vui lòng thử lại")
    ).toBeInTheDocument();
  });

  it("F2: composer textarea has flex-1 min-w-0 w-full classes", () => {
    const { container } = render(
      <DriverI18nProvider locale="vi" messages={viMessages}>
        <DriverChatView />
      </DriverI18nProvider>
    );

    const textarea = container.querySelector('[data-testid="chat-composer"] textarea');
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveClass("flex-1");
    expect(textarea).toHaveClass("min-w-0");
    expect(textarea).toHaveClass("w-full");
  });
});
