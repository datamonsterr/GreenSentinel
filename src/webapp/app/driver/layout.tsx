import { cookies } from 'next/headers';
import { Be_Vietnam_Pro } from 'next/font/google';
import './driver-theme.css';
import { getLocale, getMessages } from 'next-intl/server';
import { DriverAuthBoundary } from '@/components/driver/driver-auth-boundary';
import { DriverI18nProvider } from '@/lib/driver/i18n-provider';
import { type Locale } from '@/lib/driver/locale';
import { resolveTheme } from '@/lib/driver/theme';
import { localTestAuthentication } from '@/lib/route-authorization';
import { requirePageAccess } from '@/lib/server-route-guard';

const driverFont = Be_Vietnam_Pro({ subsets: ['latin', 'vietnamese'], weight: ['400', '500', '600', '700'], variable: '--font-driver', display: 'swap' });

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  await requirePageAccess('driver');
  const locale = (await getLocale()) as Locale;
  const messages = (await getMessages()) as Record<string, any>;
  const cookieStore = await cookies();
  const theme = resolveTheme(cookieStore.get('theme')?.value);

  const content = localTestAuthentication() ? children : <DriverAuthBoundary>{children}</DriverAuthBoundary>;

  return (
    <DriverI18nProvider locale={locale} messages={messages}>
      <div
        id="driver-root"
        data-theme-scope="driver"
        className={`${driverFont.variable} driver-scope ${theme === 'dark' ? 'dark' : 'light'} min-h-screen`}
        suppressHydrationWarning
      >
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var m=document.cookie.match(/(?:^|; )theme=([^;]*)/);var t=m?decodeURIComponent(m[1]):null;var el=document.getElementById('driver-root');if(el&&t){el.classList.remove('light','dark');el.classList.add(t==='dark'?'dark':'light');}}catch(e){}})();`,
          }}
        />
        {content}
      </div>
    </DriverI18nProvider>
  );
}
