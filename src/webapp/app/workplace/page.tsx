"use client";

import React, { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { setApiTokenProvider, fetchCurrentAnalyst } from "@/lib/api-client";
import { PortalTopBar } from "@/components/portal/portal-top-bar";
import { canAuthor } from "@/lib/knowledge-ui";
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
  const [analyst, setAnalyst] = useState<{ name: string; role: string; roles: string[] } | null>(null);
  const [urlCaseId, setUrlCaseId] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      if (tab === "cockpit" || tab === "analytics" || tab === "profile") setActiveTab(tab);
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
    if (!apiReady || e2eAuthBypass) return;
    fetchCurrentAnalyst().then(setAnalyst).catch(() => setAnalyst(null));
  }, [apiReady, e2eAuthBypass]);

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
      <PortalTopBar
        messages={messages}
        locale={locale}
        setLocale={setLocale}
        activeTab={activeTab}
        setActiveTab={(tab) => (tab === "knowledge" ? window.location.assign("/knowledge") : setActiveTab(tab))}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        analyst={analyst}
        e2eAuthBypass={e2eAuthBypass}
        canOpenKnowledge={canAuthor(analyst?.roles ?? [])}
      />

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
