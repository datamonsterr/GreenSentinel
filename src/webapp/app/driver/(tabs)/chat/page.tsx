"use client";

import React from "react";
import { DriverChatView } from "@/components/driver/chat/driver-chat-view";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";

export default function DriverChatIndexPage() {
  return (
    <DriverI18nProvider>
      <div
        data-testid="driver-chat-container"
        className="flex flex-col shrink-0 h-[calc(100dvh-5rem)] min-h-0 overflow-hidden pb-[max(1rem,env(safe-area-inset-bottom))]"
      >
        <DriverChatView />
      </div>
    </DriverI18nProvider>
  );
}
