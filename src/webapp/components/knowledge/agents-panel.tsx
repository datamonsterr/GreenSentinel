"use client";

import React from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import { knowledgeApi } from "@/lib/knowledge-client";
import { Card, Chip, Notice, SectionTitle, useLoad } from "@/components/knowledge/ui";

export function AgentsPanel() {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const reg = useLoad(() => knowledgeApi.registry(), []);
  return (
    <div className="space-y-4">
      <SectionTitle icon="smart_toy" title={t("agents.title")} hint={t("agents.hint")} />
      {reg.error && <Notice kind="error">{reg.error}</Notice>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2" data-testid="agents-grid">
        {(reg.data?.agents ?? []).map((a) => (
          <Card key={a.id} className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-[14px] font-extrabold text-on-surface" data-testid={`agent-${a.id}`}>{locale === "vi" ? a.name.vi : a.name.en}</h3>
                <div className="font-mono text-[11px] text-gs-mute">{a.id}</div>
              </div>
              {a.status === "planned" ? <Chip tone="grey">{t("agents.planned")}</Chip>
                : a.enabled === null ? <Chip tone="green">{t("agents.active")}</Chip>
                  : <Chip tone={a.enabled ? "green" : "amber"}>{t(a.enabled ? "agents.enabled" : "agents.disabled")}</Chip>}
            </div>
            <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-[12.5px]">
              <dt className="text-gs-mute">{t("agents.instruction")}</dt><dd className="font-mono font-semibold text-gs-ink-2">{a.instruction_version}</dd>
              <dt className="text-gs-mute">{t("agents.model")}</dt><dd className="font-mono text-gs-ink-2">{a.model}</dd>
              <dt className="text-gs-mute">{t("agents.reads")}</dt><dd className="text-gs-ink-2">{t(`agents.readsValue.${a.reads}`)}</dd>
              <dt className="text-gs-mute">{t("agents.knowledge")}</dt>
              <dd className="flex flex-wrap gap-1.5">
                {a.knowledge_types.map((k) => <Chip key={k} tone="purple">{t(`types.${k}`)}: {a.knowledge_published[k] ?? 0}</Chip>)}
                {a.uses_policy_documents && <Chip tone="cyan">{t("agents.policyDocs")}</Chip>}
              </dd>
              <dt className="text-gs-mute">{t("agents.tools")}</dt>
              <dd className="flex flex-wrap gap-1">{a.tools.map((x) => <span key={x} className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11px] text-gs-ink-2">{x}</span>)}</dd>
              <dt className="text-gs-mute">{t("agents.memory")}</dt>
              <dd className="flex flex-wrap gap-1">{a.memory_layers.map((x) => <Chip key={x} tone="grey">{t(`agents.layer.${x}`)}</Chip>)}</dd>
            </dl>
          </Card>
        ))}
      </div>
    </div>
  );
}
