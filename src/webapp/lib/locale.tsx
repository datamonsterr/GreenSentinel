"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Locale = "en" | "vi";
type LocaleContextValue = { locale: Locale; setLocale: (locale: Locale) => void };
const storageKey = "greensentinel.locale";
const LocaleContext = createContext<LocaleContextValue>({ locale: "en", setLocale: () => {} });

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, updateLocale] = useState<Locale>("en");

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved === "en" || saved === "vi") updateLocale(saved);
    } catch {
      // Private browsing and blocked storage retain the English default.
    }
  }, []);

  useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    updateLocale(next);
    try { window.localStorage.setItem(storageKey, next); } catch {
      // Switching remains available when persistence is unavailable.
    }
  }, []);
  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale() { return useContext(LocaleContext); }
