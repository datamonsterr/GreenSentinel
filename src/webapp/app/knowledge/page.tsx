"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { fetchCurrentAnalyst, setApiTokenProvider } from "@/lib/api-client";
import { PortalTopBar } from "@/components/portal/portal-top-bar";
import { KnowledgeShell } from "@/components/knowledge/knowledge-shell";
import { WorkspaceInitSkeleton } from "@/components/ui/skeleton";
import { isolatedGisBuild } from "@/lib/isolated-gis-build";
import { useLocale } from "@/lib/locale";
import { navigationMessages } from "@/lib/navigation-messages";

type Analyst = { id: string; name: string; role: string; roles: string[] };

export default function KnowledgePage() {
  const router = useRouter();
  const { locale, setLocale } = useLocale();
  const messages = navigationMessages[locale];
  const e2eAuthBypass = (process.env.NODE_ENV !== "production" || isolatedGisBuild()) && process.env.NEXT_PUBLIC_E2E_TEST === "true";
  // The E2E build omits ClerkProvider; the static env branch keeps production auth unchanged.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const clerkAuth = e2eAuthBypass ? { getToken: async () => null, isLoaded: true } : useAuth();
  const getToken = e2eAuthBypass ? async () => null : clerkAuth.getToken;
  const isLoaded = e2eAuthBypass || clerkAuth.isLoaded;
  const [apiReady, setApiReady] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [me, setMe] = useState<Analyst | null>(null);

  const getTokenRef = useRef(getToken);
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  useEffect(() => {
    if (!isLoaded) return;
    setApiTokenProvider((options) => getTokenRef.current(options));
    setApiReady(true);
    return () => { setApiTokenProvider(null); setApiReady(false); };
  }, [isLoaded]);

  useEffect(() => {
    if (!apiReady) return;
    fetchCurrentAnalyst().then(setMe).catch(() => setMe(null));
  }, [apiReady]);

  if (!apiReady) return <WorkspaceInitSkeleton message={messages.opening} />;

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background">
      <PortalTopBar
        messages={messages}
        locale={locale}
        setLocale={setLocale}
        activeTab="knowledge"
        setActiveTab={(tab) => router.push(tab === "knowledge" ? "/knowledge" : `/workplace?tab=${tab}`)}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        analyst={me ? { name: me.name, role: me.role } : null}
        e2eAuthBypass={e2eAuthBypass}
        canOpenKnowledge
      />
      {me ? <KnowledgeShell me={{ id: me.id, roles: me.roles }} /> : <WorkspaceInitSkeleton message={messages.opening} />}
    </div>
  );
}
