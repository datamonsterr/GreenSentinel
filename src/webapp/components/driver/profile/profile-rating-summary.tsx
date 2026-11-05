'use client';

import React from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Star, StarHalf } from 'lucide-react';
import { ProfileWeeklySparkline } from './profile-weekly-sparkline';
import type { DriverProfileResponse } from '@/types/schemas';

interface ProfileRatingSummaryProps {
  profile: DriverProfileResponse;
}

export function ProfileRatingSummary({ profile }: ProfileRatingSummaryProps) {
  const t = useTranslations('driver.profile');
  const locale = useLocale();

  const { rating_average, rated_count, distribution, weekly_trend } = profile;

  // Star rendering helper
  const renderStars = (rating: number | null) => {
    if (rating === null || rating <= 0) {
      return (
        <div data-testid="rating-stars" className="flex items-center gap-0.5 text-slate-300 dark:text-slate-600">
          {[...Array(5)].map((_, i) => (
            <Star key={i} data-testid="star-empty" className="w-4 h-4" />
          ))}
        </div>
      );
    }
    const base = Math.floor(rating);
    const fraction = rating - base;
    let fullStars = base;
    let hasHalf = false;

    if (fraction >= 0.75) {
      fullStars = Math.min(5, base + 1);
    } else if (fraction >= 0.25) {
      fullStars = Math.min(4, base);
      hasHalf = true;
    } else {
      fullStars = Math.min(5, base);
    }
    const remaining = 5 - fullStars - (hasHalf ? 1 : 0);

    return (
      <div data-testid="rating-stars" className="flex items-center gap-0.5 text-amber-500">
        {[...Array(fullStars)].map((_, i) => (
          <Star key={`full-${i}`} data-testid="star-full" className="w-4 h-4 fill-current" />
        ))}
        {hasHalf && <StarHalf key="half" data-testid="star-half" className="w-4 h-4 fill-current" />}
        {[...Array(Math.max(0, remaining))].map((_, i) => (
          <Star key={`empty-${i}`} data-testid="star-empty" className="w-4 h-4 text-slate-300 dark:text-slate-700" />
        ))}
      </div>
    );
  };

  // Distribution rows [5, 4, 3, 2, 1]
  const starRows = ['5', '4', '3', '2', '1'];

  return (
    <section className="bg-white dark:bg-slate-900 rounded-2xl p-4 shadow-xs border border-slate-200/80 dark:border-slate-800 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
            {t('ratingSectionTitle')}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('ratingSectionSubtitle')}
          </p>
        </div>
      </div>

      {/* Grid: Left Big Metric, Right Breakdown */}
      <div className="grid grid-cols-12 gap-3 items-center pt-1">
        {/* Big Metric (Left) */}
        <div className="col-span-5 flex flex-col items-center justify-center p-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/50 dark:border-slate-800/80">
          <div className="flex items-baseline gap-1">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
              {rating_average !== null ? rating_average.toFixed(1) : '—'}
            </span>
            <span className="text-xs font-semibold text-slate-400 dark:text-slate-500">
              {t('outOfFive')}
            </span>
          </div>

          <div className="my-1.5">{renderStars(rating_average)}</div>

          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400 text-center">
            {rated_count > 0 ? t('reviewCount', { count: rated_count.toLocaleString(locale) }) : t('noRatingsYet')}
          </span>
        </div>

        {/* Star Distribution Bars (Right) */}
        <div className="col-span-7 space-y-1.5">
          {starRows.map((stars) => {
            const count = (distribution && distribution[stars]) || 0;
            const pct = rated_count > 0 ? Math.round((count / rated_count) * 100) : 0;

            return (
              <div key={stars} className="flex items-center gap-1.5 text-xs">
                <span className="w-2.5 text-right font-medium text-slate-700 dark:text-slate-300 text-[11px]">
                  {stars}
                </span>
                <Star className="w-3 h-3 text-amber-500 fill-current shrink-0" />
                <div className="flex-1 h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 dark:bg-emerald-400 rounded-full transition-all duration-300"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-20 text-right text-slate-400 dark:text-slate-500 whitespace-nowrap tabular-nums text-[10px]">
                  {pct}% <span className="text-[9px]">({count.toLocaleString(locale)})</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Weekly Sparkline Trend Card */}
      {weekly_trend && weekly_trend.length > 0 && (
        <ProfileWeeklySparkline trend={weekly_trend} />
      )}
    </section>
  );
}
