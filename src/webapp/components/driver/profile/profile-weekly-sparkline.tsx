'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { TrendingUp } from 'lucide-react';
import type { WeeklyRatingTrend } from '@/types/schemas';

interface ProfileWeeklySparklineProps {
  trend: WeeklyRatingTrend[];
}

export function ProfileWeeklySparkline({ trend }: ProfileWeeklySparklineProps) {
  const t = useTranslations('driver.profile');

  if (!trend || trend.length === 0) {
    return null;
  }

  // Calculate coordinates for inline SVG polyline
  const width = 280;
  const height = 48;
  const paddingX = 12;
  const paddingY = 8;
  const usableWidth = width - paddingX * 2;
  const usableHeight = height - paddingY * 2;

  // Min rating 1.0, max 5.0 (or dynamic range around 3.5 to 5.0)
  const minRating = 1.0;
  const maxRating = 5.0;

  const points = trend.map((pt, idx) => {
    const x = paddingX + (idx / Math.max(1, trend.length - 1)) * usableWidth;
    const rating = pt.average_rating ?? minRating;
    const normalized = (rating - minRating) / (maxRating - minRating);
    const y = height - paddingY - normalized * usableHeight;
    return { x, y, pt };
  });

  const polylinePoints = points
    .filter((p) => p.pt.average_rating !== null)
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ');

  const latestRated = [...trend].reverse().find((pt) => pt.average_rating !== null);

  return (
    <div className="p-3 bg-slate-50/80 dark:bg-slate-800/40 rounded-xl border border-slate-200/60 dark:border-slate-800/60 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-1.5 text-xs font-medium text-slate-700 dark:text-slate-300">
        <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-semibold">
          <TrendingUp className="w-4 h-4" />
          <span>{t('trendTitle')}</span>
        </div>
        {latestRated?.average_rating && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100/70 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
            {t('latestRatedWeek', { score: latestRated.average_rating.toFixed(2) })}
          </span>
        )}
      </div>

      {/* Inline SVG Chart */}
      <div className="w-full flex items-center justify-center">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-12 overflow-visible select-none"
          role="img"
          aria-label={t('trendTitle')}
        >
          <defs>
            <linearGradient id="sparklineGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Area fill */}
          {polylinePoints && (
            <polygon
              points={`${points[0].x},${height - paddingY} ${polylinePoints} ${points[points.length - 1].x},${height - paddingY}`}
              fill="url(#sparklineGrad)"
            />
          )}

          {/* Trend line */}
          {polylinePoints ? (
            <polyline
              fill="none"
              stroke="#10b981"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={polylinePoints}
            />
          ) : (
            <line
              x1={paddingX}
              y1={height / 2}
              x2={width - paddingX}
              y2={height / 2}
              stroke="#94a3b8"
              strokeDasharray="4 4"
              strokeWidth="1.5"
            />
          )}

          {/* Data point dots */}
          {points.map((p, i) => (
            <g key={i}>
              <circle
                cx={p.x}
                cy={p.pt.average_rating !== null ? p.y : height / 2}
                r={p.pt.average_rating !== null ? 3.5 : 2}
                className={
                  p.pt.average_rating !== null
                    ? 'fill-emerald-500 stroke-white dark:stroke-slate-900 stroke-2'
                    : 'fill-slate-300 dark:fill-slate-600'
                }
              >
                <title>
                  {p.pt.week_label}: {p.pt.average_rating !== null ? p.pt.average_rating.toFixed(2) : '-'}
                </title>
              </circle>
            </g>
          ))}
        </svg>
      </div>

      {/* Week labels footer */}
      <div className="flex justify-between text-[10px] text-slate-400 dark:text-slate-500 font-mono px-1">
        <span>{trend[0]?.week_label || 'W1'}</span>
        <span>{trend[Math.floor(trend.length / 2)]?.week_label || 'W4'}</span>
        <span>{trend[trend.length - 1]?.week_label || 'W8'}</span>
      </div>
    </div>
  );
}
