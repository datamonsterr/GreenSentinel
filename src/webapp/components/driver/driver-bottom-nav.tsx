'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { Shield, User, Sparkles, History, Settings } from 'lucide-react';

interface TabItem {
  id: string;
  href: string;
  labelKey: string;
  icon: React.ComponentType<{ className?: string }>;
  isCenter?: boolean;
}

const TABS: TabItem[] = [
  { id: 'cases', href: '/driver/cases', labelKey: 'cases', icon: Shield },
  { id: 'profile', href: '/driver/profile', labelKey: 'profile', icon: User },
  { id: 'chat', href: '/driver/chat', labelKey: 'chat', icon: Sparkles, isCenter: true },
  { id: 'history', href: '/driver/history', labelKey: 'history', icon: History },
  { id: 'settings', href: '/driver/settings', labelKey: 'settings', icon: Settings },
];

export function DriverBottomNav() {
  const pathname = usePathname() || '';
  const t = useTranslations('driver.tabs');

  return (
    <nav
      role="navigation"
      aria-label={t('navAriaLabel')}
      className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md z-40 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border-t border-slate-200 dark:border-slate-800 shadow-lg flex justify-around items-center px-1.5 pt-1 pb-[max(0.375rem,env(safe-area-inset-bottom))] min-h-[56px]"
    >
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const isActive = pathname.startsWith(tab.href);
        const label = t(tab.labelKey);

        if (tab.isCenter) {
          return (
            <Link
              key={tab.id}
              href={tab.href}
              aria-current={isActive ? 'page' : undefined}
              className="flex flex-col items-center justify-center -mt-5 relative active:scale-95 transition-transform duration-150 group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 rounded-full"
            >
              <div
                className={`w-12 h-12 rounded-full flex items-center justify-center shadow-md ring-4 ring-white dark:ring-slate-900 transition-colors ${
                  isActive
                    ? 'bg-emerald-600 text-white ring-emerald-200 dark:ring-emerald-950'
                    : 'bg-emerald-700 dark:bg-emerald-600 text-white group-hover:bg-emerald-600'
                }`}
              >
                <Icon className="w-5 h-5" />
              </div>
              <span
                className={`text-[10.5px] font-bold mt-0.5 tracking-tight ${
                  isActive ? 'text-emerald-700 dark:text-emerald-400' : 'text-emerald-800 dark:text-emerald-500'
                }`}
              >
                {label}
              </span>
            </Link>
          );
        }

        return (
          <Link
            key={tab.id}
            href={tab.href}
            aria-current={isActive ? 'page' : undefined}
            className={`flex flex-col items-center justify-center py-1 flex-1 active:scale-95 transition-all duration-150 relative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 rounded-lg ${
              isActive
                ? 'text-emerald-700 dark:text-emerald-400 font-bold'
                : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100 font-medium'
            }`}
          >
            <Icon className="w-5 h-5 mb-0.5" />
            <span className="text-[11px] leading-tight">{label}</span>
            {isActive && (
              <span className="w-1 h-1 bg-emerald-700 dark:bg-emerald-400 rounded-full absolute bottom-0" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
