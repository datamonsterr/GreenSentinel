'use client';

import React from 'react';
import { ProfileHeader } from './profile-header';
import { ProfileIdentityCard } from './profile-identity-card';
import { ProfileRatingSummary } from './profile-rating-summary';
import { ProfileKpiGrid } from './profile-kpi-grid';
import { ProfileFeedbackList } from './profile-feedback-list';
import type { DriverProfileResponse, DriverFeedbackResponse } from '@/types/schemas';

interface DriverProfileViewProps {
  profile: DriverProfileResponse;
  feedback: DriverFeedbackResponse;
  onBack?: () => void;
  onLoadMoreFeedback?: () => void;
  isLoadingMoreFeedback?: boolean;
  loadMoreError?: string | null;
  onRetryLoadMore?: () => void;
}

export function DriverProfileView({
  profile,
  feedback,
  onBack,
  onLoadMoreFeedback,
  isLoadingMoreFeedback = false,
  loadMoreError = null,
  onRetryLoadMore,
}: DriverProfileViewProps) {
  return (
    <div className="w-full max-w-md mx-auto flex flex-col min-h-screen bg-slate-50/60 dark:bg-slate-950/80 pb-28 text-slate-900 dark:text-slate-100 antialiased selection:bg-emerald-100 selection:text-emerald-900">
      <ProfileHeader onBack={onBack} />

      <main className="px-4 space-y-4 pt-3">
        <ProfileIdentityCard profile={profile} />

        <ProfileRatingSummary profile={profile} />

        <ProfileKpiGrid scorecard={profile.scorecard} />

        <ProfileFeedbackList
          feedback={feedback}
          onLoadMore={onLoadMoreFeedback}
          isLoadingMore={isLoadingMoreFeedback}
          loadMoreError={loadMoreError}
          onRetryLoadMore={onRetryLoadMore}
        />
      </main>
    </div>
  );
}
