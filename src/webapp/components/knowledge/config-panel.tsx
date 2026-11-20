"use client";

import React, { useState } from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import { knowledgeApi, parseApiError, type ConfigItem } from "@/lib/knowledge-client";
import { Card, Chip, Notice, SectionTitle, btn, fmtDate, inputCls, useLoad } from "@/components/knowledge/ui";

const GROUPS = ["limits", "help", "thresholds"] as const;

function ConfigRow({ item, locale, onSaved, onError }: { item: ConfigItem; locale: string; onSaved: (msg: string) => void; onError: (m: string) => void }) {
  const t = useTranslations("knowledge");
  const [draft, setDraft] = useState<string>(String(item.value));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const isBool = item.type === "bool";
  const parsed = isBool ? draft === "true" : Number(draft);
  const changed = draft !== String(item.value);
  const outOfBounds = !isBool && (draft.trim() === "" || Number.isNaN(parsed as number) || (item.min !== null && (parsed as number) < item.min) || (item.max !== null && (parsed as number) > item.max)
    || (item.type === "int" && !Number.isInteger(parsed as number)));
  const save = async () => {
    setBusy(true);
    try { await knowledgeApi.setConfig(item.key, parsed, reason); setReason(""); onSaved(t("config.saved", { key: item.key })); }
    catch (e) { onError(parseApiError(e).message); } finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-3 border-t border-gs-line px-4 py-3 first:border-t-0" data-testid={`cfg-${item.key}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-bold text-on-surface">{locale === "vi" ? item.label.vi : item.label.en}</span>
          <Chip tone={item.owner === "VH" ? "orange" : "purple"} title={t("config.ownerHint")}>{t(`config.owner.${item.owner === "LEAD" ? "KSGL" : item.owner}`)}</Chip>
          {item.is_default && <Chip tone="grey">{t("config.default")}</Chip>}
        </div>
        <div className="mt-0.5 font-mono text-[11px] text-gs-mute">
          {item.key}{item.min !== null && ` · ${t("config.bounds", { min: item.min, max: item.max ?? "" })}`}
          {item.updated_at && ` · ${fmtDate(item.updated_at, locale)}`}
        </div>
        {changed && item.can_edit && (
          <div className="mt-2 flex items-center gap-2">
            <input className={`${inputCls} max-w-xs`} aria-label={t("config.reason")} placeholder={t("config.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button type="button" className={btn.primary} disabled={busy || outOfBounds || reason.trim().length < 3} onClick={save}>{t("config.save")}</button>
            <button type="button" className={btn.secondary} onClick={() => { setDraft(String(item.value)); setReason(""); }}>{t("editor.cancel")}</button>
          </div>
        )}
        {changed && outOfBounds && <div className="mt-1 text-[12px] text-gs-red">{t("config.outOfBounds", { min: item.min ?? "", max: item.max ?? "" })}</div>}
      </div>
      {isBool ? (
        <button type="button" role="switch" aria-checked={draft === "true"} aria-label={locale === "vi" ? item.label.vi : item.label.en} disabled={!item.can_edit}
          onClick={() => setDraft(draft === "true" ? "false" : "true")}
          className={`relative h-6 w-11 cursor-pointer rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${draft === "true" ? "bg-primary" : "bg-gs-line-2"}`}>
          <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${draft === "true" ? "left-[22px]" : "left-0.5"}`} />
        </button>
      ) : (
        <input type="number" step={item.type === "float" ? "0.01" : "1"} disabled={!item.can_edit} aria-label={locale === "vi" ? item.label.vi : item.label.en}
          className={`${inputCls} !w-28 text-right font-mono`} value={draft} onChange={(e) => setDraft(e.target.value)} />
      )}
    </div>
  );
}

export function ConfigPanel() {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const cfg = useLoad(() => knowledgeApi.config(), []);
  const hist = useLoad(() => knowledgeApi.configHistory(), []);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ksReason, setKsReason] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = (m: string) => { setErr(null); setMsg(m); cfg.reload(); hist.reload(); };
  const kill = cfg.data?.items.find((i) => i.key === "explain_agent_enabled");
  const enabled = kill?.value === true;

  const toggleKill = async () => {
    setBusy(true); setErr(null);
    try { await knowledgeApi.killSwitch(!enabled, ksReason); setKsReason(""); refresh(t(enabled ? "config.killOffDone" : "config.killOnDone")); }
    catch (e) { setErr(parseApiError(e).message); } finally { setBusy(false); }
  };
  const [revertId, setRevertId] = useState<string | null>(null);
  const [revertReason, setRevertReason] = useState("");
  const revert = async () => {
    if (!revertId) return;
    try { await knowledgeApi.revert(revertId, revertReason); setRevertId(null); setRevertReason(""); refresh(t("config.reverted")); }
    catch (e) { setErr(parseApiError(e).message); }
  };
  const m = cfg.data?.metrics;
  const tiles = [["avg_turns", m?.avg_turns], ["pct_exhausted", m?.pct_exhausted], ["pct_help", m?.pct_help]] as const;

  return (
    <div className="space-y-4">
      <SectionTitle icon="tune" title={t("config.title")} hint={t("config.hint")} />
      {(cfg.error || err) && <Notice kind="error">{cfg.error ?? err}</Notice>}
      {msg && <Notice kind="ok">{msg}</Notice>}

      <Card className="space-y-3 p-4" >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[14px] font-extrabold text-on-surface">{t("config.killTitle")}</h3>
              <Chip tone={enabled ? "green" : "amber"}>{t(enabled ? "config.killOn" : "config.killOff")}</Chip>
            </div>
            <p className="mt-1 max-w-2xl text-[12.5px] text-gs-mute-2">{t("config.killHint")}</p>
          </div>
          <div className="flex items-center gap-2">
            <input className={`${inputCls} !w-64`} aria-label={t("config.reason")} placeholder={t("config.reason")} value={ksReason} onChange={(e) => setKsReason(e.target.value)} disabled={!kill?.can_edit} />
            <button type="button" className={enabled ? btn.danger : btn.primary} disabled={busy || !kill?.can_edit || ksReason.trim().length < 3} onClick={toggleKill}>
              {t(enabled ? "config.turnOff" : "config.turnOn")}
            </button>
          </div>
        </div>
        {kill && !kill.can_edit && <div className="text-[12px] text-gs-mute">{t("config.killNoRight")}</div>}
      </Card>

      <div className="grid grid-cols-3 gap-3" data-testid="config-metrics">
        {tiles.map(([k, v]) => (
          <Card key={k} className="px-4 py-3">
            <div className="text-[20px] font-extrabold text-on-surface">{v == null ? "—" : v}</div>
            <div className="text-[12px] text-gs-mute-2">{t(`config.metric.${k}`)}</div>
            <div className="text-[11px] text-gs-mute">{t("config.metricWindow", { days: m?.window_days ?? 30 })}{m && !m.available ? ` · ${t("config.metricPending")}` : ""}</div>
          </Card>
        ))}
      </div>

      {GROUPS.map((g) => (
        <Card key={g}>
          <div className="border-b border-gs-line px-4 py-2.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t(`config.group.${g}`)}</div>
          {(cfg.data?.items ?? []).filter((i) => i.group === g).map((i) => (
            <ConfigRow key={`${i.key}-${String(i.value)}`} item={i} locale={locale} onSaved={refresh} onError={setErr} />
          ))}
        </Card>
      ))}

      <Card>
        <div className="border-b border-gs-line px-4 py-2.5"><SectionTitle icon="history" title={t("config.historyTitle")} /></div>
        {revertId && (
          <div className="flex items-center gap-2 border-b border-gs-line bg-gs-cyan-soft px-4 py-2" data-testid="revert-form">
            <input autoFocus className={`${inputCls} max-w-sm`} aria-label={t("config.reason")} placeholder={t("config.revertPrompt")} value={revertReason} onChange={(e) => setRevertReason(e.target.value)} />
            <button type="button" className={btn.primary} disabled={revertReason.trim().length < 3} onClick={revert}>{t("config.revert")}</button>
            <button type="button" className={btn.secondary} onClick={() => setRevertId(null)}>{t("editor.cancel")}</button>
          </div>
        )}
        <table className="w-full text-left text-[12.5px]" data-testid="config-history">
          <thead className="bg-surface text-[11px] uppercase tracking-wider text-gs-mute"><tr>
            {["when", "key", "change", "kind", "who", "reason", ""].map((c) => <th key={c || "x"} className="px-3 py-2 font-semibold">{c ? t(`config.col.${c}`) : ""}</th>)}</tr></thead>
          <tbody>
            {(hist.data?.items ?? []).map((h) => (
              <tr key={h.id} className="border-t border-gs-line">
                <td className="px-3 py-2 text-gs-mute">{fmtDate(h.created_at, locale)}</td>
                <td className="px-3 py-2 font-mono text-[11.5px]">{h.key}</td>
                <td className="px-3 py-2 font-mono">{String(h.old_value)} → <b>{String(h.new_value)}</b></td>
                <td className="px-3 py-2"><Chip tone={h.kind === "kill_switch" ? "orange" : h.kind === "revert" ? "purple" : "cyan"}>{t(`config.kind.${h.kind}`)}</Chip></td>
                <td className="px-3 py-2 text-gs-ink-2">{h.changed_by_name ?? "—"}</td>
                <td className="px-3 py-2 text-gs-mute-2">{h.reason}</td>
                <td className="px-3 py-2 text-right">
                  {h.old_value !== null && h.kind !== "revert" && (cfg.data?.items.find((i) => i.key === h.key)?.can_edit ?? false) && (
                    <button type="button" className={btn.ghost} onClick={() => setRevertId(h.id)}>{t("config.revert")}</button>)}
                </td>
              </tr>
            ))}
            {(hist.data?.items ?? []).length === 0 && !hist.loading && <tr><td colSpan={7} className="px-3 py-8 text-center text-gs-mute-2">{t("config.noHistory")}</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
