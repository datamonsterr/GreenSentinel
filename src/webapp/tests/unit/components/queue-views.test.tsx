import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { AnalyticsDashboardView } from '@/components/views/analytics-view';
import { AnalystProfileView } from '@/components/views/profile-view';
import * as api from '@/lib/api-client';

it('derives queue priorities from persisted cases', async () => {
  vi.spyOn(api, 'fetchAnalyticsMetrics').mockResolvedValue({
    scope: 'organization',
    organization_id: 'org-test',
    window_days: 30,
    generated_at: '2026-10-05T00:00:00Z',
    queue: {
      total_cases: 1,
      active_backlog: 1,
      pending_driver_confirmation: 0,
      claimed_cases: 0,
      available_unclaimed: 1,
      priority_distribution: { P0: 0, P1: 1, P2: 0 },
    },
    dispositions: {
      driver_confirmed_resolutions: 0,
      analyst_adjudications_total: 0,
      analyst_decisions_breakdown: {},
      auto_dismissed_count: 0,
    },
    categories: { 'ERR-01': 1 },
    performance: {
      average_mttr_seconds: 120,
      hitl_enforcement_ratio_pct: 100,
      reviewer_concordance_pct: null,
    },
    health: {
      database_healthy: true,
      worker_status: 'active',
      environment: 'production',
    },
  });
  vi.spyOn(api, 'fetchObservabilitySummary').mockResolvedValue({
    scope: 'single-process; bounded to the most recent 1000 runs; resets on restart',
    process_started_at: '2026-10-01T00:00:00Z',
    run_count: 1,
    latency_ms: { sample_count: 1, p50: 120, p95: 120 },
    runs: { error_count: 0, timeout_count: 0, sample_count: 1 },
    tools: { call_count: 1, success_count: 1, failure_count: 0, sample_count: 1, success_rate_pct: 100 },
    model: {
      name: 'gemini-test',
      input_tokens: 10,
      output_tokens: 5,
      token_sample_count: 1,
      estimated_cost_usd: null,
      priced_sample_count: 0,
      active_prompt_version: 'prompt-v1',
    },
    quality: {
      grounding_error_count: 0,
      grounding_sample_count: 1,
      guardrail_violation_count: 0,
      guardrail_sample_count: 1,
    },
    benchmark: {
      status: 'available',
      sample_count: 100,
      dataset_version: null,
      current_dataset_version: 'abc123',
      artifact_version: 'def456',
      dataset_path: 'eval/golden_set/rag_testset_100.json',
      result_path: 'eval/results/rag_benchmark_results.json',
      benchmark_model_version: 'gemini-test',
      benchmark_prompt_version: 'prompt-v1',
      metrics: { retrieval_top3_accuracy_pct: 68 },
    },
    tracing: {
      provider: 'LangSmith',
      project: 'greensentinel-agent-runtime',
      project_url: 'https://smith.langchain.com',
      enabled: true,
      environment: 'test',
    },
  });

  render(<AnalyticsDashboardView />);
  expect(await screen.findByText(/Live organization snapshot of 1 cases/)).toBeInTheDocument();
  expect(screen.getByText('P1: 1')).toBeInTheDocument();
  expect(await screen.findByText('Agent observability')).toBeInTheDocument();
  expect(screen.getByText('120 / 120 ms')).toBeInTheDocument();
  expect(screen.getByText(/100 samples/)).toBeInTheDocument();
  expect(screen.getByText('68%')).toBeInTheDocument();
});

it('shows authenticated profile and owned case instead of fabricated audit', async () => {
  vi.spyOn(api, 'fetchCurrentAnalyst').mockResolvedValue({ id: 'analyst-real', name: 'Real analyst', role: 'analyst', roles: ["analyst"] });
  vi.spyOn(api, 'fetchCases').mockResolvedValue({
    items: [
      {
        id: 'case-a',
        driver_name: 'Stored driver',
        assigned_analyst_id: 'analyst-real',
        priority: 'P1',
        priority_score: 2,
        status: 'in_review',
        version: 1,
      },
    ],
    total: 1,
    limit: 100,
    offset: 0,
  });
  const resume = vi.fn();
  render(<AnalystProfileView onResumeCase={resume} />);
  expect(await screen.findByText('Real analyst')).toBeInTheDocument();
  expect(screen.getByText(/Stored driver/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Open workspace' }));
  expect(resume).toHaveBeenCalled();
});
