import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkflowTab } from "@/components/adjudication/workflow-tab";
import { OverviewTab } from "@/components/adjudication/overview-tab";
import { saveCaseWorkflowDraft } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ saveCaseWorkflowDraft: vi.fn() }));
afterEach(() => vi.clearAllMocks());

const detail = (id: string, version = 1, status = "in_review") => ({
  case: { id, version, status }, workflow_draft: { text: `${id} draft`, version },
} as any);

describe("workflow draft persistence", () => {
  it("uses the returned version for a second save", async () => {
    vi.mocked(saveCaseWorkflowDraft)
      .mockResolvedValueOnce({ text: "edited", version: 2 })
      .mockResolvedValueOnce({ text: "edited again", version: 3 });
    render(<WorkflowTab caseDetail={detail("case-a")} canWrite />);
    const input = screen.getByRole("textbox", { name: /workflow draft/i });
    fireEvent.change(input, { target: { value: "edited" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => expect(saveCaseWorkflowDraft).toHaveBeenCalledWith("case-a", "edited", 1));
    fireEvent.change(input, { target: { value: "edited again" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => expect(saveCaseWorkflowDraft).toHaveBeenLastCalledWith("case-a", "edited again", 2));
  });

  it("does not publish a stale save completion after switching cases", async () => {
    let resolve!: (value: { text: string; version: number }) => void;
    vi.mocked(saveCaseWorkflowDraft).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    const view = render(<WorkflowTab caseDetail={detail("case-a")} canWrite />);
    fireEvent.change(screen.getByRole("textbox", { name: /workflow draft/i }), { target: { value: "edited" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    view.rerender(<WorkflowTab caseDetail={detail("case-b")} canWrite />);
    resolve({ text: "edited", version: 2 });
    await waitFor(() => expect(screen.getByRole("textbox", { name: /workflow draft/i })).toHaveValue("case-b draft"));
  });

  it("disables editing for an unclaimed or terminal case", () => {
    const { rerender } = render(<WorkflowTab caseDetail={detail("case-a")} />);
    expect(screen.getByRole("button", { name: /save draft/i })).toBeDisabled();
    rerender(<WorkflowTab caseDetail={detail("case-a", 2, "resolved")} canWrite />);
    expect(screen.getByRole("button", { name: /save draft/i })).toBeDisabled();
  });
});

it("renders structured motivation and willingness assessments", () => {
  render(<OverviewTab caseDetail={{ ...detail("case-a"), cockpit_evidence: {
    motivation_assessment: { label: "Passenger dispute", source: "measured chat" },
    willingness_assessment: { assessment: "Driver cooperated", source: "relay" },
  } } as any} />);
  expect(screen.getByText("Passenger dispute · measured chat")).toBeInTheDocument();
  expect(screen.getByText("Driver cooperated · relay")).toBeInTheDocument();
});
