"use client";

import React, { Suspense } from "react";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import { DriverCasesView } from "@/components/driver/cases";

export default function DriverCasesPage() {
  return (
    <DriverI18nProvider>
      <Suspense
        fallback={
          <div className="flex-1 min-h-[50vh] flex items-center justify-center p-8">
            <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          </div>
        }
      >
        <DriverCasesView />
      </Suspense>
    </DriverI18nProvider>
  );
}
