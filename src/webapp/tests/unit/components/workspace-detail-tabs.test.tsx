import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { WorkflowTab } from "@/components/adjudication/workflow-tab";
vi.mock("@/lib/locale", () => ({ useLocale: () => ({ locale: "en", setLocale: vi.fn() }) }));
vi.mock("@/lib/api-client", () => ({ fetchCaseDriverScorecard: vi.fn() }));
const detail: any = { case: { id: "case-1" }, trip: { driver_id: "drv-1", driver_statement: "I was delayed.", passenger_statement: "The car waited." }, conversation: [] };
describe("workspace detail tabs", () => {
  it("uses case-level driver identity when trip identity is absent", () => {
    render(<DriverInfoTab caseDetail={{ ...detail, case: { ...detail.case, driver_name: "Case driver", vehicle_plate: "30C-999" }, trip: { ...detail.trip, driver_name: undefined, vehicle_plate: undefined, plate: undefined } }} scorecard={null} />);
    expect(screen.getByTitle("Name")).toBeInTheDocument();
    expect(screen.getByText("Case driver")).toBeInTheDocument();
    expect(screen.getByTitle("Vehicle plate")).toBeInTheDocument();
    expect(screen.getByText("30C-999")).toBeInTheDocument();
  });
  it("shows trip metrics and identity even when history is unavailable", () => {
    const tripDetail = { ...detail, trip: { ...detail.trip, rating: 4.9, acceptance_rate: 0.92, cancellation_rate: 0.03, total_trips: 120, driver_name: "Mai", vehicle_plate: "30A-123", status: "active" } };
    render(<DriverInfoTab caseDetail={tripDetail} scorecard={null} />);
    expect(screen.getByText("4.9")).toBeInTheDocument(); expect(screen.getByText(/Mai/)).toBeInTheDocument(); expect(screen.getByText(/30A-123/)).toBeInTheDocument(); expect(screen.getAllByText(/No data yet/).length).toBeGreaterThan(0);
  });
  it("keeps customer evidence read-only and excludes relay transcript", () => { render(<ConversationTab caseDetail={{ ...detail, conversation: [{ role: "driver", text: "First" }] }} disputeDossier={{ transcript: [{ id: "b", content: "Second" }] } as any} />); expect(screen.queryByText("I was delayed.")).not.toBeInTheDocument(); expect(screen.getByText("The car waited.")).toBeInTheDocument(); expect(screen.getByText("First")).toBeInTheDocument(); expect(screen.queryByText(/Second/)).not.toBeInTheDocument(); expect(screen.queryByRole("textbox")).not.toBeInTheDocument(); });
  it("masks raw workflow labels before AI reveal while retaining timestamps and local draft", () => { render(<WorkflowTab caseDetail={detail} caseWorkflowTrace={{ timeline: [{ label: "Trip received", occurred_at: "2026-01-01" }], agent_tools_called: [] } as any} />); expect(screen.getByText("Recorded workflow event")).toBeInTheDocument(); expect(screen.getByText("2026-01-01")).toBeInTheDocument(); expect(screen.getByRole("textbox", { name: /draft/i })).toBeInTheDocument(); expect(screen.queryByText(/Trip received|confidence|recommendation|classification|14:31|completed \(4\/4\)/i)).not.toBeInTheDocument(); });
});
