'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { Loader2, AlertCircle } from 'lucide-react';
import { DriverProfileView } from '@/components/driver/profile';
import { fetchDriverProfile, fetchDriverFeedback, parseErrorStatus } from '@/lib/api-client';
import type { DriverProfileResponse, DriverFeedbackResponse } from '@/types/schemas';

export default function DriverProfilePage() {
  const router = useRouter();
  const t = useTranslations('driver.profile');

  const [profile, setProfile] = useState<DriverProfileResponse | null>(null);
  const [feedback, setFeedback] = useState<DriverFeedbackResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [hasError, setHasError] = useState<boolean>(false);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setHasError(false);
      const [p, f] = await Promise.all([
        fetchDriverProfile(),
        fetchDriverFeedback(undefined, 10),
      ]);
      setProfile(p);
      setFeedback(f);
    } catch (err: unknown) {
      const status = parseErrorStatus(err);
      console.error(status);
      setHasError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleLoadMoreFeedback = async () => {
    if (!feedback?.next_cursor || loadingMore) return;
    try {
      setLoadingMore(true);
      setLoadMoreError(null);
      const res = await fetchDriverFeedback(feedback.next_cursor, 10);
      setFeedback((prev) =>
        prev
          ? {
              items: [...prev.items, ...res.items],
              next_cursor: res.next_cursor,
              total: res.total,
            }
          : res
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('loadMoreFailed');
      setLoadMoreError(msg);
    } finally {
      setLoadingMore(false);
    }
  };

  const handleBack = () => {
    router.back();
  };

  if (loading) {
    return (
      <div className="flex-1 w-full max-w-md mx-auto p-4 flex flex-col items-center justify-center min-h-[60vh] text-center space-y-3">
        <Loader2 className="w-8 h-8 text-emerald-600 dark:text-emerald-400 animate-spin" />
        <p className="text-xs text-slate-500 dark:text-slate-400 font-medium">
          {t('loading')}
        </p>
      </div>
    );
  }

  if (hasError || !profile || !feedback) {
    return (
      <div
        data-testid="driver-profile-error-card"
        className="flex-1 w-full max-w-md mx-auto p-4 flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4"
      >
        <div className="w-12 h-12 rounded-full bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 flex items-center justify-center shadow-xs">
          <AlertCircle className="w-6 h-6" />
        </div>
        <div className="space-y-1 max-w-xs">
          <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100">
            {t('errorLoadFailed')}
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('errorLoadDesc')}
          </p>
        </div>
        <button
          type="button"
          onClick={loadData}
          data-testid="driver-profile-retry"
          className="px-4 py-2 text-xs font-semibold rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 active:scale-95 transition-all shadow-xs cursor-pointer"
        >
          {t('retry')}
        </button>
      </div>
    );
  }

  return (
    <DriverProfileView
      profile={profile}
      feedback={feedback}
      onBack={handleBack}
      onLoadMoreFeedback={handleLoadMoreFeedback}
      isLoadingMoreFeedback={loadingMore}
      loadMoreError={loadMoreError}
      onRetryLoadMore={handleLoadMoreFeedback}
    />
  );
}
