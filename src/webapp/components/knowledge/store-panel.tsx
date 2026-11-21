"use client";

import React, { useMemo, useState } from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import { knowledgeApi, parseApiError, type KbObject, type KbStatus, type KbType } from "@/lib/knowledge-client";
import { KB_STATUSES, KB_TYPES, STATUS_TONE, canAuthor, type Me } from "@/lib/knowledge-ui";
import { ObjectEditor } from "@/components/knowledge/object-editor";
import { Card, Chip, Notice, SectionTitle, btn, fmtDate, inputCls, useLoad } from "@/components/knowledge/ui";

export function StorePanel({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const [type, setType] = useState<KbType | "">("");
  const [status, setStatus] = useState<KbStatus | "">("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<KbObject | null>(null);
  const [creating, setCreating] = useState<KbType | null>(null);
  const [seedMsg, setSeedMsg] = useState<string | null>(null);
  const [seedErr, setSeedErr] = useState<string | null>(null);

  const list = useLoad(() => knowledgeApi.listObjects({ type, status, q }), [type, status, q]);
  const catalogue = useLoad(() => knowledgeApi.parameters(), []);
  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const isAdmin = me.roles.includes("admin");
  const author = canAuthor(me.roles);
  const panelOpen = !!(selected || creating);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    items.forEach((o) => { c[o.status] = (c[o.status] ?? 0) + 1; });
    return c;
  }, [items]);

  const changed = (o: KbObject) => {
    setCreating(null);
    setSelected(o);
    list.reload();
    onChanged();
  };

  const seed = async () => {
    setSeedErr(null);
    try { const r = await knowledgeApi.seed(); setSeedMsg(t("store.seeded", { n: r.created })); list.reload(); onChanged(); }
    catch (e) { setSeedErr(parseApiError(e).message); }
  };

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <SectionTitle icon="menu_book" title={t("store.title")} hint={t("store.hint")}
          right={author ? <button type="button" className={btn.primary} onClick={() => { setSelected(null); setCreating(type || "motive"); }}>
            <span className="material-symbols-outlined text-[16px]">add</span>{t("store.new")}</button> : undefined} />

        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t("store.filterType")} className="flex flex-wrap gap-1 rounded-lg border border-gs-line-2 bg-white p-0.5">
            {(["", ...KB_TYPES] as const).map((tp) => (
              <button key={tp || "all"} type="button" aria-pressed={type === tp} onClick={() => setType(tp)}
                className={`cursor-pointer rounded-md px-2.5 py-1 text-[12px] font-semibold transition-colors ${type === tp ? "bg-primary text-white" : "text-gs-mute-2 hover:bg-surface"}`}>
                {tp ? t(`types.${tp}`) : t("store.all")}
              </button>
            ))}
          </div>
          <select aria-label={t("store.filterStatus")} className={`${inputCls} !w-44`} value={status} onChange={(e) => setStatus(e.target.value as KbStatus | "")}>
            <option value="">{t("store.allStatuses")}</option>
            {KB_STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}{counts[s] && !status ? ` (${counts[s]})` : ""}</option>)}
          </select>
          <input aria-label={t("store.search")} placeholder={t("store.search")} className={`${inputCls} !w-56`} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>

        {list.error && <Notice kind="error">{list.error}</Notice>}
        {seedErr && <Notice kind="error">{seedErr}</Notice>}
        {seedMsg && <Notice kind="ok">{seedMsg}</Notice>}

        <Card className="min-h-0 flex-1 overflow-auto">
          {items.length === 0 && !list.loading ? (
            <div className="flex flex-col items-center gap-3 px-6 py-14 text-center" data-testid="store-empty">
              <span className="material-symbols-outlined text-[36px] text-gs-mute">menu_book</span>
              <p className="text-[13px] text-gs-mute-2">{t("store.empty")}</p>
              {isAdmin && <button type="button" className={btn.secondary} onClick={seed}>{t("store.seed")}</button>}
            </div>
          ) : (
            <table className="w-full text-left text-[13px]" data-testid="store-table">
              <thead className="sticky top-0 bg-surface text-[11px] uppercase tracking-wider text-gs-mute">
                <tr>
                  {["code", "name", "type", "version", "status", "author", "updated"].filter((c) => !panelOpen || !["author", "updated", "version"].includes(c)).map((c) => <th key={c} className="px-3 py-2 font-semibold">{t(`store.col.${c}`)}</th>)}
                </tr>
              </thead>
              <tbody>
                {items.map((o) => (
                  <tr key={o.id} data-testid={`row-${o.code}-v${o.version}`} onClick={() => { setCreating(null); setSelected(o); }}
                    className={`cursor-pointer border-t border-gs-line hover:bg-surface ${o.id === selected?.id ? "bg-surface" : ""}`}>
                    <td className="px-3 py-2 font-mono text-[12px] font-bold text-on-surface">{o.code}{panelOpen && <span className="ml-1 font-normal text-gs-mute">v{o.version}</span>}</td>
                    <td className="px-3 py-2 text-gs-ink-2">{o.name}</td>
                    <td className="px-3 py-2"><Chip tone="purple">{t(`types.${o.type}`)}</Chip></td>
                    {!panelOpen && <td className="px-3 py-2 font-mono">v{o.version}</td>}
                    <td className="px-3 py-2"><Chip tone={STATUS_TONE[o.status]}>{t(`status.${o.status}`)}</Chip></td>
                    {!panelOpen && <td className="px-3 py-2 text-gs-mute-2">{o.author_name ?? "—"}</td>}
                    {!panelOpen && <td className="px-3 py-2 text-gs-mute">{fmtDate(o.updated_at, locale)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {panelOpen && (
        <div className="w-[540px] shrink-0">
          <ObjectEditor key={selected?.id ?? `new-${creating}`} obj={selected} createType={creating ?? "motive"} me={me}
            catalogue={catalogue.data?.items ?? []} onChanged={changed}
            onSelectVersion={(v) => setSelected(v)} onClose={() => { setSelected(null); setCreating(null); }} />
        </div>
      )}
    </div>
  );
}
