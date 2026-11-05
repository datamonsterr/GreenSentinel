"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Shield, Sparkles, AlertCircle, RefreshCw, Inbox } from "lucide-react";
import type { DriverCaseSessionItem } from "@/types/schemas";
import { fetchDriverCases } from "@/lib/api-client";
import { isResolvedCase } from "@/lib/driver/case-segments";
import { DriverCaseCard } from "./driver-case-card";

export type CasesTab = "open" | "resolved";

export function DriverCasesView() {
  const t = useTranslations("driver");

  const [cases, setCases] = useState<DriverCaseSessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<CasesTab>("open");

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

  const openCases = cases.filter((c) => !isResolvedCase(c));
  const resolvedCases = cases.filter(isResolvedCase);

  const displayedCases = activeTab === "open" ? openCases : resolvedCases;

  return (
    <div className="w-full flex flex-col flex-1 pb-24 text-slate-900 dark:text-slate-100">
      {/* Top App Bar */}
      <header className="sticky top-0 z-30 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800 px-4 py-3 flex items-center justify-between shadow-2xs">
        <div className="flex items-center space-x-2.5">
          <div className="w-9 h-9 rounded-xl bg-emerald-500/10 dark:bg-emerald-500/20 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
            <Shield className="w-5 h-5" />
          </div>
          <div className="flex items-center space-x-2">
            <h1 className="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight">
              {t("cases.title")}
            </h1>
            <span className="inline-flex items-center justify-center px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-600 text-white shadow-2xs">
              ({cases.length})
            </span>
          </div>
        </div>
      </header>

      <div className="p-4 space-y-4">
        {/* AI Assurance Notice Banner */}
        <div className="rounded-2xl p-3.5 bg-gradient-to-r from-emerald-50 via-teal-50/60 to-white dark:from-emerald-950/40 dark:via-teal-950/30 dark:to-slate-900 border border-emerald-500/20 dark:border-emerald-500/30 shadow-2xs flex items-start space-x-3">
          <div className="w-8 h-8 rounded-xl bg-emerald-600 text-white flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div className="flex-1">
            <div className="flex items-center space-x-1.5 mb-0.5">
              <span className="text-xs font-bold text-emerald-800 dark:text-emerald-300">
                {t("cases.aiNoticeTitle")}
              </span>
              <span className="text-[10px] uppercase font-bold tracking-wide px-1.5 py-0.2 rounded bg-emerald-600/15 text-emerald-700 dark:text-emerald-300">
                {t("cases.aiNoticeBadge")}
              </span>
            </div>
            <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300">
              {t("cases.aiNoticeDesc")}
            </p>
          </div>
        </div>

        {/* Segmented Control Filter Tabs */}
        <div className="p-1 bg-slate-100 dark:bg-slate-800/80 rounded-2xl flex items-center border border-slate-200/80 dark:border-slate-700/80">
          <button
            type="button"
            onClick={() => setActiveTab("open")}
            className={`flex-1 py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center space-x-1.5 transition-all cursor-pointer ${
              activeTab === "open"
                ? "bg-emerald-600 text-white shadow-xs"
                : "text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            <span>{t("cases.tabOpen")}</span>
            <span
              className={`w-5 h-5 rounded-full text-[11px] font-bold flex items-center justify-center ${
                activeTab === "open"
                  ? "bg-white/20 text-white"
                  : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
              }`}
            >
              {openCases.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("resolved")}
            className={`flex-1 py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center space-x-1.5 transition-all cursor-pointer ${
              activeTab === "resolved"
                ? "bg-emerald-600 text-white shadow-xs"
                : "text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            <span>{t("cases.tabResolved")}</span>
            <span
              className={`w-5 h-5 rounded-full text-[11px] font-bold flex items-center justify-center ${
                activeTab === "resolved"
                  ? "bg-white/20 text-white"
                  : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
              }`}
            >
              {resolvedCases.length}
            </span>
          </button>
        </div>

        {/* Section title */}
        {activeTab === "open" && openCases.length > 0 && (
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              {t("cases.needActionSection")}
            </span>
          </div>
        )}

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
                {activeTab === "open"
                  ? t("cases.emptyOpenTitle")
                  : t("cases.emptyResolvedTitle")}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs mx-auto">
                {activeTab === "open"
                  ? t("cases.emptyOpenDesc")
                  : t("cases.emptyResolvedDesc")}
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
