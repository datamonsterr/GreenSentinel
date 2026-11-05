'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { Star, User, Loader2 } from 'lucide-react';
import type { DriverFeedbackResponse } from '@/types/schemas';

interface ProfileFeedbackListProps {
  feedback: DriverFeedbackResponse;
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
  loadMoreError?: string | null;
  onRetryLoadMore?: () => void;
}

export function ProfileFeedbackList({
  feedback,
  onLoadMore,
  isLoadingMore = false,
  loadMoreError = null,
  onRetryLoadMore,
}: ProfileFeedbackListProps) {
  const t = useTranslations('driver.profile');

  const { items, next_cursor } = feedback;
  const locale = t('dateLocale');

  const formatDate = (dateStr: string | null): string | null => {
    if (!dateStr) return null;
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return null;
      return new Intl.DateTimeFormat(locale, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(d);
    } catch {
      return null;
    }
  };

  return (
    <section className="space-y-3 pt-1">
      <div className="flex items-center justify-between px-1">
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
            {t('feedbackTitle')}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('feedbackSubtitle')}
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 text-center border border-slate-200/80 dark:border-slate-800 shadow-xs">
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {t('noFeedbackYet')}
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {items.map((item, idx) => {
            const stars = item.stars;
            const hasComment = item.comment && item.comment.trim().length > 0;
            const formattedDate = formatDate(item.date);

            return (
              <article
                key={item.id || idx}
                className="bg-white dark:bg-slate-900 rounded-2xl p-3.5 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-500 dark:text-slate-400">
                      <User className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-slate-900 dark:text-slate-100 leading-tight">
                        {t('anonymousCustomer')} #{idx + 1}
                      </h4>
                      {stars !== null && stars !== undefined ? (
                        <div className="flex items-center text-amber-500 mt-0.5">
                          {[...Array(5)].map((_, i) => (
                            <Star
                              key={i}
                              className={`w-3 h-3 ${
                                i < stars ? 'fill-current' : 'text-slate-200 dark:text-slate-700'
                              }`}
                            />
                          ))}
                        </div>
                      ) : (
                        <span className="text-[11px] text-slate-400 dark:text-slate-500 italic">
                          {t('noRating')}
                        </span>
                      )}
                    </div>
                  </div>
                  {formattedDate && (
                    <time className="text-[11px] text-slate-400 dark:text-slate-500">
                      {formattedDate}
                    </time>
                  )}
                </div>

                {hasComment ? (
                  <p className="text-xs text-slate-700 dark:text-slate-300 bg-slate-50/70 dark:bg-slate-800/40 p-2.5 rounded-xl border border-slate-200/40 dark:border-slate-800/60 leading-relaxed">
                    &ldquo;{item.comment}&rdquo;
                  </p>
                ) : (
                  <p className="text-xs text-slate-400 dark:text-slate-500 italic bg-slate-50/30 dark:bg-slate-800/20 p-2 rounded-lg border border-slate-200/30 dark:border-slate-800/40">
                    {t('noComment')}
                  </p>
                )}
              </article>
            );
          })}

          {loadMoreError && (
            <div className="text-center space-y-2 py-1">
              <p className="text-xs text-rose-600 dark:text-rose-400">{loadMoreError}</p>
              <button
                type="button"
                onClick={onRetryLoadMore}
                className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 underline"
              >
                {t('retry')}
              </button>
            </div>
          )}

          {next_cursor && !loadMoreError && (
            <div className="pt-2 text-center">
              <button
                type="button"
                onClick={onLoadMore}
                disabled={isLoadingMore}
                className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-white dark:bg-slate-900 text-emerald-600 dark:text-emerald-400 border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/80 active:scale-[0.99] transition-all flex items-center justify-center gap-2 shadow-xs disabled:opacity-50"
              >
                {isLoadingMore && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>{t('loadMore')}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
