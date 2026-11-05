'use client';

import React from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Route, Percent, ShieldAlert, FolderSearch, Info } from 'lucide-react';
import type { DriverScorecardResponse } from '@/types/schemas';

interface ProfileKpiGridProps {
  scorecard: DriverScorecardResponse;
}

export function ProfileKpiGrid({ scorecard }: ProfileKpiGridProps) {
  const t = useTranslations('driver.profile');
  const locale = useLocale();

  const totalTrips = scorecard.total_trips ?? null;
  const totalCases = scorecard.total_cases ?? null;
  const violationRatio = scorecard.violation_ratio_90d ?? null;
  const benchmarkRatio = scorecard.benchmark_violation_ratio ?? null;
  const finedRatio = scorecard.fined_ratio ?? null;

  return (
    <section className="space-y-3">
      <div className="px-1">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
          {t('performanceTitle')}
        </h3>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t('performanceSubtitle')}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        {/* Card 1: Total Assigned Trips (Span 2) */}
        <div
          className="col-span-2 bg-white dark:bg-slate-900 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 shadow-xs flex items-center gap-3 group relative"
          title={t('kpiTotalTripsTooltip')}
        >
          <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <Route className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('kpiTotalTrips')}
              </p>
              <Info className="w-3 h-3 text-slate-400 opacity-60 group-hover:opacity-100 transition-opacity" />
            </div>
            <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {totalTrips !== null ? (
                <>
                  {totalTrips.toLocaleString(locale)}{' '}
                  <span className="text-xs font-normal text-slate-400">
                    {t('kpiTotalTripsUnit')}
                  </span>
                </>
              ) : (
                '—'
              )}
            </p>
          </div>
        </div>

        {/* Card 2: Violation Ratio vs Benchmark */}
        <div
          className="bg-white dark:bg-slate-900 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 shadow-xs flex flex-col justify-between group relative"
          title={t('kpiViolationRatioTooltip')}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1">
              <span className="text-xs text-slate-500 dark:text-slate-400 truncate">
                {t('kpiViolationRatio')}
              </span>
              <Info className="w-3 h-3 text-slate-400 opacity-60 group-hover:opacity-100 shrink-0" />
            </div>
            <Percent className="w-4 h-4 text-slate-400 shrink-0" />
          </div>
          <div>
            <p className="text-xl font-bold text-slate-900 dark:text-slate-100">
              {violationRatio !== null ? `${violationRatio.toFixed(1)}%` : '—'}
            </p>
            {benchmarkRatio !== null && (
              <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 truncate">
                {t('kpiBenchmarkReference', { value: benchmarkRatio.toFixed(1) })}
              </p>
            )}
          </div>
        </div>

        {/* Card 3: Fined Ratio */}
        <div
          className="bg-white dark:bg-slate-900 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 shadow-xs flex flex-col justify-between group relative"
          title={t('kpiFinedRatioTooltip')}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1">
              <span className="text-xs text-slate-500 dark:text-slate-400 truncate">
                {t('kpiFinedRatio')}
              </span>
              <Info className="w-3 h-3 text-slate-400 opacity-60 group-hover:opacity-100 shrink-0" />
            </div>
            <ShieldAlert className="w-4 h-4 text-slate-400 shrink-0" />
          </div>
          <div>
            <p className="text-xl font-bold text-slate-900 dark:text-slate-100">
              {finedRatio !== null ? `${finedRatio.toFixed(1)}%` : '—'}
            </p>
          </div>
        </div>

        {/* Card 4: Case Count */}
        <div
          className="col-span-2 bg-white dark:bg-slate-900 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 shadow-xs flex items-center gap-3 group relative"
          title={t('kpiCaseCountTooltip')}
        >
          <div className="w-10 h-10 rounded-xl bg-slate-50 dark:bg-slate-800/60 text-slate-500 dark:text-slate-400 flex items-center justify-center shrink-0">
            <FolderSearch className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('kpiCaseCount')}
              </p>
              <Info className="w-3 h-3 text-slate-400 opacity-60 group-hover:opacity-100 transition-opacity" />
            </div>
            <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {totalCases !== null ? (
                <>
                  {totalCases.toLocaleString(locale)}{' '}
                  <span className="text-xs font-normal text-slate-400">
                    {t('kpiCaseCountUnit')}
                  </span>
                </>
              ) : (
                '—'
              )}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
