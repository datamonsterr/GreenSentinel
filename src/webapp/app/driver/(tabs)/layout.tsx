import React from 'react';
import { DriverBottomNav } from '@/components/driver/driver-bottom-nav';

export default function DriverTabsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-950 flex justify-center text-slate-900 dark:text-slate-100 antialiased">
      <div className="w-full max-w-md min-h-screen bg-white dark:bg-slate-900 flex flex-col relative pb-20 shadow-sm">
        <div className="flex-1 flex flex-col overflow-y-auto">
          {children}
        </div>
        <DriverBottomNav />
      </div>
    </div>
  );
}
