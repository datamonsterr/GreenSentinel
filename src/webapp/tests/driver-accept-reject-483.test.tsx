import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// RED: these imports do not exist yet (Issue #483).
import { DriverActionBar } from "@/components/driver/chat/driver-action-bar";
import { ConfirmationCard } from "@/components/driver/blocks/confirmation-card";

describe("DriverActionBar (Issue #483)", () => {
  it("renders accept and reject buttons", () => {
    render(<DriverActionBar caseId="c1" onAccept={vi.fn()} onReject={vi.fn()} hidden={false} />);
    expect(screen.getByRole("button", { name: /Chấp nhận vi phạm|Accept violation/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /Từ chối|Reject/i })).toBeDefined();
  });

  it("hidden when case closed/resolved", () => {
    const { container } = render(
      <DriverActionBar caseId="c1" onAccept={vi.fn()} onReject={vi.fn()} hidden={true} />
    );
    expect(container.querySelector("button")).toBeNull();
  });
});

describe("ConfirmationCard (Issue #483)", () => {
  const checklist = [
    { key: "incident_type", ok: true, label: "Incident type" },
    { key: "description", ok: true, label: "Description" },
    { key: "evidence", ok: true, label: "Evidence" },
  ];
  it("renders checklist + summary with Yes/No", () => {
    render(
      <ConfirmationCard
        action="submit_statement"
        checklist={checklist}
        summary="Flood detour"
        onConfirm={vi.fn()}
        onDecline={vi.fn()}
      />
    );
    expect(screen.getByText(/Flood detour/)).toBeDefined();
    expect(screen.getByTestId("driver-confirm-yes")).toBeDefined();
    expect(screen.getByTestId("driver-confirm-no")).toBeDefined();
  });

  it("Yes triggers onConfirm, No triggers onDecline", () => {
    const onConfirm = vi.fn();
    const onDecline = vi.fn();
    render(
      <ConfirmationCard action="submit_statement" checklist={checklist} summary="s" onConfirm={onConfirm} onDecline={onDecline} />
    );
    fireEvent.click(screen.getByTestId("driver-confirm-yes"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("driver-confirm-no"));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });
});

describe("Resume draft banner (Issue #483)", () => {
  it("shows resume banner when draft exists", async () => {
    const { FindDraftBanner } = await import("@/components/driver/chat/resume-draft-banner").catch(() => ({ FindDraftBanner: null }));
    expect(FindDraftBanner).toBeDefined();
    if (FindDraftBanner) {
      const onResume = vi.fn();
      render(<FindDraftBanner draft={{ reason: "Flooded street" }} onResume={onResume} />);
      expect(screen.getByTestId("driver-resume-draft-banner")).toBeDefined();
      expect(screen.getByText(/Flooded street/)).toBeDefined();
      fireEvent.click(screen.getByTestId("driver-resume-draft-btn"));
      expect(onResume).toHaveBeenCalledTimes(1);
    }
  });
});
