"use client";

import React, { useEffect, useState } from "react";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import type { Locale } from "@/lib/locale";
import { roleStyle } from "@/lib/role-style";

type TabKey = "cockpit" | "analytics" | "profile";
type NavMessages = Record<string, string>;

function useClock(locale: Locale) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date()); // eslint-disable-line react-hooks/set-state-in-effect
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  if (!now) return "";
  const tag = locale === "vi" ? "vi-VN" : "en-GB";
  return `${now.toLocaleDateString(tag, { day: "2-digit", month: "2-digit", year: "numeric" })} · ${now.toLocaleTimeString(tag, { hour: "2-digit", minute: "2-digit" })}`;
}

export function PortalTopBar(props: {
  messages: NavMessages;
  locale: Locale;
  setLocale: (l: Locale) => void;
  activeTab: TabKey;
  setActiveTab: (t: TabKey) => void;
  searchQuery: string;
  setSearchQuery: (v: string) => void;
  analyst: { name: string; role: string } | null;
  e2eAuthBypass: boolean;
}) {
  const { messages, locale, setLocale, activeTab, setActiveTab, searchQuery, setSearchQuery, analyst, e2eAuthBypass } = props;
  const [open, setOpen] = useState(false);
  const clock = useClock(locale);
  const role = roleStyle(analyst?.role);
  const tabs: { key: TabKey; icon: string; label: string }[] = [
    { key: "cockpit", icon: "gavel", label: messages.cockpit },
    { key: "analytics", icon: "monitoring", label: messages.analytics },
    { key: "profile", icon: "badge", label: messages.profile },
  ];

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full shrink-0 select-none items-center justify-between gap-4 border-b border-gs-line bg-white pl-5 pr-4">
      <div className="relative flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          title={messages.catalog}
          aria-label={messages.catalog}
          aria-expanded={open}
          className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-[10px] bg-primary text-white transition-colors hover:bg-primary-container"
        >
          <span className="material-symbols-outlined text-[20px]">security</span>
        </button>
        <div className="hidden min-w-0 leading-tight sm:block">
          <div className="truncate text-[15px] font-extrabold text-on-surface">GreenSentinel</div>
          <div className="truncate text-[11px] text-gs-mute">{tabs.find((t) => t.key === activeTab)?.label}</div>
        </div>
        {open && (
          <div className="absolute left-0 top-12 z-40 w-64 space-y-1 rounded-xl border border-gs-line-2 bg-white p-2 shadow-lg">
            <div className="mb-1 border-b border-gs-line px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{messages.apps}</div>
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => { setActiveTab(t.key); setOpen(false); }}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] transition-colors ${activeTab === t.key ? "bg-primary-fixed font-bold text-primary" : "text-on-surface-variant hover:bg-surface"}`}
              >
                <span className="material-symbols-outlined text-[16px]">{t.icon}</span>
                <span>{t.label}</span>
              </button>
            ))}
          </div>
        )}
        <div className="hidden items-center gap-2 rounded-[10px] border border-gs-line-2 bg-white py-1 pl-3 pr-1.5 md:flex" title={analyst?.role}>
          <span className="text-xs text-gs-mute">{locale === "vi" ? "Vai trò" : "Role"}</span>
          <span className="rounded-full px-2.5 py-0.5 text-xs font-bold" style={{ background: role.bg, color: role.fg }} data-testid="role-badge">{role.label}</span>
        </div>
      </div>

      <div className="hidden min-w-0 max-w-xl flex-1 md:block">
        <div className="relative flex w-full items-center">
          <span className="material-symbols-outlined pointer-events-none absolute left-3 text-[18px] text-gs-mute">search</span>
          <input
            id="global-search-input"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label={messages.search}
            placeholder={messages.searchPlaceholder}
            className="h-10 w-full rounded-[10px] border border-gs-line-2 bg-surface pl-9 pr-16 text-[13px] text-on-surface transition-colors placeholder:text-gs-mute focus:border-primary focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary/25"
          />
          <kbd className="absolute right-2.5 rounded border border-gs-line-2 bg-white px-1.5 py-0.5 font-mono text-[10px] text-gs-mute-2">Ctrl+K</kbd>
        </div>
      </div>

      <div className="flex min-w-0 shrink-0 items-center justify-end gap-3 sm:gap-4">
        <span className="hidden whitespace-nowrap text-[13px] text-[#3a4552] xl:inline" suppressHydrationWarning>{clock}</span>
        <div role="group" aria-label={messages.languages} className="flex shrink-0 items-center gap-0.5 rounded-lg border border-gs-line-2 p-0.5 text-xs">
          {(["en", "vi"] as const).map((language) => (
            <button
              key={language}
              type="button"
              aria-label={language === "en" ? messages.english : messages.vietnamese}
              aria-pressed={locale === language}
              onClick={() => setLocale(language)}
              className={`rounded-md px-2 py-1 font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${locale === language ? "bg-primary text-white" : "text-gs-mute-2 hover:bg-surface"}`}
            >
              <span lang={language}>
                <span className="sm:hidden">{language.toUpperCase()}</span>
                <span className="hidden sm:inline">{language === "en" ? "English" : "Tiếng Việt"}</span>
              </span>
            </button>
          ))}
        </div>
        {!e2eAuthBypass ? (
          <>
            <OrganizationSwitcher hidePersonal={false} />
            {analyst?.name && <span className="hidden max-w-[160px] truncate text-sm font-bold text-on-surface lg:inline">{analyst.name}</span>}
            <UserButton />
          </>
        ) : (
          <div className="whitespace-nowrap font-mono text-xs text-gs-mute" data-testid="e2e-auth-indicator">{messages.e2e}</div>
        )}
      </div>
    </header>
  );
}
