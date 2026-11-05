'use client';

import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import {
  Clock,
  Wallet,
  CreditCard,
  Banknote,
  Star,
  Quote,
  AlertTriangle,
  ArrowRight,
} from 'lucide-react';
import { type DriverTripItem } from '@/types/schemas';
import { getTripStatusCopy } from '@/lib/driver/status-copy';
import { tripDomId } from '@/lib/driver/trip-dom-id';

export interface TripHistoryItemProps {
  trip: DriverTripItem;
}

function formatTime(isoString?: string | null): string {
  if (!isoString) return '--:--';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '--:--';
    return d.toLocaleTimeString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--';
  }
}

export function TripHistoryItem({ trip }: TripHistoryItemProps) {
  const router = useRouter();
  const t = useTranslations('driver.history');
  const locale = useLocale();

  const startTime = formatTime(trip.started_at);
  const endTime = trip.ended_at ? formatTime(trip.ended_at) : '';
  const timeRange = endTime ? `${startTime} – ${endTime}` : startTime;

  const durationMin = Math.round(trip.duration_min);
  const distanceFormatted = trip.distance_km % 1 === 0 ? trip.distance_km.toFixed(0) : trip.distance_km.toFixed(1);
  const fareFormatted = trip.fare_vnd.toLocaleString('vi-VN');

  const paymentMethodKey = trip.payment_method === 'credit_card'
    ? 'credit_card'
    : trip.payment_method === 'cash'
    ? 'cash'
    : 'wallet';

  const PaymentIcon = trip.payment_method === 'credit_card'
    ? CreditCard
    : trip.payment_method === 'cash'
    ? Banknote
    : Wallet;

  const isFlagged = trip.has_case && Boolean(trip.case_id);
  const caseId = trip.case_id;
  const statusCopy = getTripStatusCopy(isFlagged ? 'flagged' : trip.status, locale);

  const handleCardClick = (e: React.MouseEvent) => {
    // Only navigate to chat when the trip is flagged and has a case ID
    if (isFlagged && caseId) {
      // If clicking directly on a link, let the link handle it
      if ((e.target as HTMLElement).closest('a')) return;
      router.push(`/driver/chat/${caseId}`);
    }
  };

  return (
    <article
      id={`trip-${tripDomId(trip.trip_id)}`}
      data-testid={`trip-history-item-${tripDomId(trip.trip_id)}`}
      onClick={handleCardClick}
      className={`relative bg-white dark:bg-slate-900 rounded-2xl p-4 border border-slate-200/80 dark:border-slate-800 shadow-xs transition-all ${
        isFlagged ? 'cursor-pointer hover:border-amber-400 dark:hover:border-amber-600' : ''
      }`}
    >
      {/* Left Alert Accent Line if flagged */}
      {isFlagged && (
        <div className="absolute left-0 top-3 bottom-3 w-1 bg-amber-500 rounded-r" />
      )}

      {/* Card Header: time range, duration, distance, fare */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center space-x-1.5 text-slate-500 dark:text-slate-400 text-xs font-medium">
          <Clock className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
          <span className="font-semibold text-slate-900 dark:text-slate-100">{timeRange}</span>
          <span>•</span>
          <span>{t('durationMin', { min: durationMin })}</span>
          <span>•</span>
          <span>{t('kmUnit', { km: distanceFormatted })}</span>
        </div>
        <span
          className={`text-base font-bold ${
            isFlagged
              ? 'text-slate-900 dark:text-slate-100'
              : 'text-emerald-600 dark:text-emerald-400'
          }`}
        >
          {fareFormatted}
          {t('currencySymbol')}
        </span>
      </div>

      {/* Vertical Route Stepper */}
      <div className="py-3 flex space-x-3">
        <div className="flex flex-col items-center justify-between py-1">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 ring-4 ring-emerald-100 dark:ring-emerald-950/60" />
          <div className="w-0.5 h-7 border-l-2 border-dotted border-slate-300 dark:border-slate-700 my-1" />
          <span className="w-2.5 h-2.5 rounded-xs bg-slate-800 dark:bg-slate-200" />
        </div>
        <div className="flex-1 space-y-2.5">
          <div>
            <p className="text-xs font-semibold text-slate-900 dark:text-slate-100 leading-tight">
              {trip.pickup_label}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-900 dark:text-slate-100 leading-tight">
              {trip.dropoff_label}
            </p>
          </div>
        </div>
      </div>

      {/* Customer Review Callout */}
      {trip.rating && trip.rating.comment && (
        <div className="bg-slate-50 dark:bg-slate-800/60 rounded-xl p-2.5 mb-3 flex items-start space-x-2 border border-slate-100 dark:border-slate-800">
          <Quote className="w-4 h-4 text-amber-500 shrink-0 mt-0.5 fill-amber-400/20" />
          <div className="flex-1">
            <div className="flex items-center space-x-1">
              <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                {trip.rating.stars != null ? trip.rating.stars.toFixed(1) : ''}
              </span>
              {trip.rating.stars != null && (
                <span className="text-amber-500 text-xs">
                  {'★'.repeat(trip.rating.stars)}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-300 italic mt-0.5">
              &ldquo;{trip.rating.comment}&rdquo;
            </p>
          </div>
        </div>
      )}

      {/* Flagged / Dispute Banner */}
      {isFlagged && caseId && (
        <div className="bg-amber-50 dark:bg-amber-950/30 rounded-xl p-2.5 mb-3 flex items-center justify-between border border-amber-200/60 dark:border-amber-800/40">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <span className="text-xs text-slate-800 dark:text-slate-200 font-medium">
              {t('flaggedNotice')}
            </span>
          </div>
          <Link
            href={`/driver/chat/${caseId}`}
            className="inline-flex items-center space-x-0.5 text-xs font-bold text-amber-700 dark:text-amber-300 hover:underline shrink-0"
          >
            <span>{t('viewDisputeCase')}</span>
            <ArrowRight className="w-3.5 h-3.5 ml-0.5" />
          </Link>
        </div>
      )}

      {/* Meta Information Row */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center space-x-2">
          {/* Payment method pill */}
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-[11px] font-medium">
            <PaymentIcon className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
            <span>{t(`paymentMethods.${paymentMethodKey}`)}</span>
            {trip.payment_method_synthetic && (
              <span
                title={t('syntheticDataTooltip')}
                className="ml-1 px-1 rounded bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400 text-[9px] font-semibold uppercase tracking-wide cursor-help"
              >
                {t('syntheticDataLabel')}
              </span>
            )}
          </span>

          {/* Rating or 'Not rated' */}
          {trip.rating && trip.rating.stars != null ? (
            <span className="inline-flex items-center space-x-0.5 text-[11px] font-semibold text-slate-700 dark:text-slate-300">
              <Star className="w-3 h-3 text-amber-500 fill-amber-400" />
              <span>{trip.rating.stars.toFixed(1)}</span>
            </span>
          ) : (
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {t('notRated')}
            </span>
          )}
        </div>

        {/* Status Pill */}
        <span
          className={`inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold ${
            isFlagged
              ? 'bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300'
              : 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300'
          }`}
        >
          {!isFlagged && <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-pulse" />}
          <span title={statusCopy.explanation}>{statusCopy.label}</span>
        </span>
      </div>
    </article>
  );
}
