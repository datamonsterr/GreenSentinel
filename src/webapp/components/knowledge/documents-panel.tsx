"use client";

import React, { useRef, useState } from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import { knowledgeApi, parseApiError } from "@/lib/knowledge-client";
import { similarityPct, type Me } from "@/lib/knowledge-ui";
import { Card, Chip, Field, Notice, SectionTitle, areaCls, btn, fmtDate, inputCls, useLoad } from "@/components/knowledge/ui";
import type { Tone } from "@/lib/status-tone";

const INDEX_TONE: Record<string, Tone> = { not_indexed: "amber", indexed: "green", embeddings_not_configured: "grey" };
const ANALYSIS_TONE: Record<string, Tone> = { pending: "grey", running: "amber", done: "green", failed: "red" };
const TEXT_TYPES = /\.(txt|md|csv|json)$/i;
const EMPTY = { name: "", code: "", effective_from: "", effective_to: "", region: "", service: "", contract_type: "", text: "" };

export function DocumentsPanel({ me }: { me: Me }) {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const docs = useLoad(() => knowledgeApi.documents(), []);
  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState<{ name: string; type: string; size: number } | null>(null);
  const [error, setError] = useState<{ message: string; fields?: string[] } | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [simQuery, setSimQuery] = useState("");
  const [sim, setSim] = useState<Awaited<ReturnType<typeof knowledgeApi.similar>>["items"] | null>(null);
  const [b64, setB64] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });
  const canUpload = me.roles.some((r) => ["analyst", "fraud_analyst", "senior_analyst", "admin"].includes(r));

  const pick = async (f: File | undefined) => {
    if (!f) return;
    setFile({ name: f.name, type: f.type, size: f.size }); setB64(null);
    if (TEXT_TYPES.test(f.name) || f.type.startsWith("text/")) {
      const text = await f.text();
      setForm((cur) => ({ ...cur, text, name: cur.name || f.name.replace(/\.[^.]+$/, "") }));
    } else {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = ""; bytes.forEach((b) => { bin += String.fromCharCode(b); });
      setB64(btoa(bin));
      setForm((cur) => ({ ...cur, name: cur.name || f.name.replace(/\.[^.]+$/, "") }));
    }
  };

  const missing = [!form.name.trim() && "name", !form.code.trim() && "code", !form.text.trim() && !file && "file_or_text"].filter(Boolean) as string[];

  const submit = async () => {
    setBusy(true); setError(null); setOkMsg(null);
    try {
      await knowledgeApi.createDocument({
        ...form, effective_from: form.effective_from || null, effective_to: form.effective_to || null,
        filename: file?.name ?? null, content_type: file?.type ?? "text/plain", size_bytes: file?.size ?? form.text.length,
        content_base64: b64,
      });
      setForm(EMPTY); setB64(null); setFile(null); if (fileRef.current) fileRef.current.value = "";
      setOkMsg(t("docs.uploaded")); docs.reload();
    } catch (e) { setError({ message: parseApiError(e).message }); } finally { setBusy(false); }
  };

  const analyze = async (id: string) => {
    setAnalyzing(id); setError(null); setOkMsg(null);
    try { await knowledgeApi.analyzeDocument(id); } catch (e) { setError({ message: parseApiError(e).message }); }
    finally { setAnalyzing(null); docs.reload(); }
  };

  const findSimilar = async () => {
    try { setSim((await knowledgeApi.similar(simQuery)).items); } catch (e) { setError({ message: parseApiError(e).message }); }
  };

  return (
    <div className="space-y-4">
      <SectionTitle icon="description" title={t("docs.title")} hint={t("docs.hint")} />
      <div className="grid grid-cols-[minmax(0,420px)_1fr] gap-4">
        <Card className="space-y-3 p-4">
          <h3 className="text-[13px] font-extrabold text-on-surface">{t("docs.upload")}</h3>
          {error && <Notice kind="error">{error.message}</Notice>}
          {okMsg && <Notice kind="ok">{okMsg}</Notice>}
          <div className="grid grid-cols-2 gap-3">
            <Field label={`${t("docs.name")} *`}><input className={inputCls} aria-label={t("docs.name")} value={form.name} onChange={set("name")} /></Field>
            <Field label={`${t("docs.code")} *`}><input className={`${inputCls} font-mono`} aria-label={t("docs.code")} value={form.code} onChange={set("code")} /></Field>
            <Field label={t("docs.from")}><input type="date" className={inputCls} aria-label={t("docs.from")} value={form.effective_from} onChange={set("effective_from")} /></Field>
            <Field label={t("docs.to")}><input type="date" className={inputCls} aria-label={t("docs.to")} value={form.effective_to} onChange={set("effective_to")} /></Field>
            <Field label={t("docs.region")}><input className={inputCls} aria-label={t("docs.region")} value={form.region} onChange={set("region")} /></Field>
            <Field label={t("docs.service")}><input className={inputCls} aria-label={t("docs.service")} value={form.service} onChange={set("service")} /></Field>
            <div className="col-span-2"><Field label={t("docs.contract")}><input className={inputCls} aria-label={t("docs.contract")} value={form.contract_type} onChange={set("contract_type")} /></Field></div>
          </div>
          <Field label={t("docs.file")} hint={t("docs.fileHint")}>
            <input ref={fileRef} type="file" accept=".txt,.md,.csv,.json,.docx,.pdf,.xlsx" aria-label={t("docs.file")}
              className="block w-full text-[12px] text-gs-mute-2 file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-gs-line-2 file:bg-white file:px-3 file:py-1.5 file:text-[12px] file:font-semibold"
              onChange={(e) => pick(e.target.files?.[0])} />
          </Field>
          <Field label={t("docs.paste")}><textarea rows={4} className={areaCls} aria-label={t("docs.paste")} value={form.text} onChange={set("text")} /></Field>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11.5px] text-gs-mute">{missing.length > 0 ? `${t("docs.missing")}: ${missing.map((m) => t(`docs.field.${m}`)).join(", ")}` : ""}</span>
            <button type="button" className={btn.primary} disabled={busy || !canUpload || missing.length > 0} onClick={submit}>{t("docs.submit")}</button>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="overflow-x-auto">
            <table className="w-full text-left text-[13px]" data-testid="docs-table">
              <thead className="bg-surface text-[11px] uppercase tracking-wider text-gs-mute"><tr>
                {["code", "name", "scope", "indexing", "analysis", "usedBy", "uploaded"].map((c) => <th key={c} className="px-3 py-2 font-semibold">{t(`docs.col.${c}`)}</th>)}</tr></thead>
              <tbody>
                {(docs.data?.items ?? []).map((d) => (
                  <tr key={d.id} className="border-t border-gs-line align-top">
                    <td className="px-3 py-2 font-mono text-[12px] font-bold">{d.code}</td>
                    <td className="px-3 py-2"><div className="font-semibold text-on-surface">{d.name}</div>
                      <div className="text-[11px] text-gs-mute">{d.filename ?? "—"}</div></td>
                    <td className="px-3 py-2 text-[12px] text-gs-mute-2">{[d.region, d.service, d.contract_type].filter(Boolean).join(" · ") || "—"}
                      <div className="text-gs-mute">{d.effective_from ?? "—"} → {d.effective_to ?? "—"}</div></td>
                    <td className="px-3 py-2"><Chip tone={INDEX_TONE[d.indexing_status]} title={t(`docs.indexingHint.${d.indexing_status}`)}>{t(`docs.indexing.${d.indexing_status}`)}</Chip></td>
                    <td className="px-3 py-2">
                      {(() => {
                        const st = analyzing === d.id ? "running" : (d.analysis_status ?? "pending");
                        const c = d.analysis_counts ?? {};
                        return (
                          <div className="space-y-1.5" data-testid={`analysis-${d.id}`}>
                            <Chip tone={ANALYSIS_TONE[st]}>{t(`docs.analysis.status.${st}`)}</Chip>
                            {st === "done" && (
                              <div className="text-[11.5px] text-gs-mute-2" data-testid={`analysis-counts-${d.id}`}>
                                {t("docs.analysis.proposals")}: <b>{c.proposals ?? 0}</b> · {t("docs.analysis.reuse")} {c.reuse ?? 0} · {t("docs.analysis.extend")} {c.extend ?? 0} · {t("docs.analysis.new")} {c.new ?? 0}
                                {(c.rejected_citation ?? 0) > 0 && <div className="text-gs-mute">{t("docs.analysis.rejected")}: {c.rejected_citation}</div>}
                              </div>
                            )}
                            {st === "failed" && d.analysis_error && <div className="max-w-[220px] text-[11.5px] text-red-700">{d.analysis_error}</div>}
                            {canUpload && (
                              <button type="button" className={btn.secondary} disabled={analyzing !== null || !d.has_text} title={d.has_text ? undefined : t("docs.analysis.noText")} onClick={() => analyze(d.id)}>
                                {analyzing === d.id ? t("docs.analysis.running") : t(d.analysis_status && d.analysis_status !== "pending" ? "docs.analysis.rerun" : "docs.analysis.run")}
                              </button>
                            )}
                          </div>
                        );
                      })()}
                    </td>
                    <td className="px-3 py-2 text-[12px] text-gs-mute-2">{d.used_by.map((a) => (locale === "vi" ? a.vi : a.en)).join(", ") || "—"}</td>
                    <td className="px-3 py-2 text-[12px] text-gs-mute">{d.uploaded_by_name ?? "—"}<div>{fmtDate(d.created_at, locale)}</div></td>
                  </tr>
                ))}
                {(docs.data?.items ?? []).length === 0 && !docs.loading && (
                  <tr><td colSpan={7} className="px-3 py-10 text-center text-[13px] text-gs-mute-2">{t("docs.empty")}</td></tr>
                )}
              </tbody>
            </table>
          </Card>

          <Card className="space-y-3 p-4">
            <SectionTitle icon="compare_arrows" title={t("docs.similarTitle")} hint={t("docs.similarHint")} />
            <div className="flex gap-2">
              <input className={inputCls} aria-label={t("docs.similarTitle")} placeholder={t("docs.similarPlaceholder")} value={simQuery} onChange={(e) => setSimQuery(e.target.value)} />
              <button type="button" className={btn.secondary} disabled={!simQuery.trim()} onClick={findSimilar}>{t("docs.similarRun")}</button>
            </div>
            {sim && (
              <ul className="divide-y divide-gs-line rounded-lg border border-gs-line text-[12.5px]" data-testid="similar-list">
                {sim.length === 0 && <li className="px-3 py-3 text-gs-mute-2">{t("docs.similarNone")}</li>}
                {sim.map((s) => (
                  <li key={`${s.type}-${s.code}`} className="flex items-center gap-2 px-3 py-2">
                    <span className="font-mono font-bold">{s.code}</span><Chip tone="purple">{t(`types.${s.type}`)}</Chip>
                    <span className="min-w-0 flex-1 truncate text-gs-mute-2">{s.name}</span>
                    <span className="font-mono font-bold text-primary">{similarityPct(s.similarity)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
