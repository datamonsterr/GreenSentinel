'use client';

import { useAuth } from '@clerk/nextjs';
import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';
import { setApiTokenProvider } from '@/lib/api-client';

/** Mount Driver data consumers only after Clerk can authenticate their API requests. */
export function DriverAuthBoundary({ children }: { children: React.ReactNode }) {
  const t = useTranslations('driver.authBoundary');
  const { getToken, isLoaded, userId } = useAuth();
  const token = useRef(getToken);
  useEffect(() => {
    token.current = getToken;
  }, [getToken]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!isLoaded || !userId) return;
    setApiTokenProvider((options) => token.current(options));
    setReady(true);
    return () => { setApiTokenProvider(null); setReady(false); };
  }, [isLoaded, userId]);
  if (!ready || !userId) return <p role="status">{t('loadingSession')}</p>;
  return children;
}
