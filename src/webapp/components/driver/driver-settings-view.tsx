'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import { useUser, useClerk } from '@clerk/nextjs';
import {
  User as UserIcon,
  ChevronRight,
  Sun,
  Moon,
  Info,
  Palette,
  LogOut,
} from 'lucide-react';
import { setLocaleCookie, type Locale } from '@/lib/driver/locale';
import { getClientTheme, setTheme, type Theme } from '@/lib/driver/theme';

export function DriverSettingsView() {
  const router = useRouter();
  const t = useTranslations('driver.settings');
  const locale = useLocale();
  const { user } = useUser();
  const clerk = useClerk();

  const [currentTheme, setCurrentTheme] = useState<Theme>('light');
  const [appVersion, setAppVersion] = useState<string>('0.1.0');

  useEffect(() => {
    setCurrentTheme(getClientTheme());
    setAppVersion(process.env.NEXT_PUBLIC_APP_VERSION || '0.1.0');
  }, []);

  const handleThemeChange = (theme: Theme) => {
    setTheme(theme);
    setCurrentTheme(theme);
  };

  const handleLocaleChange = (newLocale: Locale) => {
    setLocaleCookie(newLocale);
    router.refresh();
  };

  const handleSignOut = async () => {
    try {
      if (typeof clerk?.signOut === 'function') {
        await clerk.signOut(() => router.push('/sign-in'));
      } else {
        router.push('/sign-in');
      }
    } catch {
      router.push('/sign-in');
    }
  };

  const handleManageAccount = () => {
    if (typeof clerk?.openUserProfile === 'function') {
      clerk.openUserProfile();
    }
  };

  const emailDisplay = user?.primaryEmailAddress?.emailAddress || (t.has('noEmail') ? t('noEmail') : '');

  return (
    <div className="flex-1 w-full max-w-md mx-auto flex flex-col bg-slate-50 dark:bg-slate-950 pb-24 text-slate-900 dark:text-slate-100 antialiased">
      {/* Header */}
      <header className="bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 px-4 py-3 sticky top-0 z-30 shadow-xs flex items-center justify-between">
        <div>
          <h1 className="text-base font-bold text-slate-900 dark:text-slate-100">{t('title')}</h1>
          <p className="text-xs text-emerald-700 dark:text-emerald-400 font-semibold flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 inline-block" />
            {t('driverPartner')}
          </p>
        </div>
      </header>

      {/* Main Content */}
      <main className="p-4 space-y-4">
        {/* Profile Card */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl p-4 border border-slate-200 dark:border-slate-800 shadow-xs relative overflow-hidden">
          <div className="flex items-start gap-3.5">
            {/* Avatar */}
            <div className="relative shrink-0">
              {user?.imageUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={user.imageUrl}
                  alt={t('avatarAlt')}
                  className="w-14 h-14 rounded-full object-cover ring-2 ring-emerald-500/20 shadow-xs"
                />
              ) : (
                <div className="w-14 h-14 rounded-full bg-emerald-100 dark:bg-emerald-950/60 flex items-center justify-center text-emerald-700 dark:text-emerald-300 ring-2 ring-emerald-500/20">
                  <UserIcon className="w-7 h-7" />
                </div>
              )}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate">
                {user?.fullName || t('driverPartner')}
              </h2>
              {emailDisplay && (
                <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                  {emailDisplay}
                </p>
              )}
            </div>
          </div>

          {/* Manage Account Row */}
          <div className="mt-3.5 pt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">
              {t('securityAndLicense')}
            </span>
            <button
              type="button"
              onClick={handleManageAccount}
              className="inline-flex items-center gap-1 text-xs font-bold text-emerald-700 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300 transition-colors py-1 px-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 active:scale-95 cursor-pointer"
            >
              {t('manageAccount')}
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </section>

        {/* Section 1: Theme & Experience */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl p-4 border border-slate-200 dark:border-slate-800 shadow-xs space-y-4">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
            <Palette className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h3 className="text-xs font-bold text-slate-900 dark:text-slate-100 uppercase tracking-wider">
              {t('sectionExperience')}
            </h3>
          </div>

          {/* Theme Toggle */}
          <div className="flex items-center justify-between py-1">
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">{t('theme')}</div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">{t('themeDesc')}</div>
            </div>
            <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-xl flex items-center gap-1 border border-slate-200 dark:border-slate-700">
              <button
                type="button"
                onClick={() => handleThemeChange('light')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                  currentTheme === 'light'
                    ? 'bg-white text-emerald-700 shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Sun className="w-3.5 h-3.5" />
                {t('themeLight')}
              </button>
              <button
                type="button"
                onClick={() => handleThemeChange('dark')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                  currentTheme === 'dark'
                    ? 'bg-slate-900 text-emerald-400 shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <Moon className="w-3.5 h-3.5" />
                {t('themeDark')}
              </button>
            </div>
          </div>

          {/* Language Toggle */}
          <div className="flex items-center justify-between py-1 border-t border-slate-100 dark:border-slate-800/80 pt-3">
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">{t('language')}</div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">{t('languageDesc')}</div>
            </div>
            <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-xl flex items-center gap-1 border border-slate-200 dark:border-slate-700">
              <button
                type="button"
                onClick={() => handleLocaleChange('vi')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  locale === 'vi'
                    ? 'bg-emerald-700 text-white shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                {t('langVi')}
              </button>
              <button
                type="button"
                onClick={() => handleLocaleChange('en')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  locale === 'en'
                    ? 'bg-emerald-700 text-white shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                {t('langEn')}
              </button>
            </div>
          </div>
        </section>

        {/* Section 2: Info & Support */}
        <section className="bg-white dark:bg-slate-900 rounded-2xl p-4 border border-slate-200 dark:border-slate-800 shadow-xs space-y-3">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
            <Info className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h3 className="text-xs font-bold text-slate-900 dark:text-slate-100 uppercase tracking-wider">
              {t('sectionInfo')}
            </h3>
          </div>

          {/* App Version */}
          <div className="flex items-center justify-between py-1.5">
            <div>
              <div className="text-xs font-semibold text-slate-900 dark:text-slate-100">{t('appVersion')}</div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">v{appVersion}</div>
            </div>
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
              {t('versionLatest')}
            </span>
          </div>
        </section>

        {/* Sign Out Button */}
        <section className="pt-2">
          <button
            type="button"
            onClick={handleSignOut}
            className="w-full min-h-[48px] bg-red-50 hover:bg-red-100 dark:bg-red-950/30 dark:hover:bg-red-900/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/50 font-semibold rounded-2xl px-4 py-3 flex items-center justify-center gap-2 transition-all active:scale-[0.99] shadow-xs cursor-pointer"
          >
            <LogOut className="w-4 h-4" />
            <span className="text-xs font-bold">{t('signOut')}</span>
          </button>
        </section>
      </main>
    </div>
  );
}
