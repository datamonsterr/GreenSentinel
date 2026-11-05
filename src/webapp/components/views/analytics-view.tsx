"use client";

import React, { useEffect, useState } from "react";
import { fetchAnalyticsMetrics, fetchObservabilitySummary } from "@/lib/api-client";
import { AnalyticsMetricsResponse, ObservabilitySummary } from "@/types/schemas";
import { AnalyticsDashboardSkeleton } from "@/components/ui/skeleton";

const benchmarkRepositoryUrl = "https://github.com/AI20K-Build-Phase-Cohort-4/P-063/blob/main";

const CATEGORY_LABELS: Record<string, string> = {
  "ERR-01": "Fare & Route Deviation",
  "ERR-02": "Ghost Ride & Telemetry Disconnect",
  "ERR-03": "GPS Spoofing & Mock Location",
  "ERR-04": "Trip Milking & Prolonged Stall",
  "ERR-05": "Ping Gap & Device Manipulation",
};

function formatMttr(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

export function AnalyticsDashboardView() {
  const [analytics, setAnalytics] = useState<AnalyticsMetricsResponse | null>(null);
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [windowDays, setWindowDays] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);

    fetchAnalyticsMetrics(windowDays)
      .then((result) => {
        if (current) setAnalytics(result);
      })
      .catch((reason) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "Unable to load analytics metrics");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    fetchObservabilitySummary()
      .then((result) => {
        if (current) setSummary(result);
      })
      .catch((reason) => {
        if (current) {
          setSummaryError(reason instanceof Error ? reason.message : "Unable to load observability metrics");
        }
      });

    return () => {
      current = false;
    };
  }, [windowDays, revision]);

  if (loading && !analytics) return <AnalyticsDashboardSkeleton />;

  const queue = analytics?.queue;
  const dispositions = analytics?.dispositions;
  const performance = analytics?.performance;
  const health = analytics?.health;
  const categories = analytics?.categories || {};

  const totalAdjudications = (dispositions?.analyst_adjudications_total || 0) + (dispositions?.driver_confirmed_resolutions || 0);

  return (
    <section className="space-y-6 overflow-auto p-4">
      {/* Top Header & Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-3">
        <div>
          <h1 className="text-sm font-semibold text-slate-900">Operations analytics</h1>
          <p className="text-xs text-slate-500">
            Uncapped organization metrics & agent observability
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-0.5 text-xs">
            {[7, 30, 90].map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => setWindowDays(days)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  windowDays === days
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {days}d
              </button>
            ))}
          </div>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              setSummaryError(null);
              setRevision((v) => v + 1);
            }}
            className="rounded border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
          {error}
        </div>
      ) : queue ? (
        <>
          {/* Section 1: KPI Overview Cards */}
          <section className="space-y-3" aria-labelledby="queue-overview-heading">
            <div className="flex items-center justify-between">
              <h2 id="queue-overview-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Queue overview
              </h2>
              <span className="text-xs text-slate-500">
                Live organization snapshot of {queue.total_cases} cases
              </span>
            </div>

            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {/* Card 1: Active Backlog */}
              <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm">
                <dt className="text-xs font-medium text-slate-500">Active Backlog</dt>
                <dd className="mt-1 text-2xl font-bold text-slate-900">{queue.active_backlog}</dd>
                <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                  {(["P0", "P1", "P2"] as const).map((priority) => (
                    <span
                      key={priority}
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium border ${
                        priority === "P0"
                          ? "bg-rose-50 text-rose-700 border-rose-200"
                          : priority === "P1"
                          ? "bg-amber-50 text-amber-700 border-amber-200"
                          : "bg-slate-50 text-slate-700 border-slate-200"
                      }`}
                    >
                      {priority}: {queue.priority_distribution[priority] || 0}
                    </span>
                  ))}
                </div>
              </div>

              {/* Card 2: Driver Confirmation */}
              <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm">
                <dt className="text-xs font-medium text-slate-500">Pending Driver Confirmation</dt>
                <dd className="mt-1 text-2xl font-bold text-slate-900">
                  {queue.pending_driver_confirmation}
                </dd>
                <p className="mt-2.5 text-xs text-slate-500">Awaiting driver dispute statement</p>
              </div>

              {/* Card 3: Adjudicated in Window */}
              <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm">
                <dt className="text-xs font-medium text-slate-500">Adjudicated ({windowDays}d)</dt>
                <dd className="mt-1 text-2xl font-bold text-slate-900">{totalAdjudications}</dd>
                <p className="mt-2.5 text-xs text-slate-500">
                  {dispositions?.analyst_adjudications_total || 0} analyst · {dispositions?.driver_confirmed_resolutions || 0} driver confirmed
                </p>
              </div>

              {/* Card 4: Mean Time to Resolution */}
              <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm">
                <dt className="text-xs font-medium text-slate-500">Average MTTR</dt>
                <dd className="mt-1 text-2xl font-bold text-slate-900">
                  {formatMttr(performance?.average_mttr_seconds)}
                </dd>
                <p className="mt-2.5 text-xs text-slate-500">
                  {performance?.hitl_enforcement_ratio_pct !== null && performance?.hitl_enforcement_ratio_pct !== undefined
                    ? `HITL enforcement: ${performance.hitl_enforcement_ratio_pct}%`
                    : "HITL ratio: uncalibrated"}
                </p>
              </div>
            </dl>
          </section>

          {/* Section 2: Queue Health & Capacity */}
          <section className="space-y-3" aria-labelledby="queue-capacity-heading">
            <h2 id="queue-capacity-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Queue capacity & active leases
            </h2>
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div>
                  <dt className="text-xs text-slate-500">Total Cases</dt>
                  <dd className="mt-1 text-lg font-semibold text-slate-900">{queue.total_cases}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Available Unclaimed</dt>
                  <dd className="mt-1 text-lg font-semibold text-emerald-700">{queue.available_unclaimed}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Active Review Leases</dt>
                  <dd className="mt-1 text-lg font-semibold text-indigo-700">{queue.claimed_cases}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">System Health</dt>
                  <dd className="mt-1 flex items-center gap-1.5 text-xs font-medium text-slate-700">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${
                        health?.database_healthy ? "bg-emerald-500" : "bg-rose-500"
                      }`}
                    />
                    {health?.database_healthy ? "Healthy" : "Degraded"} · {health?.worker_status || "active"}
                  </dd>
                </div>
              </div>

              {/* Capacity Progress Bar */}
              {queue.total_cases > 0 && (
                <div className="mt-4 space-y-1.5">
                  <div className="flex justify-between text-[11px] text-slate-500">
                    <span>Available ({Math.round((queue.available_unclaimed / queue.total_cases) * 100)}%)</span>
                    <span>Claimed ({Math.round((queue.claimed_cases / queue.total_cases) * 100)}%)</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 flex">
                    <div
                      className="bg-emerald-500 transition-all"
                      style={{ width: `${(queue.available_unclaimed / queue.total_cases) * 100}%` }}
                    />
                    <div
                      className="bg-indigo-500 transition-all"
                      style={{ width: `${(queue.claimed_cases / queue.total_cases) * 100}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Section 3: Adjudication Outcomes & Decisions Breakdown */}
          <section className="space-y-3" aria-labelledby="dispositions-heading">
            <h2 id="dispositions-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Adjudication outcomes & driver resolution ({windowDays}d)
            </h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {/* Left: Driver Outcomes */}
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3">
                <h3 className="text-xs font-semibold text-slate-900">Autonomous Driver Resolution</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded border border-slate-100 bg-slate-50/50 p-3">
                    <dt className="text-xs text-slate-500">Driver Exonerations</dt>
                    <dd className="mt-1 text-xl font-bold text-emerald-700">
                      {dispositions?.driver_confirmed_resolutions || 0}
                    </dd>
                    <p className="mt-1 text-[11px] text-slate-500">Exonerated via statement</p>
                  </div>
                  <div className="rounded border border-slate-100 bg-slate-50/50 p-3">
                    <dt className="text-xs text-slate-500">Auto Dismissed</dt>
                    <dd className="mt-1 text-xl font-bold text-slate-700">
                      {dispositions?.auto_dismissed_count || 0}
                    </dd>
                    <p className="mt-1 text-[11px] text-slate-500">System policy threshold</p>
                  </div>
                </div>
              </div>

              {/* Right: Analyst Decisions Breakdown */}
              <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm space-y-3">
                <h3 className="text-xs font-semibold text-slate-900">Analyst Decision Breakdown</h3>
                {dispositions && Object.keys(dispositions.analyst_decisions_breakdown).length > 0 ? (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {Object.entries(dispositions.analyst_decisions_breakdown).map(([verdict, count]) => (
                      <div key={verdict} className="rounded border border-slate-100 bg-slate-50/50 p-2 text-center">
                        <span className="text-[11px] font-semibold uppercase text-slate-600">{verdict}</span>
                        <p className="mt-0.5 text-base font-bold text-slate-900">{count}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">No analyst decisions recorded in window.</p>
                )}
              </div>
            </div>
          </section>

          {/* Section 4: Suspected Category Distribution */}
          <section className="space-y-3" aria-labelledby="categories-heading">
            <h2 id="categories-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Suspected category distribution
            </h2>
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              {Object.keys(categories).length > 0 ? (
                <div className="space-y-3">
                  {Object.entries(categories).map(([code, count]) => {
                    const percentage = queue.total_cases > 0 ? Math.round((count / queue.total_cases) * 100) : 0;
                    return (
                      <div key={code} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-medium text-slate-800">
                            {code} · {CATEGORY_LABELS[code] || "Violation Category"}
                          </span>
                          <span className="text-slate-500">
                            {count} ({percentage}%)
                          </span>
                        </div>
                        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                          <div
                            className="h-full bg-emerald-600 transition-all rounded-full"
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-xs text-slate-500">No categories recorded.</p>
              )}
            </div>
          </section>
        </>
      ) : null}

      {/* Section 5: Agent Observability & Benchmark */}
      <section className="space-y-3" aria-labelledby="agent-observability-heading">
        <h2 id="agent-observability-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Agent observability
        </h2>
        {summaryError ? (
          <p role="alert" className="text-xs text-red-700">
            {summaryError}
          </p>
        ) : summary ? (
          <>
            <p className="text-xs text-slate-500">
              {summary.scope} · process started {new Date(summary.process_started_at).toLocaleString()}
            </p>
            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Metric
                label="Agent runs"
                value={summary.run_count}
                detail={`${summary.runs.error_count} errors · ${summary.runs.timeout_count} timeouts`}
              />
              <Metric
                label="Latency p50 / p95"
                value={`${summary.latency_ms.p50 ?? "—"} / ${summary.latency_ms.p95 ?? "—"} ms`}
                detail={`${summary.latency_ms.sample_count} samples`}
              />
              <Metric
                label="Tool success"
                value={summary.tools.success_rate_pct === null ? "—" : `${summary.tools.success_rate_pct}%`}
                detail={`${summary.tools.success_count}/${summary.tools.sample_count} calls`}
              />
              <Metric
                label="Estimated model cost"
                value={
                  summary.model.estimated_cost_usd === null
                    ? "Not configured"
                    : `$${summary.model.estimated_cost_usd}`
                }
                detail={`${summary.model.priced_sample_count} priced runs`}
              />
            </dl>

            <div className="grid grid-cols-1 gap-3 rounded border bg-white p-3 text-xs sm:grid-cols-2">
              <div>
                <h3 className="font-semibold text-slate-900">Runtime versions</h3>
                <p className="mt-1 text-slate-600">Model: {summary.model.name}</p>
                <p className="text-slate-600">Prompt: {summary.model.active_prompt_version}</p>
                <p className="text-slate-600">
                  Tokens: {summary.model.input_tokens ?? "—"} input / {summary.model.output_tokens ?? "—"} output (
                  {summary.model.token_sample_count} complete samples)
                </p>
                <p className="text-slate-600">
                  Grounding: {summary.quality.grounding_error_count ?? "—"} errors /{" "}
                  {summary.quality.grounding_sample_count} samples · guardrails:{" "}
                  {summary.quality.guardrail_violation_count ?? "—"} / {summary.quality.guardrail_sample_count}
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-slate-900">Benchmark</h3>
                <p className="mt-1 text-slate-600">
                  Status: {summary.benchmark.status} · {summary.benchmark.sample_count} samples
                </p>
                <p className="text-slate-600">
                  Artifact dataset version: {summary.benchmark.dataset_version ?? "not recorded"} · current dataset:{" "}
                  {summary.benchmark.current_dataset_version ?? "not found"}
                </p>
                <p className="text-slate-600">
                  Artifact version: {summary.benchmark.artifact_version ?? "not found"} · model:{" "}
                  {summary.benchmark.benchmark_model_version ?? "not recorded"} · prompt:{" "}
                  {summary.benchmark.benchmark_prompt_version ?? "not recorded"}
                </p>
                <a
                  className="mt-1 inline-block text-blue-700 underline"
                  href={`${benchmarkRepositoryUrl}/${summary.benchmark.dataset_path}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  View benchmark dataset
                </a>
                <a
                  className="ml-3 inline-block text-blue-700 underline"
                  href={`${benchmarkRepositoryUrl}/${summary.benchmark.result_path}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  View result artifact
                </a>
                {summary.benchmark.timestamp && (
                  <p className="text-slate-500">
                    Last artifact: {new Date(summary.benchmark.timestamp).toLocaleString()}
                  </p>
                )}
                {Object.entries(summary.benchmark.metrics).length > 0 ? (
                  <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                    {Object.entries(summary.benchmark.metrics).map(([name, value]) => (
                      <div key={name}>
                        <dt className="capitalize text-slate-500">{name.replaceAll("_", " ")}</dt>
                        <dd className="font-medium">
                          {value}
                          {name.endsWith("_pct") ? "%" : ""}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="mt-1 text-slate-500">No benchmark quality metrics in the artifact.</p>
                )}
                <p className="mt-1 text-slate-600">
                  Tracing: {summary.tracing.enabled ? "enabled" : "disabled"} · {summary.tracing.environment} ·{" "}
                  {summary.tracing.project}
                </p>
                <a
                  className="text-blue-700 underline"
                  href={summary.tracing.project_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open LangSmith
                </a>
              </div>
            </div>
          </>
        ) : (
          <p className="text-xs text-slate-500">Loading observability metrics…</p>
        )}
      </section>
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: React.ReactNode; detail: string }) {
  return (
    <div className="rounded border bg-white p-3 shadow-sm">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-1 text-lg font-semibold">{value}</dd>
      <p className="text-xs text-slate-500">{detail}</p>
    </div>
  );
}
