'use client';

import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { Calendar, History, Loader2, ChevronLeft, ChevronRight, AlertTriangle } from 'lucide-react';
import { MonthlySummaryCard } from '@/components/driver/history/monthly-summary-card';
import { HistorySegmentedTabs, type HistoryFilterStatus } from '@/components/driver/history/history-segmented-tabs';
import { TripHistoryItem } from '@/components/driver/history/trip-history-item';
import { tripDomId } from '@/lib/driver/trip-dom-id';
import { fetchDriverTrips, fetchDriverTripsSummary, parseErrorStatus } from '@/lib/api-client';
import { type DriverTripItem, type DriverTripsSummaryResponse, type DriverTripCounts } from '@/types/schemas';

interface DateGroup {
  dateKey: string;
  displayDate: string;
  trips: DriverTripItem[];
  totalFare: number;
}

/** Current year-month (YYYY-MM) in Asia/Ho_Chi_Minh. */
function currentVnMonth(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(new Date());
  const year = parts.find((p) => p.type === 'year')?.value ?? '1970';
  const month = parts.find((p) => p.type === 'month')?.value ?? '01';
  return `${year}-${month}`;
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map((v) => parseInt(v, 10));
  const date = new Date(Date.UTC(y, m - 1 + delta, 1));
  const year = date.getUTCFullYear();
  const mon = String(date.getUTCMonth() + 1).padStart(2, '0');
  return `${year}-${mon}`;
}

function dedupeByTripId(trips: DriverTripItem[]): DriverTripItem[] {
  const seen = new Set<string>();
  const result: DriverTripItem[] = [];
  for (const trip of trips) {
    if (seen.has(trip.trip_id)) continue;
    seen.add(trip.trip_id);
    result.push(trip);
  }
  return result;
}

const EMPTY_COUNTS: DriverTripCounts = { all: 0, completed: 0, flagged: 0 };

export default function DriverHistoryPage() {
  const t = useTranslations('driver.history');
  const searchParams = useSearchParams();
  const highlightTripId = searchParams?.get('trip') || null;

  const [activeTab, setActiveTab] = useState<HistoryFilterStatus>('all');
  const [selectedMonth, setSelectedMonth] = useState<string>(() => currentVnMonth());
  const [summary, setSummary] = useState<DriverTripsSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<boolean>(false);
  const [trips, setTrips] = useState<DriverTripItem[]>([]);
  const [counts, setCounts] = useState<DriverTripCounts>(EMPTY_COUNTS);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [tripsError, setTripsError] = useState<boolean>(false);

  // Stale-response guard: only the latest in-flight request may commit state.
  const requestIdRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const monthParts = useMemo(() => {
    const [y, m] = selectedMonth.split('-');
    return { year: y || '1970', month: parseInt(m || '1', 10) };
  }, [selectedMonth]);

  const loadData = useCallback(async () => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const requestId = ++requestIdRef.current;

    setLoading(true);
    setTripsError(false);
    setSummaryError(false);

    const [tripsResult, summaryResult] = await Promise.allSettled([
      fetchDriverTrips({
        month: selectedMonth,
        status: activeTab === 'all' ? undefined : activeTab,
        limit: 20,
        signal: controller.signal,
      }),
      fetchDriverTripsSummary({ month: selectedMonth, signal: controller.signal }),
    ]);

    if (requestIdRef.current !== requestId) return; // stale, superseded by a newer request

    if (tripsResult.status === 'fulfilled') {
      setTrips(dedupeByTripId(tripsResult.value.trips || []));
      setCounts(tripsResult.value.counts || EMPTY_COUNTS);
      setNextCursor(tripsResult.value.next_cursor || null);
      setTripsError(false);
    } else {
      const status = parseErrorStatus(tripsResult.reason);
      console.error(status);
      setTrips([]);
      setCounts(EMPTY_COUNTS);
      setNextCursor(null);
      setTripsError(true);
    }

    // Summary failure must not wipe the trip list into an empty state.
    if (summaryResult.status === 'fulfilled') {
      setSummary(summaryResult.value);
      setSummaryError(false);
    } else {
      const status = parseErrorStatus(summaryResult.reason);
      console.error(status);
      setSummary(null);
      setSummaryError(true);
    }

    setLoading(false);
  }, [selectedMonth, activeTab]);

  useEffect(() => {
    loadData();
    return () => abortControllerRef.current?.abort();
  }, [loadData]);

  // Deep-link from a chat trip:// block (Issue #538 blocker #6): scroll to
  // and briefly highlight the matching trip once it has rendered.
  useEffect(() => {
    if (!highlightTripId || trips.length === 0) return;
    const el = document.getElementById(`trip-${tripDomId(highlightTripId)}`);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-amber-500');
    const timer = setTimeout(() => el.classList.remove('ring-2', 'ring-amber-500'), 2500);
    return () => clearTimeout(timer);
  }, [highlightTripId, trips]);

  const handleLoadMore = useCallback(async () => {
    if (!nextCursor || loadingMore || loading) return;
    const requestId = requestIdRef.current; // load-more belongs to the current filter generation
    setLoadingMore(true);
    try {
      const res = await fetchDriverTrips({
        month: selectedMonth,
        status: activeTab === 'all' ? undefined : activeTab,
        cursor: nextCursor,
        limit: 20,
      });
      if (requestIdRef.current !== requestId) return; // filters changed while this page was loading
      setTrips((prev) => dedupeByTripId([...prev, ...(res.trips || [])]));
      setNextCursor(res.next_cursor || null);
      setCounts(res.counts || EMPTY_COUNTS);
    } catch {
      // Keep existing list on pagination failure.
    } finally {
      if (requestIdRef.current === requestId) setLoadingMore(false);
    }
  }, [nextCursor, loadingMore, loading, selectedMonth, activeTab]);

  // Infinite scroll sentinel via IntersectionObserver, with a visible fallback button for a11y.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !nextCursor) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) handleLoadMore();
      },
      { rootMargin: '200px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [nextCursor, handleLoadMore]);

  const dateGroups: DateGroup[] = useMemo(() => {
    const groupsMap = new Map<string, DriverTripItem[]>();

    for (const trip of trips) {
      let key = 'unknown';
      try {
        const d = new Date(trip.started_at);
        if (!isNaN(d.getTime())) {
          key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        }
      } catch {
        key = 'unknown';
      }

      const existing = groupsMap.get(key) || [];
      existing.push(trip);
      groupsMap.set(key, existing);
    }

    const now = new Date();
    const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const yesterdayDate = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const yesterdayKey = `${yesterdayDate.getFullYear()}-${String(yesterdayDate.getMonth() + 1).padStart(2, '0')}-${String(yesterdayDate.getDate()).padStart(2, '0')}`;

    const sortedEntries = Array.from(groupsMap.entries()).sort((a, b) => b[0].localeCompare(a[0]));

    return sortedEntries.map(([dateKey, items]) => {
      let displayDate = dateKey;
      if (dateKey !== 'unknown') {
        const [y, m, d] = dateKey.split('-');
        const dateFormatted = `${parseInt(d, 10)}/${parseInt(m, 10)}/${y}`;
        if (dateKey === todayKey) {
          displayDate = `${t('today')}, ${dateFormatted}`;
        } else if (dateKey === yesterdayKey) {
          displayDate = `${t('yesterday')}, ${dateFormatted}`;
        } else {
          displayDate = dateFormatted;
        }
      }

      const totalFare = items.reduce((sum, item) => sum + (item.fare_vnd || 0), 0);

      return {
        dateKey,
        displayDate,
        trips: items,
        totalFare,
      };
    });
  }, [trips, t]);

  // Tab counts always come from the backend-reported counts (never recomputed from the current page).
  const tabCounts = counts;

  return (
    <div className="flex-1 w-full max-w-md mx-auto px-4 pt-3 pb-8 space-y-4">
      {/* Top Header */}
      <header className="flex justify-between items-center pb-1">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">
            {t('title')}
          </h1>
        </div>

        {/* Month Picker: previous / label / next */}
        <div className="flex items-center space-x-1">
          <button
            type="button"
            aria-label={t('prevMonth')}
            onClick={() => setSelectedMonth((prev) => shiftMonth(prev, -1))}
            className="p-1.5 rounded-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-all active:scale-95 cursor-pointer"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span
            aria-label={t('filterMonthAria')}
            className="flex items-center space-x-1.5 py-1.5 px-3 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700"
          >
            <Calendar className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
              {t('monthFormat', { month: monthParts.month, year: monthParts.year })}
            </span>
          </span>
          <button
            type="button"
            aria-label={t('nextMonth')}
            onClick={() => setSelectedMonth((prev) => shiftMonth(prev, 1))}
            className="p-1.5 rounded-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-all active:scale-95 cursor-pointer"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Segmented Filter Tabs */}
      <HistorySegmentedTabs
        activeTab={activeTab}
        onChange={setActiveTab}
        counts={tabCounts}
      />

      {/* Monthly Summary Bento Card (summary failures shown inline, do not block the trip list) */}
      {summaryError ? (
        <div className="flex items-center justify-between rounded-2xl border border-amber-200/60 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-800 dark:text-amber-300">
          <span>{t('errorTitle')}</span>
          <button type="button" onClick={loadData} className="font-bold underline cursor-pointer">
            {t('errorRetry')}
          </button>
        </div>
      ) : (
        <MonthlySummaryCard summary={summary} loading={loading} />
      )}

      {/* Main Content: Grouped Trip List, Error, or Empty State */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-16 space-y-2 text-slate-400 dark:text-slate-500">
          <Loader2 className="w-7 h-7 animate-spin text-emerald-600" />
          <span className="text-xs font-medium">{t('loading')}</span>
        </div>
      ) : tripsError ? (
        <div data-testid="driver-history-error-card" className="flex flex-col items-center justify-center py-16 text-center space-y-3 bg-white dark:bg-slate-900 rounded-2xl border border-red-200/80 dark:border-red-800/60 p-6 shadow-xs">
          <div className="w-14 h-14 rounded-2xl bg-red-50 dark:bg-red-950/40 text-red-500 flex items-center justify-center">
            <AlertTriangle className="w-7 h-7" />
          </div>
          <div className="space-y-1 max-w-xs">
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
              {t('errorTitle')}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t('errorDesc')}
            </p>
          </div>
          <button
            type="button"
            onClick={loadData}
            data-testid="driver-history-retry"
            className="inline-flex items-center py-2 px-5 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition-all active:scale-95 cursor-pointer"
          >
            {t('errorRetry')}
          </button>
        </div>
      ) : trips.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center space-y-3 bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 p-6 shadow-xs">
          <div className="w-14 h-14 rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 flex items-center justify-center">
            <History className="w-7 h-7" />
          </div>
          <div className="space-y-1 max-w-xs">
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
              {t('emptyTitle')}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              {t('emptyDesc')}
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          {dateGroups.map((group) => {
            const fareFormatted = group.totalFare.toLocaleString('vi-VN');
            return (
              <section key={group.dateKey} className="space-y-3">
                {/* Date Group Heading */}
                <div className="flex items-center justify-between px-1">
                  <div className="flex items-center space-x-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-600" />
                    <h2 className="text-xs font-bold text-slate-900 dark:text-slate-100">
                      {group.displayDate}
                    </h2>
                  </div>
                  <span className="text-xs text-slate-400 dark:text-slate-500 font-medium">
                    {t('tripsCountUnit', { count: group.trips.length })} • {fareFormatted}
                    {t('currencySymbol')}
                  </span>
                </div>

                {/* List of Trip Cards for this date */}
                <div className="space-y-3">
                  {group.trips.map((trip) => (
                    <TripHistoryItem key={trip.trip_id} trip={trip} />
                  ))}
                </div>
              </section>
            );
          })}

          {/* Infinite-scroll sentinel (IntersectionObserver) + visible fallback button for accessibility */}
          {nextCursor && (
            <div ref={sentinelRef} className="pt-2 pb-4 flex justify-center">
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loadingMore}
                aria-label={t('loadMoreSentinelLabel')}
                className="inline-flex items-center space-x-1.5 py-2 px-5 rounded-full bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-xs font-bold transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {loadingMore && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>{t('loadMore')}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
