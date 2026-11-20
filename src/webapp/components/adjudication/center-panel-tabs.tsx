"use client";

import React, { useRef } from "react";
import { useLocale } from "@/lib/locale";
import { workspaceMessages } from "@/lib/workspace-messages";

export type CenterTabType = "overview" | "maps" | "customer" | "driver" | "finalization";

interface CenterPanelTabsProps {
  activeTab: CenterTabType;
  onTabChange: (tab: CenterTabType) => void;
  conversationCount?: number;
  driverRiskScore?: number;
}

export const CenterPanelTabs: React.FC<CenterPanelTabsProps> = ({
  activeTab,
  onTabChange,
}) => {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const { locale } = useLocale();
  const messages = workspaceMessages[locale];
  const tabs: Array<{ id: CenterTabType; label: string; icon: string }> = [
    { id: "overview", label: messages.tabs.overview, icon: "dashboard" },
    { id: "maps", label: messages.tabs.maps, icon: "map" },
    { id: "customer", label: messages.tabs.customer, icon: "forum" },
    { id: "driver", label: messages.tabs.driver, icon: "badge" },
    { id: "finalization", label: messages.tabs.finalization, icon: "fact_check" },
  ];

  return (
    <nav
      role="tablist"
      aria-label={messages.views}
      className="grid grid-cols-3 gap-1 border-x border-b border-slate-200 bg-slate-50 p-0.5 sm:grid-cols-5 shrink-0 select-none w-full"
    >
      {tabs.map((tab, index) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`panel-${tab.id}`}
            id={`tab-${tab.id}`}
            tabIndex={isActive ? 0 : -1}
            ref={(element) => { tabRefs.current[index] = element; }}
            onClick={() => onTabChange(tab.id)}
            onKeyDown={(event) => {
              let nextIndex: number | undefined;
              if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
              if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
              if (event.key === "Home") nextIndex = 0;
              if (event.key === "End") nextIndex = tabs.length - 1;
              if (nextIndex === undefined) return;
              event.preventDefault();
              const nextTab = tabs[nextIndex];
              onTabChange(nextTab.id);
              tabRefs.current[nextIndex]?.focus();
            }}
            className={`inline-flex min-w-0 min-h-7 items-center justify-center gap-1 rounded-md border px-1.5 py-1 text-[11px] leading-4 font-medium transition-colors w-full focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary ${
              isActive
                ? "bg-white text-primary font-semibold shadow-xs border-slate-200"
                : "border-transparent text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"
            }`}
          >
            <span
              className={`material-symbols-outlined !text-[14px] !leading-none shrink-0 ${
                isActive ? "text-primary" : "text-slate-400"
              }`}
              aria-hidden="true"
            >
              {tab.icon}
            </span>
            <span className="truncate">{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
};
