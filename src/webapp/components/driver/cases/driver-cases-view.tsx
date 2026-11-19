"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Shield, Sparkles, AlertCircle, RefreshCw, Inbox } from "lucide-react";
import type { DriverCaseSessionItem } from "@/types/schemas";
import { fetchDriverCases } from "@/lib/api-client";
import { countByPhase, getTicketPhase, type TicketFilter } from "@/lib/driver/tickets";
import { DriverCaseCard } from "./driver-case-card";

export type CasesTab = TicketFilter;

export function DriverCasesView() {
  const t = useTranslations("driver");

  const [cases, setCases] = useState<DriverCaseSessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<CasesTab>("all");

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchDriverCases();
      setCases(res?.items || []);
    } catch {
      setError(t("cases.errorTitle"));
      setCases([]);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  const counts = countByPhase(cases);
  const displayedCases = activeTab === "all" ? cases : cases.filter((c) => getTicketPhase(c) === activeTab);
  const filters: { id: CasesTab; label: string }[] = [
    { id: "all", label: t("tickets.filterAll") },
    { id: "open", label: t("tickets.filterOpen") },
    { id: "pending", label: t("tickets.filterPending") },
    { id: "closed", label: t("tickets.filterClosed") },
  ];

  return (
    <div className="w-full flex flex-col flex-1 pb-24 text-slate-900 dark:text-slate-100">
      <header className="sticky top-0 z-30 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800 px-4 pt-4 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-500/20 flex items-center justify-center text-emerald-700 dark:text-emerald-400">
            <Shield className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight">{t("cases.title")}</h1>
              <span className="inline-flex items-center justify-center px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-600 text-white">
                ({cases.length})
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="tickets-summary">
              {t("tickets.summary", { open: counts.open, pending: counts.pending, closed: counts.closed })}
            </p>
          </div>
        </div>
        <div className="mt-3 flex gap-2 overflow-x-auto -mx-1 px-1 pb-0.5" aria-label={t("cases.title")}>
          {filters.map((f) => {
            const active = activeTab === f.id;
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={active}
                onClick={() => setActiveTab(f.id)}
                className={`shrink-0 min-h-11 px-4 rounded-full border text-sm font-semibold flex items-center gap-1.5 transition-colors cursor-pointer ${
                  active
                    ? "bg-[#1b2a33] border-[#1b2a33] text-white dark:bg-emerald-600 dark:border-emerald-600"
                    : "bg-white border-slate-200 text-slate-700 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-300"
                }`}
              >
                <span>{f.label}</span>
                <span className={`text-xs ${active ? "text-white/70" : "text-slate-400"}`}>{counts[f.id]}</span>
              </button>
            );
          })}
        </div>
      </header>

      <div className="p-4 space-y-4">
        {/* AI Assurance Notice */}
        <div className="rounded-[20px] p-3.5 bg-[var(--driver-strip)] border border-emerald-500/20 flex items-start gap-3">
          <div className="w-8 h-8 rounded-full bg-emerald-600 text-white flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className="text-xs font-bold text-emerald-800 dark:text-emerald-300">{t("cases.aiNoticeTitle")}</span>
              <span className="text-[10px] uppercase font-bold tracking-wide px-1.5 rounded bg-emerald-600/15 text-emerald-700 dark:text-emerald-300">
                {t("cases.aiNoticeBadge")}
              </span>
            </div>
            <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300">{t("cases.aiNoticeDesc")}</p>
          </div>
        </div>

        {/* Content Area */}
        {loading ? (
          /* Loading Skeleton */
          <div data-testid="cases-loading-skeleton" className="space-y-3">
            {[1, 2, 3].map((idx) => (
              <div
                key={idx}
                className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 space-y-3 animate-pulse"
              >
                <div className="flex items-center justify-between">
                  <div className="h-5 w-14 bg-slate-200 dark:bg-slate-800 rounded-md" />
                  <div className="h-5 w-24 bg-slate-200 dark:bg-slate-800 rounded-full" />
                </div>
                <div className="h-4 w-3/4 bg-slate-200 dark:bg-slate-800 rounded" />
                <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
                  <div className="h-4 w-32 bg-slate-200 dark:bg-slate-800 rounded" />
                  <div className="h-4 w-4 bg-slate-200 dark:bg-slate-800 rounded" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          /* Error State with Retry */
          <div
            data-testid="cases-error-state"
            className="rounded-2xl border border-rose-200 dark:border-rose-900 bg-rose-50/60 dark:bg-rose-950/30 p-6 text-center space-y-3"
          >
            <div className="w-10 h-10 rounded-full bg-rose-100 dark:bg-rose-900/60 text-rose-600 dark:text-rose-400 flex items-center justify-center mx-auto">
              <AlertCircle className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">{error}</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t("cases.errorDesc")}
              </p>
            </div>
            <button
              type="button"
              onClick={loadCases}
              className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-xs transition-colors cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>{t("cases.retryButton")}</span>
            </button>
          </div>
        ) : displayedCases.length === 0 ? (
          /* Empty State */
          <div
            data-testid="cases-empty-state"
            className="rounded-2xl border border-dashed border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-8 text-center space-y-3"
          >
            <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 flex items-center justify-center mx-auto">
              <Inbox className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                {cases.length === 0 ? t("tickets.emptyAllTitle") : t("tickets.emptyFilterTitle")}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs mx-auto">
                {cases.length === 0 ? t("tickets.emptyAllDesc") : t("tickets.emptyFilterDesc")}
              </p>
            </div>
          </div>
        ) : (
          /* Case Cards List */
          <div className="space-y-3">
            {displayedCases.map((item) => (
              <DriverCaseCard key={item.case_id} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
