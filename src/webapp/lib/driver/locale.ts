export const DEFAULT_LOCALE = 'vi' as const;
export const SUPPORTED_LOCALES = ['vi', 'en'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_COOKIE_NAME = 'NEXT_LOCALE';

/** GreenSM operates in Vietnam; render dates in local time on server and client alike. */
export const DRIVER_TIME_ZONE = 'Asia/Ho_Chi_Minh';

export function resolveLocale(value?: string | null): Locale {
  if (!value) return DEFAULT_LOCALE;
  const normalized = value.trim().toLowerCase();
  if (normalized === 'en') return 'en';
  if (normalized === 'vi') return 'vi';
  return DEFAULT_LOCALE;
}

export function setLocaleCookie(locale: Locale): void {
  if (typeof document !== 'undefined') {
    document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; path=/; max-age=31536000; SameSite=Lax`;
  }
}
