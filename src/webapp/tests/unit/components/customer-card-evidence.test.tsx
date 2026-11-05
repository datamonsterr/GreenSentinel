import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { LocaleProvider } from "@/lib/locale";

describe("Customer tab Customer card", () => {
  it("shows customer feedback and customer rating, and does not show driver statement in the customer card", () => {
    const detail: any = {
      case: { id: "case-cust-1" },
      trip: {
        passenger_statement: "Passenger was waiting at gate 3.",
        driver_statement: "I arrived on time at gate 1.",
        customer_rating: 4.5,
      },
      conversation: [],
    };

    render(
      <LocaleProvider>
        <ConversationTab caseDetail={detail} />
      </LocaleProvider>
    );

    // Customer feedback is present
    expect(screen.getByText("Passenger was waiting at gate 3.")).toBeInTheDocument();
    // Customer rating is present
    expect(screen.getByText("4.5")).toBeInTheDocument();
    // Driver statement is NOT in the Customer card
    expect(screen.queryByText("I arrived on time at gate 1.")).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Driver statement:/)).not.toBeInTheDocument();
  });

  it("remains read-only and excludes driver statement even when dispute dossier is provided", () => {
    const detail: any = {
      case: { id: "case-cust-2" },
      trip: {
        passenger_statement: "Wrong route taken.",
      },
      conversation: [],
    };
    const dossier: any = {
      driver_statement: "Driver explains road detour due to barrier.",
    };

    render(
      <LocaleProvider>
        <ConversationTab caseDetail={detail} disputeDossier={dossier} />
      </LocaleProvider>
    );

    expect(screen.getByText("Wrong route taken.")).toBeInTheDocument();
    expect(screen.queryByText("Driver explains road detour due to barrier.")).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Driver statement:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
