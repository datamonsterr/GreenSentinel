import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { TripFacts } from "@/components/adjudication/overview-tab";
import { FinalizationTab } from "@/components/adjudication/finalization-tab";
import { MapLibreView } from "@/components/map/maplibre-view";
import { LocaleProvider } from "@/lib/locale";

describe("Preview acceptance refinement (#368, #379)", () => {
  describe("Item 1: DriverInfoTab unavailable metric cards", () => {
    const emptyDetail: any = {
      case: { id: "case-empty", driver_name: "Nguyen Van A", vehicle_plate: "29A-12345" },
      trip: {},
      conversation: [],
    };

    it("keeps an individually labeled unavailable card for every missing driver metric", () => {
      render(<LocaleProvider><DriverInfoTab caseDetail={emptyDetail} scorecard={null} /></LocaleProvider>);
      for (const label of ["Average rating", "Acceptance rate", "Cancellation rate", "Total trips"]) {
        const card = screen.getByTitle(label);
        expect(within(card).getByText(label)).toBeVisible();
        expect(within(card).getByText("No data yet")).toHaveClass("text-slate-500");
        expect(card).not.toHaveTextContent(/0%|^0$/);
      }
    });

    it("keeps missing history metrics explicit without inventing zero risk", () => {
      render(<LocaleProvider><DriverInfoTab caseDetail={emptyDetail} scorecard={{} as any} /></LocaleProvider>);
      for (const label of ["90-day violation ratio", "Fined ratio", "Repeat-offense risk", "Benchmark ratio", "Tenure"]) {
        expect(within(screen.getByTitle(label)).getByText("No data yet")).toHaveClass("text-slate-500");
      }
      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    });

    it("keeps available rating and unavailable peer metrics together for a partial profile", () => {
      render(<LocaleProvider><DriverInfoTab caseDetail={{ ...emptyDetail, trip: { rating: 4.85 } }} scorecard={null} /></LocaleProvider>);
      expect(within(screen.getByTitle("Average rating")).getByText("4.85")).toBeVisible();
      for (const label of ["Acceptance rate", "Cancellation rate", "Total trips"]) {
        expect(within(screen.getByTitle(label)).getByText("No data yet")).toBeVisible();
      }
    });
  });

  describe("Item 2: ConversationTab profile collapse, compact text, and turn pluralization", () => {
    it("collapses a missing customer statement into ONE designed empty state", () => {
      const emptyTripDetail: any = {
        case: { id: "case-conv-1" },
        trip: {},
        conversation: [],
      };
      render(
        <LocaleProvider>
          <ConversationTab caseDetail={emptyTripDetail} />
        </LocaleProvider>
      );
      const statement = screen.getByRole("region", { name: "Customer statement" });
      expect(within(statement).getByRole("status")).toHaveTextContent("No data yet");
      expect(statement).not.toHaveTextContent(/Unavailable|undefined/);
      // Should not render 3 separate unavailable sections
      expect(screen.queryByTitle(/^Customer statement: Unavailable$/i)).not.toBeInTheDocument();
      expect(screen.queryByTitle(/^Driver statement: Unavailable$/i)).not.toBeInTheDocument();
      expect(screen.queryByTitle(/^Customer rating: Unavailable$/i)).not.toBeInTheDocument();
    });

    it("renders only rows that have values when present", () => {
      const statementDetail: any = {
        case: { id: "case-conv-2" },
        trip: { passenger_statement: "Driver was late." },
        conversation: [],
      };
      render(
        <LocaleProvider>
          <ConversationTab caseDetail={statementDetail} />
        </LocaleProvider>
      );
      expect(screen.getByText("Driver was late.")).toBeInTheDocument();
      expect(screen.queryByTitle(/^Driver statement: Unavailable$/i)).not.toBeInTheDocument();
      expect(screen.queryByTitle(/^Customer rating: Unavailable$/i)).not.toBeInTheDocument();
    });

    it("correctly pluralizes turns (1 turn vs N turns, VI 'lượt')", () => {
      const singleTurn: any = {
        case: { id: "case-turn-1" },
        trip: {},
        conversation: [{ role: "customer", text: "Hello" }],
      };
      const { rerender } = render(
        <LocaleProvider>
          <ConversationTab caseDetail={singleTurn} />
        </LocaleProvider>
      );
      expect(screen.getByText("1 turn")).toBeInTheDocument();

      const multiTurn: any = {
        case: { id: "case-turn-2" },
        trip: {},
        conversation: [{ role: "customer", text: "Hello" }, { role: "driver", text: "Hi" }],
      };
      rerender(
        <LocaleProvider>
          <ConversationTab caseDetail={multiTurn} />
        </LocaleProvider>
      );
      expect(screen.getByText("2 turns")).toBeInTheDocument();

      localStorage.setItem("greensentinel.locale", "vi");
      render(
        <LocaleProvider>
          <ConversationTab caseDetail={singleTurn} />
        </LocaleProvider>
      );
      expect(screen.getByText("1 lượt")).toBeInTheDocument();
      localStorage.clear();
    });
  });

  describe("Item 3: TripFacts omits missing status badges", () => {
    it("renders no status or matching badge when both are missing, keeping the one-line row", () => {
      const missingDetail: any = {
        trip: {
          fare_amount_vnd: 50000,
          id: "TRIP-123",
        },
      };
      render(
        <LocaleProvider>
          <TripFacts caseDetail={missingDetail} />
        </LocaleProvider>
      );
      // Fare is formatted correctly
      expect(screen.getByText(/50,000 ₫/)).toBeInTheDocument();
      // Missing status and matching render no badge at all (no fabricated pill)
      expect(screen.queryByTitle(/Driver status|Matching/i)).not.toBeInTheDocument();
      // Only pickup and dropoff show the designed empty value; never "Unavailable"
      expect(screen.getAllByText("No data yet")).toHaveLength(2);
      expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    });
  });

  describe("Item 4: Maps panel header hides orphan ROUTE: label", () => {
    it("does not render ROUTE: label when candidateRoutes is empty", () => {
      const { container } = render(
        <LocaleProvider>
          <MapLibreView caseId="test-case" candidateRoutes={[]} />
        </LocaleProvider>
      );
      // "Route:" or "ROUTE:" should not appear as an orphan label in the controls
      const routeLabels = container.querySelectorAll("span.font-mono.uppercase");
      expect(routeLabels.length).toBe(0);
    });
  });

  describe("Item 5: FinalizationTab delta localization", () => {
    const baseDetail: any = {
      case: { id: "case-fin", version: 1 },
      assessment: { category: "ERR-01", confidence: 85 },
      forensic_brief: { summary_text: "Observed drift" },
      preliminary_judgment: { id: "pj-1", case_id: "case-fin", judgment: "Nghi ngờ vi phạm" },
    };

    it("renders human-readable phrase for match and mismatch and omits when empty", () => {
      const { rerender } = render(
        <LocaleProvider>
          <FinalizationTab
            caseDetail={baseDetail}
            isActive
            canWrite
            busy={false}
            choice=""
            onChoice={vi.fn()}
            note=""
            onNote={vi.fn()}
            savingJudgment={false}
            onSaveJudgment={vi.fn()}
            rationale="Valid rationale for testing"
            onRationale={vi.fn()}
            onDecision={vi.fn()}
            delta="match"
          />
        </LocaleProvider>
      );
      const region = screen.getByRole("region", { name: "Counterargument" });
      expect(region).toHaveTextContent("Matches AI recommendation");
      expect(region).not.toHaveTextContent("delta: match");

      rerender(
        <LocaleProvider>
          <FinalizationTab
            caseDetail={baseDetail}
            isActive
            canWrite
            busy={false}
            choice=""
            onChoice={vi.fn()}
            note=""
            onNote={vi.fn()}
            savingJudgment={false}
            onSaveJudgment={vi.fn()}
            rationale="Valid rationale for testing"
            onRationale={vi.fn()}
            onDecision={vi.fn()}
            delta="mismatch"
          />
        </LocaleProvider>
      );
      expect(region).toHaveTextContent("Differs from AI recommendation");
      expect(region).not.toHaveTextContent("delta: mismatch");

      localStorage.setItem("greensentinel.locale", "vi");
      const { unmount: unmountVi } = render(
        <LocaleProvider>
          <FinalizationTab
            caseDetail={baseDetail}
            isActive
            canWrite
            busy={false}
            choice=""
            onChoice={vi.fn()}
            note=""
            onNote={vi.fn()}
            savingJudgment={false}
            onSaveJudgment={vi.fn()}
            rationale="Valid rationale for testing"
            onRationale={vi.fn()}
            onDecision={vi.fn()}
            delta="match"
          />
        </LocaleProvider>
      );
      const regionVi = screen.getByRole("region", { name: "Phản biện" });
      expect(regionVi).toHaveTextContent("Trùng khớp với khuyến nghị AI");
      unmountVi();
      localStorage.clear();

      rerender(
        <LocaleProvider>
          <FinalizationTab
            caseDetail={baseDetail}
            isActive
            canWrite
            busy={false}
            choice=""
            onChoice={vi.fn()}
            note=""
            onNote={vi.fn()}
            savingJudgment={false}
            onSaveJudgment={vi.fn()}
            rationale="Valid rationale for testing"
            onRationale={vi.fn()}
            onDecision={vi.fn()}
            delta=""
          />
        </LocaleProvider>
      );
      expect(screen.getByRole("region", { name: "Counterargument" })).not.toHaveTextContent(/Matches|Differs|delta:/i);
    });
  });
});
