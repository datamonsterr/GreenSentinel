'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { Car, Route, Star, Sparkles } from 'lucide-react';
import { type DriverTripsSummaryResponse } from '@/types/schemas';

export interface MonthlySummaryCardProps {
  summary: DriverTripsSummaryResponse | null;
  loading?: boolean;
}

export function MonthlySummaryCard({ summary, loading = false }: MonthlySummaryCardProps) {
  const t = useTranslations('driver.history');

  const fareFormatted = (summary?.total_fare_vnd ?? 0).toLocaleString('vi-VN');
  const distanceFormatted = (summary?.total_distance_km ?? 0).toLocaleString('vi-VN', {
    maximumFractionDigits: 1,
  });
  const tripCount = summary?.trip_count ?? 0;
  const ratingFormatted = summary?.avg_rating != null ? summary.avg_rating.toFixed(2) : t('unratedShort');

  return (
    <section
      aria-label={t('monthlyEarnings')}
      className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-white via-white to-emerald-50/40 dark:from-slate-900 dark:via-slate-900 dark:to-emerald-950/20 border border-emerald-100 dark:border-slate-800 p-4 shadow-sm"
    >
      <div className="absolute -right-10 -bottom-10 w-44 h-44 rounded-full bg-emerald-400/10 dark:bg-emerald-500/10 blur-2xl pointer-events-none" />

      <div className="flex justify-between items-start mb-3">
        <div>
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center space-x-1">
            <span>{t('monthlyEarnings')}</span>
            <Sparkles className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
          </span>
          <div className="flex items-baseline space-x-1.5 mt-1">
            <span className="text-3xl font-extrabold text-emerald-700 dark:text-emerald-400 tracking-tight">
              {loading ? '—' : fareFormatted}
            </span>
            <span className="text-lg font-bold text-emerald-700 dark:text-emerald-400">
              {t('currencySymbol')}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 pt-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40 rounded-xl p-2.5">
        <div className="flex flex-col items-center text-center">
          <div className="w-7 h-7 rounded-full bg-white dark:bg-slate-800 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-1 shadow-xs border border-slate-100 dark:border-slate-700">
            <Car className="w-3.5 h-3.5" />
          </div>
          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{t('tripCount')}</span>
          <span className="text-base font-bold text-slate-900 dark:text-slate-100 mt-0.5">
            {loading ? '—' : tripCount}
          </span>
        </div>

        <div className="flex flex-col items-center text-center border-x border-slate-200/60 dark:border-slate-800">
          <div className="w-7 h-7 rounded-full bg-white dark:bg-slate-800 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-1 shadow-xs border border-slate-100 dark:border-slate-700">
            <Route className="w-3.5 h-3.5" />
          </div>
          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{t('distance')}</span>
          <span className="text-base font-bold text-slate-900 dark:text-slate-100 mt-0.5">
            {loading ? '—' : distanceFormatted}
            <span className="text-[10px] font-normal text-slate-500 dark:text-slate-400 ml-0.5">km</span>
          </span>
        </div>

        <div className="flex flex-col items-center text-center">
          <div className="w-7 h-7 rounded-full bg-white dark:bg-slate-800 flex items-center justify-center text-amber-500 mb-1 shadow-xs border border-slate-100 dark:border-slate-700">
            <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
          </div>
          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{t('rating')}</span>
          <span className="text-base font-bold text-slate-900 dark:text-slate-100 mt-0.5">
            {loading ? '—' : ratingFormatted}
            {summary?.avg_rating != null && (
              <span className="text-amber-500 text-xs ml-0.5">★</span>
            )}
          </span>
        </div>
      </div>
    </section>
  );
}
