'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { useUser } from '@clerk/nextjs';
import { Car } from 'lucide-react';
import type { DriverProfileResponse } from '@/types/schemas';

interface ProfileIdentityCardProps {
  profile: DriverProfileResponse;
}

export function ProfileIdentityCard({ profile }: ProfileIdentityCardProps) {
  const t = useTranslations('driver.profile');
  let user: ReturnType<typeof useUser>['user'] = null;
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const clerk = useUser();
    user = clerk?.user ?? null;
  } catch {
    user = null;
  }

  const rawDisplayName = profile.display_name;
  const isEmail = typeof rawDisplayName === 'string' && rawDisplayName.includes('@');
  const clerkName = user?.fullName || user?.firstName || null;
  const clerkEmail = user?.primaryEmailAddress?.emailAddress || null;
  const displayName =
    (isEmail && clerkName) ? clerkName
    : rawDisplayName
      || clerkName
      || clerkEmail
      || t('unnamedDriver');
  const avatarUrl = ((isEmail || !rawDisplayName) && user?.imageUrl) ? user.imageUrl : null;

  // Format member since date
  const formattedMemberSince = React.useMemo(() => {
    if (!profile.member_since) return null;
    try {
      const d = new Date(profile.member_since);
      if (isNaN(d.getTime())) return profile.member_since;
      return d.toLocaleDateString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      });
    } catch {
      return profile.member_since;
    }
  }, [profile.member_since]);

  return (
    <section className="bg-white dark:bg-slate-900 rounded-2xl p-4 shadow-xs border border-slate-200/80 dark:border-slate-800 flex items-center gap-3.5 relative overflow-hidden">
      {/* Avatar */}
      <div className="w-16 h-16 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 font-bold text-xl flex items-center justify-center ring-2 ring-emerald-500/30 shrink-0 overflow-hidden">
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt={displayName}
            className="w-full h-full object-cover"
            data-testid="driver-avatar-image"
          />
        ) : (
          <span>{displayName.charAt(0) || '?'}</span>
        )}
      </div>

      {/* Driver Meta */}
      <div className="flex-1 min-w-0">
        <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 truncate">
          {displayName}
        </h2>

        {/* Vehicle & License info */}
        <div className="flex items-center gap-1.5 mt-1 text-xs text-slate-600 dark:text-slate-400">
          <Car className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
          {profile.vehicle ? (
            <>
              {profile.vehicle.model && (
                <span className="font-medium text-slate-800 dark:text-slate-200 truncate">
                  {profile.vehicle.model}
                </span>
              )}
              {profile.vehicle.plate && (
                <>
                  <span className="text-slate-300 dark:text-slate-700">•</span>
                  <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[11px] font-mono font-bold tracking-wider text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700">
                    {profile.vehicle.plate}
                  </span>
                </>
              )}
            </>
          ) : (
            <span className="text-slate-400 dark:text-slate-500 italic">
              {t('noVehicle')}
            </span>
          )}
        </div>

        {formattedMemberSince && (
          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
            {t('memberSince', { date: formattedMemberSince })}
          </p>
        )}
      </div>
    </section>
  );
}
