"use client";

import React, { useState, useEffect } from "react";
import { OrganizationSwitcher, UserButton, useAuth } from "@clerk/nextjs";
import { setApiTokenProvider } from "@/lib/api-client";
import { CockpitWorkspaceView } from "@/components/views/cockpit-view";
import { AnalyticsDashboardView } from "@/components/views/analytics-view";
import { AnalystProfileView } from "@/components/views/profile-view";
import { WorkspaceInitSkeleton } from "@/components/ui/skeleton";
import { isolatedGisBuild } from '@/lib/isolated-gis-build';
import { useLocale } from '@/lib/locale';
import { navigationMessages } from '@/lib/navigation-messages';

type TabKey = "cockpit" | "analytics" | "profile";

export default function WorkplacePage() {
  const { locale, setLocale } = useLocale();
  const messages = navigationMessages[locale];
  const e2eAuthBypass = (process.env.NODE_ENV !== "production" || isolatedGisBuild()) && process.env.NEXT_PUBLIC_E2E_TEST === "true";
  // The E2E build omits ClerkProvider; the static env branch keeps production auth unchanged.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const clerkAuth = e2eAuthBypass ? { getToken: async () => null, isLoaded: true } : useAuth();
  const getToken = e2eAuthBypass ? async () => null : clerkAuth.getToken;
  const isLoaded = e2eAuthBypass || clerkAuth.isLoaded;
  const [apiReady, setApiReady] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>("cockpit");
  const [searchQuery, setSearchQuery] = useState("");
  const [appSwitcherOpen, setAppSwitcherOpen] = useState(false);
  const [urlCaseId, setUrlCaseId] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const cid = params.get("caseId") || params.get("case_id");
      if (cid) setUrlCaseId(cid);
    }
  }, []);

  const getTokenRef = React.useRef(getToken);
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  useEffect(() => {
    if (!isLoaded) return;
    setApiTokenProvider((options) => getTokenRef.current(options));
    setApiReady(true);
    return () => {
      setApiTokenProvider(null);
      setApiReady(false);
    };
  }, [isLoaded]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        const el = document.getElementById("global-search-input");
        if (el) el.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  if (!apiReady) return <WorkspaceInitSkeleton message={messages.opening} />;

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden bg-background">
      {/* Top Application Sub-Header / Search & Tab Bar */}
      <div className="h-10 w-full bg-surface-container-lowest border-b border-outline-variant/60 flex items-center justify-between px-3 lg:px-0 select-none shrink-0 z-30 flex-nowrap">
        {/* Left: Quick App Switcher & Avatar — matches the 22% case-queue column */}
        <div className="flex items-center gap-2 relative shrink-0 lg:w-[22%] lg:pl-3">
          <div className="relative">
            <button
              onClick={() => setAppSwitcherOpen(!appSwitcherOpen)}
              className="w-7 h-7 rounded bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 flex items-center justify-center text-white shadow-xs transition-colors cursor-pointer"
              title={messages.catalog}
              aria-label={messages.catalog}
              aria-expanded={appSwitcherOpen}
              type="button"
            >
              <span className="material-symbols-outlined text-[16px]">security</span>
            </button>

            {appSwitcherOpen && (
              <div className="absolute left-0 top-9 w-64 bg-white border border-slate-200 rounded shadow-lg z-40 p-2 space-y-1">
                <div className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold border-b border-slate-100 mb-1">
                  {messages.apps}
                </div>
                <button
                  onClick={() => {
                    setActiveTab("cockpit");
                    setAppSwitcherOpen(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left ${
                    activeTab === "cockpit"
                      ? "bg-emerald-50 text-emerald-800 font-semibold border border-emerald-200"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="material-symbols-outlined text-[15px] text-emerald-600">gavel</span>
                  <span>{messages.cockpit}</span>
                </button>
                <button
                  onClick={() => {
                    setActiveTab("analytics");
                    setAppSwitcherOpen(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left ${
                    activeTab === "analytics"
                      ? "bg-emerald-50 text-emerald-800 font-semibold border border-emerald-200"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="material-symbols-outlined text-[15px] text-slate-500">monitoring</span>
                  <span>{messages.analytics}</span>
                </button>
                <button
                  onClick={() => {
                    setActiveTab("profile");
                    setAppSwitcherOpen(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left ${
                    activeTab === "profile"
                      ? "bg-emerald-50 text-emerald-800 font-semibold border border-emerald-200"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="material-symbols-outlined text-[15px] text-slate-500">badge</span>
                  <span>{messages.profile}</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Center: Search Bar with Ctrl+K — spans the 50% center-panel column */}
        <div className="flex-1 min-w-0 px-3 hidden md:block lg:flex-none lg:w-[50%]">
          <div className="relative flex items-center w-full">
            <span className="material-symbols-outlined absolute left-2 text-secondary text-[16px] pointer-events-none">
              search
            </span>
            <input
              id="global-search-input"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label={messages.search}
              placeholder={messages.searchPlaceholder}
              className="w-full h-7 pl-7 pr-14 text-xs bg-surface rounded border border-outline-variant/70 focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none transition-colors"
            />
            <kbd className="absolute right-2 font-mono text-[10px] bg-surface-container-lowest text-secondary px-1 py-0.5 rounded border border-outline-variant">
              Ctrl+K
            </kbd>
          </div>
        </div>

        <div className="flex min-w-0 items-center justify-end gap-1.5 sm:gap-2 shrink-0 lg:flex-1 lg:shrink lg:pr-3">
          <div role="group" aria-label={messages.languages} className="flex items-center gap-0.5 rounded border border-outline-variant/70 p-0.5 text-xs shrink-0">
            {(["en", "vi"] as const).map((language) => (
              <button
                key={language}
                type="button"
                aria-label={language === "en" ? messages.english : messages.vietnamese}
                aria-pressed={locale === language}
                onClick={() => setLocale(language)}
                className={`rounded px-1.5 py-0.5 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${locale === language ? "bg-emerald-600 text-white" : "text-secondary hover:bg-surface"}`}
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
              <UserButton />
            </>
          ) : (
            <div className="whitespace-nowrap text-xs text-slate-500 font-mono" data-testid="e2e-auth-indicator">
              {messages.e2e}
            </div>
          )}
        </div>
      </div>

      {/* Tab Contents */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {activeTab === "cockpit" && <CockpitWorkspaceView initialCaseId={urlCaseId} />}
        {activeTab === "analytics" && <AnalyticsDashboardView />}
        {activeTab === "profile" && (
          <AnalystProfileView onResumeCase={() => setActiveTab("cockpit")} />
        )}
      </div>
    </div>
  );
}
