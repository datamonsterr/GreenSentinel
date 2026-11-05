'use client';

import React from 'react';
import { useTranslations } from 'next-intl';

interface ProfileHeaderProps {
  onBack?: () => void;
}

export function ProfileHeader({ onBack: _onBack }: ProfileHeaderProps = {}) {
  const t = useTranslations('driver.profile');

  return (
    <header className="sticky top-0 z-40 w-full px-4 h-14 max-w-md mx-auto flex justify-center items-center bg-white dark:bg-slate-900 border-b border-slate-200/80 dark:border-slate-800 shadow-xs">
      <h1 className="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight text-center">
        {t('title')}
      </h1>
    </header>
  );
}
