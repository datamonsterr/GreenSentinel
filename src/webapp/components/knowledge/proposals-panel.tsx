"use client";

import React, { useState } from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import { knowledgeApi, parseApiError, type Proposal } from "@/lib/knowledge-client";
import { KB_TYPES, similarityPct, type Me } from "@/lib/knowledge-ui";
import { Card, Chip, Notice, SectionTitle, areaCls, btn, fmtDate, inputCls, useLoad } from "@/components/knowledge/ui";
import type { Tone } from "@/lib/status-tone";

const SOURCES = ["policy_analysis", "help_reply", "closed_case", "monitoring", "manual"] as const;
const REASONS = ["wrong_source", "wrong_motive", "duplicate", "out_of_scope", "other"] as const;
const MAPPING_TONE: Record<string, Tone> = { reuse: "green", extend: "cyan", new: "purple" };
const STATUS_TONE: Record<string, Tone> = { pending: "amber", accepted: "green", edited: "cyan", rejected: "grey" };

function ProposalCard({ p, canDecide, onDone, onError }: { p: Proposal; canDecide: boolean; onDone: (m: string) => void; onError: (m: string) => void }) {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const [mode, setMode] = useState<"edit" | "reject" | null>(null);
  const [json, setJson] = useState(JSON.stringify(p.payload, null, 2));
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const body = (p.payload.body ?? {}) as Record<string, unknown>;
  const formula = String(body.formula ?? body.condition ?? "");

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try { await fn(); onDone(msg); } catch (e) { onError(parseApiError(e).message); } finally { setBusy(false); }
  };
  const saveEdit = () => {
    let payload: Record<string, unknown>;
    try { payload = JSON.parse(json); } catch { onError(t("proposals.badJson")); return; }
    return run(() => knowledgeApi.editProposal(p.id, payload), t("proposals.edited"));
  };

  return (
    <Card className="overflow-hidden" >
      <div className="flex flex-wrap items-center gap-2 border-b border-gs-line px-4 py-2.5" data-testid={`proposal-${p.id}`}>
        <h3 className="text-[13.5px] font-extrabold text-on-surface">{p.title}</h3>
        <Chip tone="purple">{t(`proposals.source.${p.source}`)}</Chip>
        <Chip tone="grey">{t(`types.${p.type}`)}</Chip>
        <Chip tone={MAPPING_TONE[p.mapping]}>{t(`proposals.mapping.${p.mapping}`)}{p.matched_code ? ` · ${p.matched_code}` : ""}</Chip>
        {p.similarity != null && <span className="font-mono text-[11.5px] text-gs-mute-2">{t("proposals.similarity")} {similarityPct(Number(p.similarity))}</span>}
        <span className="ml-auto flex items-center gap-2 text-[11.5px] text-gs-mute"><Chip tone={STATUS_TONE[p.status]}>{t(`proposals.status.${p.status}`)}</Chip>{fmtDate(p.created_at, locale)}</span>
      </div>
      <div className="grid grid-cols-2 divide-x divide-gs-line">
        <div className="space-y-1.5 p-4">
          <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("proposals.sourceCol")}</div>
          <blockquote className="rounded-lg border-l-4 border-primary bg-gs-cyan-soft px-3 py-2 text-[12.5px] text-gs-ink-2">{p.source_excerpt ?? t("proposals.noSource")}</blockquote>
          {p.source_ref && <div className="text-[11.5px] text-gs-mute">{p.source_ref}</div>}
          <div className="text-[11.5px] text-gs-mute">{t("proposals.by")}: {p.created_by ?? "—"}</div>
        </div>
        <div className="space-y-1.5 p-4">
          <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("proposals.proposalCol")}</div>
          <div className="text-[12.5px]"><span className="font-mono font-bold">{String(p.payload.code ?? "—")}</span> · {String(p.payload.name ?? "")}</div>
          {formula && <pre className="overflow-x-auto rounded-lg bg-surface px-3 py-2 font-mono text-[11.5px] text-gs-ink-2">{formula}</pre>}
          {!formula && <pre className="max-h-28 overflow-auto rounded-lg bg-surface px-3 py-2 font-mono text-[11px] text-gs-ink-2">{JSON.stringify(body, null, 1)}</pre>}
          {p.reason_code && <div className="text-[12px] text-gs-mute-2">{t("proposals.rejectedWith")}: {t(`proposals.reason.${p.reason_code}`)}{p.note ? ` — ${p.note}` : ""}</div>}
        </div>
      </div>
      {mode === "edit" && (
        <div className="space-y-2 border-t border-gs-line bg-surface px-4 py-3">
          <div className="text-[12px] text-gs-mute-2">{t("proposals.editHint")}</div>
          <textarea rows={8} className={`${areaCls} font-mono`} aria-label={t("proposals.editHint")} value={json} onChange={(e) => setJson(e.target.value)} />
          <div className="flex gap-2"><button type="button" className={btn.primary} disabled={busy} onClick={saveEdit}>{t("proposals.saveEdit")}</button>
            <button type="button" className={btn.secondary} onClick={() => setMode(null)}>{t("editor.cancel")}</button></div>
        </div>
      )}
      {mode === "reject" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-gs-line bg-surface px-4 py-3">
          <select className={`${inputCls} !w-52`} aria-label={t("proposals.reasonLabel")} value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">{t("proposals.reasonPick")}</option>
            {REASONS.map((r) => <option key={r} value={r}>{t(`proposals.reason.${r}`)}</option>)}
          </select>
          <input className={`${inputCls} !w-72`} aria-label={t("proposals.note")} placeholder={t("proposals.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="button" className={btn.primary} disabled={busy || !reason} onClick={() => run(() => knowledgeApi.rejectProposal(p.id, reason, note), t("proposals.rejected"))}>{t("proposals.confirmReject")}</button>
          <button type="button" className={btn.secondary} onClick={() => setMode(null)}>{t("editor.cancel")}</button>
        </div>
      )}
      {p.status === "pending" && canDecide && !mode && (
        <div className="flex gap-2 border-t border-gs-line px-4 py-3">
          <button type="button" className={btn.primary} disabled={busy} onClick={() => run(() => knowledgeApi.acceptProposal(p.id), t("proposals.accepted"))}>{t("proposals.accept")}</button>
          <button type="button" className={btn.secondary} disabled={busy} onClick={() => setMode("edit")}>{t("proposals.edit")}</button>
          <button type="button" className={btn.secondary} disabled={busy} onClick={() => setMode("reject")}>{t("proposals.reject")}</button>
        </div>
      )}
    </Card>
  );
}

export function ProposalsPanel({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const t = useTranslations("knowledge");
  const [status, setStatus] = useState("pending");
  const [source, setSource] = useState("");
  const [type, setType] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const list = useLoad(() => knowledgeApi.proposals({ status, source, type }), [status, source, type]);
  const canDecide = me.roles.some((r) => ["analyst", "fraud_analyst", "senior_analyst", "admin"].includes(r));

  return (
    <div className="space-y-4">
      <SectionTitle icon="inbox" title={t("proposals.title")} hint={t("proposals.hint")} />
      <div className="flex flex-wrap gap-2">
        <select className={`${inputCls} !w-40`} aria-label={t("proposals.filterStatus")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("proposals.allStatuses")}</option>
          {["pending", "accepted", "edited", "rejected"].map((s) => <option key={s} value={s}>{t(`proposals.status.${s}`)}</option>)}
        </select>
        <select className={`${inputCls} !w-48`} aria-label={t("proposals.filterSource")} value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">{t("proposals.allSources")}</option>
          {SOURCES.map((s) => <option key={s} value={s}>{t(`proposals.source.${s}`)}</option>)}
        </select>
        <select className={`${inputCls} !w-40`} aria-label={t("proposals.filterType")} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">{t("store.all")}</option>
          {KB_TYPES.map((s) => <option key={s} value={s}>{t(`types.${s}`)}</option>)}
        </select>
      </div>
      {(list.error || err) && <Notice kind="error">{list.error ?? err}</Notice>}
      {msg && <Notice kind="ok">{msg}</Notice>}
      <div className="space-y-3" data-testid="proposal-list">
        {(list.data?.items ?? []).map((p) => (
          <ProposalCard key={p.id} p={p} canDecide={canDecide}
            onDone={(m) => { setMsg(m); setErr(null); list.reload(); onChanged(); }} onError={setErr} />
        ))}
        {(list.data?.items ?? []).length === 0 && !list.loading && (
          <Card className="px-6 py-12 text-center text-[13px] text-gs-mute-2" >{t("proposals.empty")}</Card>
        )}
      </div>
    </div>
  );
}
