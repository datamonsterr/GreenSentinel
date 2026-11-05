import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  BlockRenderer,
  CaseCard,
  TripCard,
  TableBlockComponent,
  ClickableList,
  LinkBlockComponent,
  StatusPill,
  EvidenceBlockComponent,
  NextSteps,
  formatCaseId,
  formatTripId,
  defaultStatusLabel,
  VI_LABELS,
  EN_LABELS,
} from "@/components/driver/blocks";
import type {
  CaseCardBlock,
  TripCardBlock,
  TableBlock,
  ClickableListBlock,
  LinkBlock,
  StatusPillBlock,
  EvidenceBlock,
  NextStepsBlock,
  DriverChatBlock,
} from "@/types/driver-blocks";

describe("CaseCard", () => {
  const sampleCase: CaseCardBlock = {
    type: "case_card",
    case_id: "case-a3f91234-abcd-5678",
    title: "Lệch tuyến đường giờ cao điểm",
    status_key: "under_investigation",
  };

  it("renders short code and never renders raw id", () => {
    render(<CaseCard {...sampleCase} />);

    expect(screen.getByText("#A3F9")).toBeInTheDocument();
    expect(screen.queryByText(sampleCase.case_id)).not.toBeInTheDocument();
    expect(screen.getByText("Lệch tuyến đường giờ cao điểm")).toBeInTheDocument();
  });

  it("formats case UUIDs without prefix correctly and suppresses raw uuid", () => {
    const uuidCase: CaseCardBlock = {
      type: "case_card",
      case_id: "550e8400-e29b-41d4-a716-446655440000",
      title: "Cước phí chênh lệch",
      status_key: "pending",
    };
    render(<CaseCard {...uuidCase} />);

    expect(screen.getByText("#550E")).toBeInTheDocument();
    expect(screen.queryByText(uuidCase.case_id)).not.toBeInTheDocument();
  });

  it("formats status with statusLabel prop", () => {
    const statusLabel = vi.fn((key: string) => `Status: ${key.toUpperCase()}`);
    render(<CaseCard {...sampleCase} statusLabel={statusLabel} />);

    expect(statusLabel).toHaveBeenCalledWith("under_investigation");
    expect(screen.getByText("Status: UNDER_INVESTIGATION")).toBeInTheDocument();
  });

  it("invokes onNavigate with case:// href when clicked or triggered by keyboard", () => {
    const onNavigate = vi.fn();
    render(<CaseCard {...sampleCase} onNavigate={onNavigate} />);

    const card = screen.getByRole("button", { name: /#A3F9/i });
    fireEvent.click(card);
    expect(onNavigate).toHaveBeenCalledWith(`case://${sampleCase.case_id}`);

    fireEvent.keyDown(card, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });

  it("renders with English labels when labels prop is supplied", () => {
    render(<CaseCard {...sampleCase} labels={EN_LABELS} />);
    expect(screen.getByRole("button", { name: /Case #A3F9/i })).toBeInTheDocument();
  });
});

describe("TripCard", () => {
  const sampleTrip: TripCardBlock = {
    type: "trip_card",
    trip_id: "trip-88219-uuid-9999",
    pickup: "45 Lê Duẩn, Q.1",
    destination: "120 Trần Não, TP. Thủ Đức",
    fare_vnd: 85000,
  };

  it("renders trip details, formatted fare, and never exposes any trip_id fragment", () => {
    render(<TripCard {...sampleTrip} />);

    expect(screen.getByText("45 Lê Duẩn, Q.1")).toBeInTheDocument();
    expect(screen.getByText("120 Trần Não, TP. Thủ Đức")).toBeInTheDocument();
    expect(screen.getByText(/85\.000/)).toBeInTheDocument();

    // Must never show raw id or any short code fragment
    expect(screen.queryByText(sampleTrip.trip_id)).not.toBeInTheDocument();
    expect(screen.queryByText(/#GS-/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/88219/)).not.toBeInTheDocument();

    // Shows opaque label from default Vietnamese labels
    expect(screen.getByText("Chuyến đi")).toBeInTheDocument();
  });

  it("hides fare row when fare_vnd is missing and never renders NaN đ", () => {
    const noFareTrip: TripCardBlock = {
      type: "trip_card",
      trip_id: "trip-12345",
      pickup: "Điểm A",
      destination: "Điểm B",
    };
    render(<TripCard {...noFareTrip} />);

    expect(screen.getByText("Điểm A")).toBeInTheDocument();
    expect(screen.getByText("Điểm B")).toBeInTheDocument();
    expect(screen.queryByText(/NaN/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Cước phí/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Recorded fare/i)).not.toBeInTheDocument();
  });

  it("triggers onNavigate with trip:// href on click", () => {
    const onNavigate = vi.fn();
    render(<TripCard {...sampleTrip} onNavigate={onNavigate} />);

    const button = screen.getByRole("button", { name: /chuyến|trip/i });
    fireEvent.click(button);

    expect(onNavigate).toHaveBeenCalledWith(`trip://${sampleTrip.trip_id}`);
  });

  it("renders with English labels when labels prop is provided", () => {
    render(<TripCard {...sampleTrip} labels={EN_LABELS} />);

    expect(screen.getByText("Trip")).toBeInTheDocument();
    expect(screen.getByText("Pickup")).toBeInTheDocument();
    expect(screen.getByText("Destination")).toBeInTheDocument();
    expect(screen.getByText("Recorded fare")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Trip details/i })).toBeInTheDocument();
  });
});

describe("TableBlockComponent", () => {
  const sampleTable: TableBlock = {
    type: "table",
    columns: ["Thời gian", "Khoảng cách", "Ghi chú"],
    rows: [
      ["14:00", "5.2 km", "Bình thường"],
      ["14:15", "7.6 km", "Phát hiện chênh lệch"],
    ],
  };

  it("renders headers and cells properly", () => {
    render(<TableBlockComponent {...sampleTable} />);

    expect(screen.getByText("Thời gian")).toBeInTheDocument();
    expect(screen.getByText("Khoảng cách")).toBeInTheDocument();
    expect(screen.getByText("Ghi chú")).toBeInTheDocument();
    expect(screen.getByText("5.2 km")).toBeInTheDocument();
    expect(screen.getByText("Phát hiện chênh lệch")).toBeInTheDocument();
  });
});

describe("ClickableList", () => {
  const sampleList: ClickableListBlock = {
    type: "list",
    items: [
      { label: "Xem vụ việc liên quan", href: "case://case-999" },
      { label: "Xem cuốc xe trước", href: "trip://trip-777" },
      { label: "Quy chuẩn an toàn", href: "policy://driver-safety" },
      { label: "Chính sách tài xế", href: "https://support.greensm.vn/policy" },
    ],
  };

  it("routes case://, trip://, and policy:// through onNavigate and https:// through rel=noopener", () => {
    const onNavigate = vi.fn();
    render(<ClickableList {...sampleList} onNavigate={onNavigate} />);

    const caseLink = screen.getByText("Xem vụ việc liên quan");
    fireEvent.click(caseLink);
    expect(onNavigate).toHaveBeenCalledWith("case://case-999");

    const tripLink = screen.getByText("Xem cuốc xe trước");
    fireEvent.click(tripLink);
    expect(onNavigate).toHaveBeenCalledWith("trip://trip-777");

    const policyLink = screen.getByText("Quy chuẩn an toàn");
    fireEvent.click(policyLink);
    expect(onNavigate).toHaveBeenCalledWith("policy://driver-safety");

    const externalLink = screen.getByRole("link", { name: /Chính sách tài xế/i });
    expect(externalLink).toHaveAttribute("target", "_blank");
    expect(externalLink.getAttribute("rel")).toContain("noopener");
  });

  it("renders non-allowlisted schemes as plain text (no button, no anchor)", () => {
    const unallowedList: ClickableListBlock = {
      type: "list",
      items: [
        { label: "Malicious script", href: "javascript:alert(1)" },
        { label: "Insecure http", href: "http://insecure.example.com" },
        { label: "File link", href: "file:///etc/passwd" },
      ],
    };

    render(<ClickableList {...unallowedList} />);

    expect(screen.getByText("Malicious script")).toBeInTheDocument();
    expect(screen.getByText("Insecure http")).toBeInTheDocument();
    expect(screen.getByText("File link")).toBeInTheDocument();

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("returns null when items array is empty", () => {
    const { container } = render(<ClickableList type="list" items={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("LinkBlockComponent", () => {
  it("renders external link with rel=noopener and new tab for https://", () => {
    const link: LinkBlock = {
      type: "link",
      label: "Quy chuẩn dịch vụ GreenSM",
      url: "https://greensm.vn/terms",
    };
    render(<LinkBlockComponent {...link} />);

    const anchor = screen.getByRole("link", { name: /Quy chuẩn dịch vụ GreenSM/i });
    expect(anchor).toHaveAttribute("target", "_blank");
    expect(anchor.getAttribute("rel")).toContain("noopener");
  });

  it("routes case://, trip://, and policy:// url via onNavigate", () => {
    const onNavigate = vi.fn();
    const caseLink: LinkBlock = {
      type: "link",
      label: "Chi tiết vụ việc #B441",
      url: "case://case-b441",
    };
    const { rerender } = render(<LinkBlockComponent {...caseLink} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByText("Chi tiết vụ việc #B441"));
    expect(onNavigate).toHaveBeenCalledWith("case://case-b441");

    const policyLink: LinkBlock = {
      type: "link",
      label: "Quy định hoàn tiền",
      url: "policy://refund-rules",
    };
    rerender(<LinkBlockComponent {...policyLink} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByText("Quy định hoàn tiền"));
    expect(onNavigate).toHaveBeenCalledWith("policy://refund-rules");
  });

  it("renders non-allowlisted schemes as plain text (no button or link)", () => {
    const badLink: LinkBlock = {
      type: "link",
      label: "Script URL",
      url: "javascript:alert(1)",
    };
    render(<LinkBlockComponent {...badLink} />);

    expect(screen.getByText("Script URL")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders with English labels when labels prop is supplied", () => {
    const internalLink: LinkBlock = {
      type: "link",
      label: "Case Overview",
      url: "case://case-123",
    };
    render(<LinkBlockComponent {...internalLink} labels={EN_LABELS} />);

    expect(screen.getByText("In-app navigation")).toBeInTheDocument();
  });
});

describe("StatusPill", () => {
  it("renders status label and handles statusLabel mapping", () => {
    const pill: StatusPillBlock = {
      type: "status_pill",
      status_key: "resolved",
    };
    const statusLabel = vi.fn().mockReturnValue("Đã giải quyết");
    render(<StatusPill {...pill} statusLabel={statusLabel} />);

    expect(statusLabel).toHaveBeenCalledWith("resolved");
    expect(screen.getByText("Đã giải quyết")).toBeInTheDocument();
  });

  it("provides sensible default Vietnamese labels when statusLabel is omitted", () => {
    const { rerender } = render(<StatusPill type="status_pill" status_key="under_investigation" />);
    expect(screen.getByText("Đang giải quyết")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="auto_dismissed" />);
    expect(screen.getByText("Tự động miễn trừ")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="violation" />);
    expect(screen.getByText("Xác nhận vi phạm")).toBeInTheDocument();
  });

  it("supports new required status keys: under_review, draft, submitted, escalated, pending_analyst_review", () => {
    const { rerender } = render(<StatusPill type="status_pill" status_key="under_review" />);
    expect(screen.getByText("Đang xem xét")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="draft" />);
    expect(screen.getByText("Bản nháp")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="submitted" />);
    expect(screen.getByText("Đã gửi")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="escalated" />);
    expect(screen.getByText("Đã chuyển thẩm định")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="pending_analyst_review" />);
    expect(screen.getByText("Chờ chuyên viên thẩm định")).toBeInTheDocument();
  });

  it("hides pill completely when status_key is empty or whitespace", () => {
    const { container, rerender } = render(<StatusPill type="status_pill" status_key="" />);
    expect(container.firstChild).toBeNull();

    rerender(<StatusPill type="status_pill" status_key="   " />);
    expect(container.firstChild).toBeNull();
  });

  it("renders English status labels when labels prop is provided", () => {
    const { rerender } = render(
      <StatusPill type="status_pill" status_key="under_review" labels={EN_LABELS} />
    );
    expect(screen.getByText("Under review")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="draft" labels={EN_LABELS} />);
    expect(screen.getByText("Draft")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="submitted" labels={EN_LABELS} />);
    expect(screen.getByText("Submitted")).toBeInTheDocument();

    rerender(<StatusPill type="status_pill" status_key="escalated" labels={EN_LABELS} />);
    expect(screen.getByText("Escalated")).toBeInTheDocument();

    rerender(
      <StatusPill type="status_pill" status_key="pending_analyst_review" labels={EN_LABELS} />
    );
    expect(screen.getByText("Pending analyst review")).toBeInTheDocument();
  });
});

describe("EvidenceBlockComponent", () => {
  const sampleEvidence: EvidenceBlock = {
    type: "evidence",
    items: [
      { kind: "weather", summary: "Mưa to diện rộng lúc 14:10", source: "Radar thời tiết" },
      { kind: "traffic", summary: "Ùn tắc cục bộ đường Nguyễn Huệ", source: "Hệ thống giám sát giao thông" },
      { kind: "telemetry", summary: "Định vị GPS khớp 100% với hộp đen" },
      { kind: "policy", summary: "Khoản 4 Điều 12 Quy chế đón trả khách" },
    ],
  };

  it("renders evidence items with summaries and sources", () => {
    render(<EvidenceBlockComponent {...sampleEvidence} />);

    expect(screen.getByText("Mưa to diện rộng lúc 14:10")).toBeInTheDocument();
    expect(screen.getByText(/Radar thời tiết/)).toBeInTheDocument();
    expect(screen.getByText("Ùn tắc cục bộ đường Nguyễn Huệ")).toBeInTheDocument();
    expect(screen.getByText("Định vị GPS khớp 100% với hộp đen")).toBeInTheDocument();
    expect(screen.getByText("Khoản 4 Điều 12 Quy chế đón trả khách")).toBeInTheDocument();
  });

  it("renders with English labels when labels prop is supplied", () => {
    render(<EvidenceBlockComponent {...sampleEvidence} labels={EN_LABELS} />);

    expect(screen.getByText("Recorded Evidence & Data")).toBeInTheDocument();
    expect(screen.getByText("Weather")).toBeInTheDocument();
    expect(screen.getByText("Traffic")).toBeInTheDocument();
    expect(screen.getByText("Telemetry")).toBeInTheDocument();
    expect(screen.getByText("Policy")).toBeInTheDocument();
  });

  it("returns null when evidence items are empty", () => {
    const { container } = render(<EvidenceBlockComponent type="evidence" items={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("NextSteps", () => {
  const sampleNextSteps: NextStepsBlock = {
    type: "next_steps",
    items: [
      { label: "Gửi ảnh camera", prompt: "Tôi muốn gửi ảnh camera hành trình" },
      { label: "Xem lộ trình GPS", prompt: "Xem lại bản đồ lộ trình GPS cuốc xe này" },
    ],
  };

  it("calls onPrompt when prompt chips are clicked", () => {
    const onPrompt = vi.fn();
    render(<NextSteps {...sampleNextSteps} onPrompt={onPrompt} />);

    const chip1 = screen.getByRole("button", { name: /Gửi ảnh camera/i });
    fireEvent.click(chip1);
    expect(onPrompt).toHaveBeenCalledWith("Tôi muốn gửi ảnh camera hành trình");

    const chip2 = screen.getByRole("button", { name: /Xem lộ trình GPS/i });
    fireEvent.click(chip2);
    expect(onPrompt).toHaveBeenCalledWith("Xem lại bản đồ lộ trình GPS cuốc xe này");
  });

  it("renders with English labels when labels prop is supplied", () => {
    render(<NextSteps {...sampleNextSteps} labels={EN_LABELS} />);
    expect(screen.getByText("Next steps:")).toBeInTheDocument();
  });

  it("returns null when next_steps items are empty", () => {
    const { container } = render(<NextSteps type="next_steps" items={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("BlockRenderer", () => {
  it("renders all block types seamlessly through discriminator", () => {
    const onNavigate = vi.fn();
    const onPrompt = vi.fn();
    const statusLabel = vi.fn((k: string) => `Label: ${k}`);

    const blocks: Array<
      | CaseCardBlock
      | TripCardBlock
      | TableBlock
      | ClickableListBlock
      | LinkBlock
      | StatusPillBlock
      | EvidenceBlock
      | NextStepsBlock
    > = [
      { type: "case_card", case_id: "case-abcd-1234", title: "Test Case", status_key: "open" },
      {
        type: "trip_card",
        trip_id: "trip-xyz-123",
        pickup: "Điểm A",
        destination: "Điểm B",
        fare_vnd: 50000,
      },
      { type: "table", columns: ["Col1"], rows: [["Val1"]] },
      { type: "list", items: [{ label: "Item 1", href: "case://123" }] },
      { type: "link", label: "External", url: "https://example.com" },
      { type: "status_pill", status_key: "pending" },
      { type: "evidence", items: [{ kind: "weather", summary: "Nắng nóng" }] },
      { type: "next_steps", items: [{ label: "Bấm vào đây", prompt: "Prompt 1" }] },
    ];

    const { rerender } = render(
      <BlockRenderer
        block={blocks[0]}
        onNavigate={onNavigate}
        onPrompt={onPrompt}
        statusLabel={statusLabel}
      />
    );
    expect(screen.getByText("Test Case")).toBeInTheDocument();

    for (let i = 1; i < blocks.length; i++) {
      rerender(
        <BlockRenderer
          block={blocks[i]}
          onNavigate={onNavigate}
          onPrompt={onPrompt}
          statusLabel={statusLabel}
        />
      );
    }

    expect(screen.getByText("Bấm vào đây")).toBeInTheDocument();
  });

  it("propagates English labels when labels/t prop is passed", () => {
    const block: NextStepsBlock = {
      type: "next_steps",
      items: [{ label: "Appeal now", prompt: "I want to appeal" }],
    };

    render(<BlockRenderer block={block} labels={EN_LABELS} />);
    expect(screen.getByText("Next steps:")).toBeInTheDocument();
    expect(screen.getByText("Appeal now")).toBeInTheDocument();
  });

  it("renders multiple blocks when blocks array prop is supplied", () => {
    const blocks: Array<CaseCardBlock | LinkBlock> = [
      { type: "case_card", case_id: "c-1", title: "First Case", status_key: "open" },
      { type: "link", label: "Support FAQ", url: "https://greensm.vn/faq" },
    ];

    render(<BlockRenderer blocks={blocks} />);

    expect(screen.getByText("First Case")).toBeInTheDocument();
    expect(screen.getByText("Support FAQ")).toBeInTheDocument();
  });

  it("handles unknown or undefined block without crashing", () => {
    const { container: c1 } = render(<BlockRenderer block={undefined} />);
    expect(c1.firstChild).toBeNull();

    const { container: c2 } = render(
      <BlockRenderer block={{ type: "unknown" } as unknown as DriverChatBlock} />
    );
    expect(c2.firstChild).toBeNull();
  });
});

describe("Block helper utilities", () => {
  it("formats case ids and trip ids correctly", () => {
    expect(formatCaseId("case-abc1234")).toBe("#ABC1");
    expect(formatCaseId("")).toBe("#CASE");
    expect(formatTripId("trip-998877")).toBe("#GS-998877");
    expect(formatTripId("")).toBe("#GS-TRIP");
  });

  it("resolves default status labels with defaultStatusLabel helper", () => {
    expect(defaultStatusLabel("resolved")).toBe(VI_LABELS.status.resolved);
    expect(defaultStatusLabel("custom_status")).toBe("Custom Status");
    expect(defaultStatusLabel("resolved", EN_LABELS)).toBe("Resolved");
  });

  it("builds VI_LABELS and EN_LABELS from messages JSON under driverBlocks", () => {
    expect(VI_LABELS.trip).toBe("Chuyến đi");
    expect(EN_LABELS.trip).toBe("Trip");
    expect(VI_LABELS.evidenceKinds.weather).toBe("Thời tiết");
    expect(EN_LABELS.evidenceKinds.weather).toBe("Weather");
  });
});

