'use client';

import React from 'react';
import { useTranslations } from 'next-intl';

export type HistoryFilterStatus = 'all' | 'completed' | 'flagged';

export interface HistorySegmentedTabsProps {
  activeTab: HistoryFilterStatus;
  onChange: (tab: HistoryFilterStatus) => void;
  counts?: {
    all?: number;
    completed?: number;
    flagged?: number;
  };
}

export function HistorySegmentedTabs({
  activeTab,
  onChange,
  counts,
}: HistorySegmentedTabsProps) {
  const t = useTranslations('driver.history');

  const tabs: Array<{
    id: HistoryFilterStatus;
    label: string;
    count?: number;
    isAlert?: boolean;
  }> = [
    { id: 'all', label: t('tabAll'), count: counts?.all },
    { id: 'completed', label: t('tabCompleted'), count: counts?.completed },
    { id: 'flagged', label: t('tabFlagged'), count: counts?.flagged, isAlert: true },
  ];

  return (
    <div
      role="tablist"
      aria-label={t('title')}
      className="flex items-center space-x-2 overflow-x-auto no-scrollbar py-1"
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all active:scale-95 shrink-0 ${
              isActive
                ? 'bg-emerald-600 text-white shadow-xs dark:bg-emerald-600 dark:text-white'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <span>{tab.label}</span>
            {tab.count != null && (
              <span
                className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                  isActive
                    ? 'bg-emerald-700/60 text-white'
                    : tab.isAlert && tab.count > 0
                    ? 'bg-red-500 text-white'
                    : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
