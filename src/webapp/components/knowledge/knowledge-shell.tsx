"use client";

import React, { useCallback, useEffect, useState } from "react";
import { NextIntlClientProvider, useTranslations } from "next-intl";
import { useLocale } from "@/lib/locale";
import en from "@/messages/en.json";
import vi from "@/messages/vi.json";
import { knowledgeApi } from "@/lib/knowledge-client";
import type { Me } from "@/lib/knowledge-ui";
import { StorePanel } from "@/components/knowledge/store-panel";
import { DocumentsPanel } from "@/components/knowledge/documents-panel";
import { AgentsPanel } from "@/components/knowledge/agents-panel";
import { ConfigPanel } from "@/components/knowledge/config-panel";
import { ProposalsPanel } from "@/components/knowledge/proposals-panel";

export type PanelKey = "store" | "documents" | "agents" | "config" | "proposals";
const NAV: { key: PanelKey; icon: string }[] = [
  { key: "store", icon: "menu_book" },
  { key: "documents", icon: "description" },
  { key: "agents", icon: "smart_toy" },
  { key: "config", icon: "tune" },
  { key: "proposals", icon: "inbox" },
];

function Inner({ me }: { me: Me }) {
  const t = useTranslations("knowledge");
  const [panel, setPanel] = useState<PanelKey>("store");
  const [pending, setPending] = useState<number | null>(null);
  const refreshCounts = useCallback(() => {
    knowledgeApi.proposals({ status: "pending" }).then((r) => setPending(r.items.length)).catch(() => setPending(null));
  }, []);
  useEffect(() => { refreshCounts(); }, [refreshCounts]);

  return (
    <div className="flex min-h-0 flex-1" data-testid="knowledge-shell">
      <nav aria-label={t("nav.label")} className="hidden w-60 shrink-0 flex-col gap-1 border-r border-gs-line bg-white p-3 md:flex">
        <div className="px-2 pb-2 pt-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("nav.section")}</div>
        {NAV.map((n) => (
          <button key={n.key} type="button" data-testid={`nav-${n.key}`} aria-current={panel === n.key ? "page" : undefined} onClick={() => setPanel(n.key)}
            className={`flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[13px] transition-colors ${panel === n.key ? "bg-primary-fixed font-bold text-primary" : "text-gs-ink-2 hover:bg-surface"}`}>
            <span className="material-symbols-outlined text-[18px]">{n.icon}</span>
            <span className="flex-1">{t(`nav.${n.key}`)}</span>
            {n.key === "proposals" && pending ? <span className="rounded-full bg-gs-amber-soft px-2 py-0.5 text-[11px] font-bold text-gs-amber-ink" data-testid="pending-badge">{pending}</span> : null}
          </button>
        ))}
      </nav>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-surface p-6">
        {/* md-: compact tab strip replaces the sidebar */}
        <div className="mb-4 flex gap-1 overflow-x-auto md:hidden">
          {NAV.map((n) => (
            <button key={n.key} type="button" onClick={() => setPanel(n.key)}
              className={`shrink-0 rounded-lg px-3 py-1.5 text-[12px] font-semibold ${panel === n.key ? "bg-primary text-white" : "bg-white text-gs-ink-2"}`}>{t(`nav.${n.key}`)}</button>
          ))}
        </div>
        {panel === "store" && <StorePanel me={me} onChanged={refreshCounts} />}
        {panel === "documents" && <DocumentsPanel me={me} />}
        {panel === "agents" && <AgentsPanel />}
        {panel === "config" && <ConfigPanel />}
        {panel === "proposals" && <ProposalsPanel me={me} onChanged={refreshCounts} />}
      </main>
    </div>
  );
}

export function KnowledgeShell({ me }: { me: Me }) {
  const { locale } = useLocale();
  return (
    <NextIntlClientProvider locale={locale} messages={locale === "vi" ? vi : en} timeZone="Asia/Ho_Chi_Minh">
      <Inner me={me} />
    </NextIntlClientProvider>
  );
}
