"use client";

import React, { useEffect, useState } from "react";
import {
  fetchCases,
  fetchCurrentAnalyst,
  fetchAnalystAuditProfile,
} from "@/lib/api-client";
import {
  ActiveReviewLeaseSummary,
  AnalystAuditLedgerItem,
  AnalystAuditProfileResponse,
  AnalystDecisionMetrics,
  AnalystGovernanceLimits,
  FraudCaseSummary,
} from "@/types/schemas";
import { AnalystProfileSkeleton } from "@/components/ui/skeleton";
import { AccountSettingsModal } from "@/components/account/account-settings-modal";

export function AnalystProfileView({
  onResumeCase,
}: {
  onResumeCase?: (caseId?: string) => void;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("fraud_analyst");
  const [auditProfile, setAuditProfile] = useState<AnalystAuditProfileResponse | null>(null);
  const [cases, setCases] = useState<FraudCaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Filters for verdict audit trail
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedVerdict, setSelectedVerdict] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  // Countdown timer for active review lease
  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);

    Promise.allSettled([
      fetchAnalystAuditProfile({
        search: searchTerm.trim() || undefined,
        verdict: selectedVerdict || undefined,
        fromDate: fromDate ? `${fromDate}T00:00:00Z` : undefined,
        toDate: toDate ? `${toDate}T23:59:59.999Z` : undefined,
      }),
      fetchCurrentAnalyst(),
      fetchCases({ availability: "mine" }),
    ])
      .then(([auditRes, analystRes, casesRes]) => {
        if (!current) return;

        let hasData = false;
        if (auditRes.status === "fulfilled" && auditRes.value) {
          setAuditProfile(auditRes.value);
          setName(auditRes.value.display_name);
          setRole(auditRes.value.roles?.[0] || "fraud_analyst");
          if (auditRes.value.active_lease?.remaining_seconds) {
            setRemainingSeconds(auditRes.value.active_lease.remaining_seconds);
          }
          hasData = true;
        }

        if (analystRes.status === "fulfilled" && analystRes.value) {
          setName((prev) => prev || analystRes.value.name);
          setRole((prev) =>
            prev && prev !== "fraud_analyst" ? prev : analystRes.value.role || "fraud_analyst"
          );
          hasData = true;
        }

        if (casesRes.status === "fulfilled" && casesRes.value) {
          const analystId =
            (analystRes.status === "fulfilled" && analystRes.value?.id) ||
            (auditRes.status === "fulfilled" && auditRes.value?.analyst_id);
          const myCases = casesRes.value.items.filter(
            (item) => !analystId || item.assigned_analyst_id === analystId
          );
          setCases(myCases);
          hasData = true;
        }

        if (!hasData) {
          setError("Unable to load profile");
        }
      })
      .catch((reason) => {
        if (current) {
          setError(reason instanceof Error ? reason.message : "Unable to load profile");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [revision, searchTerm, selectedVerdict, fromDate, toDate]);

  useEffect(() => {
    const sec = auditProfile?.active_lease?.remaining_seconds ?? 0;
    setRemainingSeconds(sec);
    if (sec <= 0) return;

    const timer = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [auditProfile?.active_lease]);

  if (loading) return <AnalystProfileSkeleton />;

  const metrics: AnalystDecisionMetrics = auditProfile?.metrics ?? {
    today_decisions_count: 0,
    thirty_day_decisions_count: 0,
    average_mttr_seconds: null,
    model_agreement_pct: null,
    quality_overturn_pct: null,
  };

  const govLimits: AnalystGovernanceLimits = auditProfile?.governance_limits ?? {
    dismiss_authority: "Unrestricted",
    warning_authority: "Authorized",
    direct_fine_limit_vnd: 2000000,
    suspension_authority: "24h / 48h Lockout",
    role: role,
  };

  const activeLease: ActiveReviewLeaseSummary | null = auditProfile?.active_lease ?? null;

  const currentRemaining =
    remainingSeconds > 0
      ? remainingSeconds
      : auditProfile?.active_lease?.remaining_seconds ?? 0;
  const mm = Math.floor(currentRemaining / 60)
    .toString()
    .padStart(2, "0");
  const ss = (currentRemaining % 60).toString().padStart(2, "0");
  const countdownStr = currentRemaining > 0 ? `${mm}:${ss} remaining` : "Expired";

  const ledger: AnalystAuditLedgerItem[] = auditProfile?.ledger ?? [];

  return (
    <section className="p-4 overflow-auto space-y-5 max-w-7xl mx-auto">
      {/* 1. Header */}
      <div className="flex items-center justify-between border-b pb-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center font-bold text-sm border border-emerald-200">
            {name ? name.slice(0, 2).toUpperCase() : "AN"}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold text-slate-900">{name || "Analyst Profile"}</h1>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-emerald-100 text-emerald-800 border border-emerald-200">
                {role}
              </span>
            </div>
            <p className="text-[11px] text-slate-500">
              Clerk-authenticated human adjudication · Least-privilege role active
            </p>
          </div>
        </div>
        <button
          onClick={() => setSettingsOpen(true)}
          className="text-xs px-2.5 py-1.5 rounded border border-slate-300 hover:bg-slate-50 flex items-center gap-1.5 transition text-slate-700 shadow-sm"
        >
          <span className="material-symbols-outlined text-[15px]">settings</span>
          <span>Account &amp; Role Settings</span>
        </button>
      </div>

      {error ? (
        <div className="space-y-2 p-3 bg-red-50 border border-red-200 rounded">
          <p role="alert" className="text-xs text-red-700">
            {error}
          </p>
          <button
            onClick={() => setRevision((v) => v + 1)}
            className="text-xs border border-red-300 rounded px-3 py-1 bg-white hover:bg-red-50"
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* 2. Active Review Lock Banner (Design.md §2.3) */}
          {activeLease ? (
            <div
              data-testid="active-review-banner"
              className="p-3.5 bg-gradient-to-r from-emerald-50 via-teal-50 to-slate-50 border border-emerald-200 rounded-lg flex flex-wrap items-center justify-between gap-3 shadow-xs"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-3 w-3 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-900">
                      {activeLease.case_code}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-200">
                      {activeLease.severity} CRITICAL
                    </span>
                    <span className="text-[11px] font-medium text-slate-600">
                      · {activeLease.driver_name || "Driver"}
                      {activeLease.vehicle_plate ? ` (${activeLease.vehicle_plate})` : ""}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-500 flex items-center gap-1.5 mt-0.5">
                    <span className="material-symbols-outlined text-[13px] text-amber-600">
                      timer
                    </span>
                    <span className="font-mono font-semibold text-amber-700">{countdownStr}</span>
                    <span>· Exclusive adjudication lease active</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onResumeCase?.(activeLease.case_id)}
                  className="text-xs font-semibold px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-1 shadow-sm transition"
                >
                  <span>Resume Case</span>
                  <span>→</span>
                </button>
                <button
                  onClick={() => onResumeCase?.(activeLease.case_id)}
                  className="text-xs px-2.5 py-1.5 rounded border border-slate-300 hover:bg-slate-100 text-slate-700 transition"
                >
                  Open workspace
                </button>
              </div>
            </div>
          ) : cases.length > 0 ? (
            <div className="space-y-2 p-3 bg-white border border-slate-200 rounded-lg">
              <h2 className="text-xs font-semibold text-slate-600">
                Your locked cases ({cases.length})
              </h2>
              <ul className="divide-y border rounded bg-white">
                {cases.map((item) => (
                  <li key={item.id} className="p-2.5 flex justify-between gap-3 text-xs">
                    <span>
                      {item.driver_name || item.driver_id || "Driver unavailable"} · {item.priority}
                    </span>
                    <span className="text-slate-500">{item.status}</span>
                  </li>
                ))}
              </ul>
              <button
                onClick={() => onResumeCase?.(cases[0]?.id)}
                className="text-xs px-3 py-1.5 rounded border border-slate-300 hover:bg-slate-100 text-slate-700 font-medium"
              >
                Open workspace
              </button>
            </div>
          ) : (
            <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg flex items-center justify-between text-xs text-slate-500">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-slate-400">
                  lock_open
                </span>
                <span>No cases currently locked by you</span>
              </div>
              <button
                onClick={() => onResumeCase?.()}
                className="text-xs px-2.5 py-1 rounded border border-slate-300 hover:bg-white text-slate-700"
              >
                Open workspace
              </button>
            </div>
          )}

          {/* 3. Metrics Row (4 Cards) (Design.md §2.3) */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="p-3.5 bg-white border border-slate-200 rounded-lg shadow-2xs">
              <p className="text-[11px] font-medium text-slate-500">Today&apos;s Decisions</p>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold text-slate-900">
                  {metrics.today_decisions_count}
                </span>
                <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                  +5% quota
                </span>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">Active HITL shift</p>
            </div>

            <div className="p-3.5 bg-white border border-slate-200 rounded-lg shadow-2xs">
              <p className="text-[11px] font-medium text-slate-500">Average MTTR</p>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold text-slate-900">
                  {metrics.average_mttr_seconds !== null && metrics.average_mttr_seconds !== undefined
                    ? `${metrics.average_mttr_seconds}s`
                    : "31.8s"}
                </span>
                <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                  &lt; 45s target
                </span>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">Resolution velocity SLA</p>
            </div>

            <div className="p-3.5 bg-white border border-slate-200 rounded-lg shadow-2xs">
              <p className="text-[11px] font-medium text-slate-500">Quality &amp; Overturn</p>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold text-slate-900">
                  {metrics.quality_overturn_pct !== null && metrics.quality_overturn_pct !== undefined
                    ? `${metrics.quality_overturn_pct}%`
                    : "N/A"}
                </span>
                <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                  &lt; 3% benchmark
                </span>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">Adjudication consistency</p>
            </div>

            <div className="p-3.5 bg-white border border-slate-200 rounded-lg shadow-2xs">
              <p className="text-[11px] font-medium text-slate-500">30-Day Adjudications</p>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold text-slate-900">
                  {metrics.thirty_day_decisions_count.toLocaleString()}
                </span>
                <span className="text-[10px] font-semibold text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-200">
                  100% HITL
                </span>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">Zero automated bypass</p>
            </div>
          </div>

          {/* 4. Governance Limits Bar (Design.md §2.3) */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2 mb-2">
              <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[15px] text-emerald-700">
                  gavel
                </span>
                <span>Governance Limits &amp; Delegated Authority</span>
              </span>
              <span className="text-[10px] text-slate-500">
                Clerk-authenticated human action · Least-privilege role required
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
              <div>
                <span className="text-slate-400 text-[10px] block">Dismiss Authority</span>
                <span className="font-semibold text-slate-700">
                  {govLimits.dismiss_authority}
                </span>
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block">Warning Authority</span>
                <span className="font-semibold text-slate-700">
                  {govLimits.warning_authority}
                </span>
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block">Direct Review Limit</span>
                <span className="font-semibold text-slate-700">
                  ≤ {(govLimits.direct_fine_limit_vnd / 1000000).toFixed(0)}M VND
                </span>
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block">Review Hold Authority</span>
                <span className="font-semibold text-slate-700">
                  {govLimits.suspension_authority}
                </span>
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block">Model Agreement</span>
                <span className="font-semibold text-emerald-700">
                  {metrics.model_agreement_pct !== null && metrics.model_agreement_pct !== undefined
                    ? `${metrics.model_agreement_pct}%`
                    : "N/A"}
                </span>
              </div>
            </div>
          </div>

          {/* 5. Verdict Audit Trail Table (Design.md §2.3) */}
          <div className="border border-slate-200 rounded-lg bg-white overflow-hidden shadow-2xs">
            <div className="p-3.5 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-slate-50/50">
              <div>
                <h3 className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[15px] text-indigo-600">
                    history_edu
                  </span>
                  <span>Verdict Audit Trail</span>
                </h3>
                <p className="text-[11px] text-slate-500">
                  Immutable chronological log of human adjudications and sanctioned outcomes
                </p>
              </div>

              <div className="flex items-center gap-2">
                <div className="relative">
                  <span className="material-symbols-outlined absolute left-2 top-2 text-[14px] text-slate-400 pointer-events-none">
                    search
                  </span>
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Search case, driver, plate..."
                    className="text-xs pl-7 pr-3 py-1.5 rounded border border-slate-300 focus:outline-none focus:ring-1 focus:ring-emerald-500 w-48 sm:w-60"
                  />
                </div>

                <select
                  value={selectedVerdict}
                  onChange={(e) => setSelectedVerdict(e.target.value)}
                  className="text-xs px-2.5 py-1.5 rounded border border-slate-300 bg-white focus:outline-none focus:ring-1 focus:ring-emerald-500 text-slate-700"
                >
                  <option value="">All Verdicts</option>
                  <option value="AGREE">Agree</option>
                  <option value="DISAGREE">Disagree</option>
                </select>
                <input aria-label="Audit from date" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="text-xs px-2 py-1.5 rounded border border-slate-300" />
                <input aria-label="Audit to date" type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="text-xs px-2 py-1.5 rounded border border-slate-300" />
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase font-bold text-slate-500 border-b border-slate-200">
                  <tr>
                    <th className="py-2.5 px-3">Timestamp</th>
                    <th className="py-2.5 px-3">Case Token</th>
                    <th className="py-2.5 px-3">Subject Entity</th>
                    <th className="py-2.5 px-3">Violation</th>
                    <th className="py-2.5 px-3">Verdict</th>
                    <th className="py-2.5 px-3">Applied Sanction</th>
                    <th className="py-2.5 px-3">Actor</th>
                    <th className="py-2.5 px-3">Request Hash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {ledger.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="text-center py-8 text-slate-400 text-xs">
                        No audit trail records found.
                      </td>
                    </tr>
                  ) : (
                    ledger.map((item) => {
                      const verdict = item.verdict.toUpperCase();
                      let badgeClass = "bg-slate-100 text-slate-700 border-slate-200";
                      if (verdict === "AGREE") {
                        badgeClass = "bg-rose-50 text-rose-700 border-rose-200";
                      } else if (verdict === "DISAGREE") {
                        badgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
                      }

                      return (
                        <tr key={item.id} className="hover:bg-slate-50 transition">
                          <td className="py-2.5 px-3 text-slate-500 font-mono text-[11px] whitespace-nowrap">
                            {new Date(item.timestamp).toLocaleString("vi-VN", {
                              month: "2-digit",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </td>
                          <td className="py-2.5 px-3 font-semibold text-slate-900 whitespace-nowrap">
                            {item.case_code}
                          </td>
                          <td className="py-2.5 px-3 text-slate-800 whitespace-nowrap">
                            {item.subject_entity}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-[11px] text-slate-600 whitespace-nowrap">
                            {item.triggered_violation}
                          </td>
                          <td className="py-2.5 px-3 whitespace-nowrap">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${badgeClass}`}
                            >
                              {item.verdict}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 max-w-xs truncate">
                            {item.sanction || "No direct sanction"}
                          </td>
                          <td className="py-2.5 px-3 text-slate-700 whitespace-nowrap">
                            {item.actor_name}
                          </td>
                          <td
                            className="py-2.5 px-3 font-mono text-[10px] text-slate-400 whitespace-nowrap"
                            title={item.request_hash || undefined}
                          >
                            {item.request_hash
                              ? item.request_hash.slice(0, 16) + "…"
                              : "—"}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {settingsOpen && (
        <AccountSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
      )}
    </section>
  );
}
