"use client";

import React, { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { DriverChatView } from "@/components/driver/chat/driver-chat-view";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";

export default function DriverChatCasePage({
  params,
}: {
  params?: Promise<{ caseId: string }>;
}) {
  const routeParams = useParams();
  const [caseId, setCaseId] = useState<string>("");

  useEffect(() => {
    if (params) {
      params.then((p) => {
        if (p?.caseId) setCaseId(p.caseId);
      });
    } else if (routeParams?.caseId) {
      setCaseId(routeParams.caseId as string);
    }
  }, [params, routeParams]);

  if (!caseId) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center p-4">
        <div className="w-8 h-8 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <DriverI18nProvider>
      <div
        data-testid="driver-chat-container"
        className="flex flex-col shrink-0 h-dvh min-h-0 overflow-hidden"
      >
        <DriverChatView caseId={caseId} />
      </div>
    </DriverI18nProvider>
  );
}
