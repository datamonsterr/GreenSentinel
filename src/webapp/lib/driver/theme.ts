export type Theme = 'light' | 'dark';

export const THEME_COOKIE_NAME = 'theme';

export function resolveTheme(value?: string | null): Theme {
  if (value === 'dark') return 'dark';
  return 'light';
}

export function getClientTheme(): Theme {
  if (typeof document === 'undefined') return 'light';
  const match = document.cookie.match(/(?:^|; )theme=([^;]*)/);
  if (match && (match[1] === 'dark' || match[1] === 'light')) {
    return match[1] as Theme;
  }
  const root = document.getElementById('driver-root');
  if (root?.classList.contains('dark')) return 'dark';
  return 'light';
}

export function setTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;

  const root = document.getElementById('driver-root');
  if (root) {
    root.classList.remove('light', 'dark');
    root.classList.add(theme);
  }

  document.cookie = `${THEME_COOKIE_NAME}=${theme}; path=/; max-age=31536000; SameSite=Lax`;
}
