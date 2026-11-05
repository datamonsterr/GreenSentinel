import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConversationTab } from "@/components/adjudication/conversation-tab";

vi.mock("@/lib/locale", () => ({ useLocale: () => ({ locale: "en", setLocale: vi.fn() }) }));

describe("customer transcript preservation", () => {
  it("keeps same-turn question and reply, deduplicates exact duplicates, orders timestamps, and renders time", () => {
    render(<ConversationTab caseDetail={{ case: { id: "case-customer" }, trip: {}, conversation: [
      { role: "customer", text: "Where is the driver?", occurred_at: "2026-01-01T10:02:00Z", turn_id: "turn-1" } as any,
      { role: "agent", text: "The driver is approaching.", occurred_at: "2026-01-01T10:02:30Z", turn_id: "turn-1" } as any,
    ] } as any} disputeDossier={{ transcript: [
      { role: "customer", content: "Where is the driver?", timestamp: "2026-01-01T10:02:00Z" },
    ] } as any} />);
    expect(screen.getByText("Where is the driver?")).toBeInTheDocument();
    expect(screen.getByText("The driver is approaching.")).toBeInTheDocument();
    expect(screen.getAllByRole("time")).toHaveLength(2);
    expect(screen.getAllByText("Where is the driver?")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Driver–customer conversation" })).toBeInTheDocument();
    expect(screen.getByText("2 turns")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Conversation summary" })).toBeInTheDocument();
  });
});
