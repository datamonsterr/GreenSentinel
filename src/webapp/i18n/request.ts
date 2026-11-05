import { getRequestConfig } from 'next-intl/server';
import { cookies } from 'next/headers';
import { DRIVER_TIME_ZONE, resolveLocale } from '@/lib/driver/locale';

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const localeCookie = cookieStore.get('NEXT_LOCALE')?.value;
  const locale = resolveLocale(localeCookie);

  return {
    locale,
    timeZone: DRIVER_TIME_ZONE,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
