import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import WorkplacePage from "@/app/workplace/page";
import { LocaleProvider } from "@/lib/locale";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, getToken: vi.fn(async () => null) }),
  OrganizationSwitcher: () => <span>Org</span>,
  UserButton: () => <span>User</span>,
}));
vi.mock("@/components/map/maplibre-view", () => ({
  MapLibreView: () => <div data-testid="map-boundary" />,
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api-client")>(),
  setApiTokenProvider: vi.fn(),
  fetchCases: vi.fn(async () => ({ items: [], total: 0, limit: 50, offset: 0 })),
  fetchCurrentAnalyst: vi.fn(async () => ({ id: "analyst-1", name: "Analyst", role: "analyst" })),
  fetchCaseDetail: vi.fn(),
  fetchForensicBrief: vi.fn(),
  fetchCasePolicy: vi.fn(),
  fetchAgentSession: vi.fn(),
  getDisputeDossier: vi.fn(),
  getCaseWorkflowTrace: vi.fn(),
  subscribeCaseStream: vi.fn(() => () => {}),
}));

describe("Header language toggle", () => {
  it("renders compact EN and VI on small screens with full accessible names", async () => {
    render(
      <LocaleProvider>
        <WorkplacePage />
      </LocaleProvider>
    );

    // Full accessible names for screen readers
    const enButton = await screen.findByRole("button", { name: "Switch language to English" });
    const viButton = screen.getByRole("button", { name: "Switch language to Vietnamese" });
    expect(enButton).toBeInTheDocument();
    expect(viButton).toBeInTheDocument();

    // Contains both compact abbreviation for mobile (<640px) and full text for desktop
    expect(enButton.querySelector(".sm\\:hidden")).toHaveTextContent("EN");
    expect(enButton.querySelector(".hidden.sm\\:inline")).toHaveTextContent("English");
    expect(viButton.querySelector(".sm\\:hidden")).toHaveTextContent("VI");
    expect(viButton.querySelector(".hidden.sm\\:inline")).toHaveTextContent("Tiếng Việt");
  });
});
