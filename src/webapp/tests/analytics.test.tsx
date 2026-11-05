import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AnalyticsDashboardView } from "@/components/views/analytics-view";
import * as api from "@/lib/api-client";
import { AnalyticsMetricsResponse, ObservabilitySummary } from "@/types/schemas";

const mockAnalyticsResponse: AnalyticsMetricsResponse = {
  scope: "organization",
  organization_id: "org-greensentinel",
  window_days: 30,
  generated_at: "2026-10-05T08:00:00Z",
  queue: {
    total_cases: 125,
    active_backlog: 82,
    pending_driver_confirmation: 14,
    claimed_cases: 8,
    available_unclaimed: 74,
    priority_distribution: { P0: 12, P1: 38, P2: 32 },
  },
  dispositions: {
    driver_confirmed_resolutions: 19,
    analyst_adjudications_total: 24,
    analyst_decisions_breakdown: {
      AGREE: 10,
      DISAGREE: 8,
    },
    auto_dismissed_count: 5,
  },
  categories: {
    "ERR-01": 45,
    "ERR-02": 30,
    "ERR-03": 25,
    "ERR-05": 25,
  },
  performance: {
    average_mttr_seconds: 245.5,
    hitl_enforcement_ratio_pct: 95.8,
    reviewer_concordance_pct: null,
  },
  health: {
    database_healthy: true,
    worker_status: "active",
    environment: "production",
  },
};

const mockObservabilitySummary: ObservabilitySummary = {
  scope: "production-agent-runtime",
  process_started_at: "2026-10-01T00:00:00Z",
  run_count: 1420,
  latency_ms: { sample_count: 1420, p50: 310, p95: 850 },
  runs: { error_count: 3, timeout_count: 1, sample_count: 1420 },
  tools: {
    call_count: 2850,
    success_count: 2800,
    failure_count: 50,
    sample_count: 2850,
    success_rate_pct: 98.2,
  },
  model: {
    name: "gemini-2.5-pro",
    input_tokens: 450000,
    output_tokens: 120000,
    token_sample_count: 1420,
    estimated_cost_usd: "12.45",
    priced_sample_count: 1420,
    active_prompt_version: "sentinel-v2.1",
  },
  quality: {
    grounding_error_count: 2,
    grounding_sample_count: 1420,
    guardrail_violation_count: 0,
    guardrail_sample_count: 1420,
  },
  benchmark: {
    status: "available",
    sample_count: 100,
    dataset_version: "golden-v1",
    current_dataset_version: "golden-v1",
    artifact_version: "art-v1",
    dataset_path: "eval/golden_set/rag_testset_100.json",
    result_path: "eval/results/rag_benchmark_results.json",
    benchmark_model_version: "gemini-2.5-pro",
    benchmark_prompt_version: "sentinel-v2.1",
    metrics: { accuracy_pct: 94.5 },
  },
  tracing: {
    provider: "LangSmith",
    project: "greensentinel-agent-runtime",
    project_url: "https://smith.langchain.com",
    enabled: true,
    environment: "production",
  },
};

describe("AnalyticsDashboardView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders uncapped queue metrics, KPI cards, and breakdowns", async () => {
    const fetchSpy = vi.spyOn(api, "fetchAnalyticsMetrics").mockResolvedValue(mockAnalyticsResponse);
    vi.spyOn(api, "fetchObservabilitySummary").mockResolvedValue(mockObservabilitySummary);

    render(<AnalyticsDashboardView />);

    expect(await screen.findByText(/Live organization snapshot of 125 cases/)).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(30);

    // KPI cards
    expect(screen.getByText("Active Backlog")).toBeInTheDocument();
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("P0: 12")).toBeInTheDocument();
    expect(screen.getByText("P1: 38")).toBeInTheDocument();
    expect(screen.getByText("P2: 32")).toBeInTheDocument();

    expect(screen.getByText("Pending Driver Confirmation")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();

    expect(screen.getByText("Adjudicated (30d)")).toBeInTheDocument();
    // 24 analyst + 19 driver confirmed = 43
    expect(screen.getByText("43")).toBeInTheDocument();
    expect(screen.getByText(/24 analyst · 19 driver confirmed/)).toBeInTheDocument();

    // MTTR formatting: 245.5s = 4m 6s
    expect(screen.getByText("Average MTTR")).toBeInTheDocument();
    expect(screen.getByText("4m 6s")).toBeInTheDocument();
    expect(screen.getByText(/HITL enforcement: 95.8%/)).toBeInTheDocument();

    // Queue Capacity
    expect(screen.getByText("Available Unclaimed")).toBeInTheDocument();
    expect(screen.getByText("74")).toBeInTheDocument();
    expect(screen.getByText("Active Review Leases")).toBeInTheDocument();
    expect(screen.getAllByText("8")).toHaveLength(2); // In active leases and in DISAGREE decisions

    // Driver vs Analyst outcomes
    expect(screen.getByText("Driver Exonerations")).toBeInTheDocument();
    expect(screen.getByText("19")).toBeInTheDocument();
    expect(screen.getByText("Auto Dismissed")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();

    // Analyst verdicts
    expect(screen.getByText("AGREE")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("DISAGREE").parentElement).toHaveTextContent("8");

    // Category distribution
    expect(screen.getByText(/ERR-01 · Fare & Route Deviation/)).toBeInTheDocument();
    expect(screen.getByText(/45 \(36%\)/)).toBeInTheDocument();

    // Observability
    expect(screen.getByText("Agent observability")).toBeInTheDocument();
    expect(screen.getByText("$12.45")).toBeInTheDocument();
  });

  it("handles window filter switching (7d, 30d, 90d)", async () => {
    const fetchSpy = vi.spyOn(api, "fetchAnalyticsMetrics").mockResolvedValue(mockAnalyticsResponse);
    vi.spyOn(api, "fetchObservabilitySummary").mockResolvedValue(mockObservabilitySummary);

    render(<AnalyticsDashboardView />);
    await screen.findByText(/Live organization snapshot/);

    const btn7d = screen.getByRole("button", { name: "7d" });
    fireEvent.click(btn7d);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(7);
    });

    const btn90d = screen.getByRole("button", { name: "90d" });
    fireEvent.click(btn90d);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(90);
    });
  });

  it("handles error state gracefully", async () => {
    vi.spyOn(api, "fetchAnalyticsMetrics").mockRejectedValue(new Error("Database connection failure"));
    vi.spyOn(api, "fetchObservabilitySummary").mockResolvedValue(mockObservabilitySummary);

    render(<AnalyticsDashboardView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Database connection failure");
  });

  it("handles uncalibrated MTTR and missing hitl ratio", async () => {
    const uncalibratedResponse: AnalyticsMetricsResponse = {
      ...mockAnalyticsResponse,
      performance: {
        average_mttr_seconds: null,
        hitl_enforcement_ratio_pct: null,
        reviewer_concordance_pct: null,
      },
    };
    vi.spyOn(api, "fetchAnalyticsMetrics").mockResolvedValue(uncalibratedResponse);
    vi.spyOn(api, "fetchObservabilitySummary").mockResolvedValue(mockObservabilitySummary);

    render(<AnalyticsDashboardView />);

    await screen.findByText(/Live organization snapshot/);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("HITL ratio: uncalibrated")).toBeInTheDocument();
  });
});
