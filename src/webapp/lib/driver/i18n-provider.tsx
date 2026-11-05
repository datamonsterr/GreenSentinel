'use client';

import React, { createContext, useContext } from 'react';
import { NextIntlClientProvider } from 'next-intl';
import viMessages from '@/messages/vi.json';
import enMessages from '@/messages/en.json';
import { DEFAULT_LOCALE, DRIVER_TIME_ZONE, type Locale } from './locale';

const HasDriverI18nContext = createContext<boolean>(false);

const MESSAGES_BY_LOCALE: Record<Locale, Record<string, any>> = {
  vi: viMessages,
  en: enMessages,
};

export interface DriverI18nProviderProps {
  children: React.ReactNode;
  locale?: Locale;
  messages?: Record<string, any>;
}

/**
 * DriverI18nProvider wraps children in NextIntlClientProvider.
 * If already wrapped by an outer NextIntlClientProvider (such as in driver/layout.tsx),
 * it passes children through without nesting redundant providers.
 */
export function DriverI18nProvider({
  children,
  locale = DEFAULT_LOCALE,
  messages,
}: DriverI18nProviderProps) {
  const isAlreadyWrapped = useContext(HasDriverI18nContext);

  if (isAlreadyWrapped) {
    return <>{children}</>;
  }

  const resolvedMessages = messages || MESSAGES_BY_LOCALE[locale] || viMessages;

  return (
    <HasDriverI18nContext.Provider value={true}>
      <NextIntlClientProvider locale={locale} messages={resolvedMessages} timeZone={DRIVER_TIME_ZONE}>
        {children}
      </NextIntlClientProvider>
    </HasDriverI18nContext.Provider>
  );
}
