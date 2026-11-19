"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { DriverBottomNav } from "@/components/driver/driver-bottom-nav";

// Case chat (/driver/chat/<caseId>) is full-screen: no bottom nav.
const CASE_CHAT_ROUTE = /^\/driver\/chat\/[^/]+/;

export default function DriverTabsLayout({ children }: { children: React.ReactNode }) {
  const hideNav = CASE_CHAT_ROUTE.test(usePathname() || "");
  return (
    <div className="min-h-screen bg-[#e3e8ea] dark:bg-slate-950 flex justify-center text-slate-900 dark:text-slate-100 antialiased">
      <div
        data-testid="driver-tabs-shell"
        className={`w-full max-w-md min-h-screen bg-[var(--driver-canvas)] dark:bg-slate-900 flex flex-col relative shadow-sm ${hideNav ? "" : "pb-20"}`}
      >
        <div className="flex-1 flex flex-col overflow-y-auto">
          {children}
        </div>
        {!hideNav && <DriverBottomNav />}
      </div>
    </div>
  );
}
