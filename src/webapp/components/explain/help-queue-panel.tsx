"use client";

import React, { useCallback, useEffect, useState } from "react";
import { parseApiError } from "@/lib/knowledge-client";
import type { Locale } from "@/lib/locale";
import { explainApi, type HelpCounts, type HelpRequest, type HelpRequestDetail } from "@/lib/explain-client";

const MSG = {
  vi: {
    title: "Hàng chờ trợ giúp AI", close: "Đóng", empty: "Không có yêu cầu trợ giúp nào đang chờ.", loading: "Đang tải…",
    open: "Đang chờ", claimed: "Đã nhận", claim: "Nhận xử lý", reply: "Phản hồi thay VH", text: "Nội dung phản hồi cho tài xế",
    facts: "Dữ kiện (mỗi dòng một dữ kiện, dùng để đề xuất tri thức)", send: "Gửi phản hồi", stuck: "Điểm đang vướng", driverSays: "Tài xế khai",
    openCase: "Mở hồ sơ", claimedBy: "Người nhận", transcript: "Hội thoại", sent: "Đã gửi phản hồi.", refresh: "Làm mới",
  },
  en: {
    title: "AI help queue", close: "Close", empty: "No pending help requests.", loading: "Loading…",
    open: "Open", claimed: "Claimed", claim: "Claim", reply: "Reply as VH", text: "Reply to the driver",
    facts: "Facts (one per line, used to propose knowledge)", send: "Send reply", stuck: "Stuck point", driverSays: "Driver statement",
    openCase: "Open case", claimedBy: "Claimed by", transcript: "Transcript", sent: "Reply sent.", refresh: "Refresh",
  },
} as const;

/** Poll the open+claimed badge count. Pass enabled=false for roles without queue access. */
export function useHelpCount(enabled: boolean, intervalMs = 30_000): { counts: HelpCounts | null; refresh: () => void } {
  const [counts, setCounts] = useState<HelpCounts | null>(null);
  const refresh = useCallback(() => { explainApi.helpCount().then(setCounts).catch(() => undefined); }, []);
  useEffect(() => {
    if (!enabled) return;
    refresh();
    const t = setInterval(refresh, intervalMs);
    return () => clearInterval(t);
  }, [enabled, intervalMs, refresh]);
  return { counts, refresh };
}

const chip = (tone: string) => `gs-tone ${tone} inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold`;

function Item({ item, locale, onChanged, onOpenCase }: { item: HelpRequest; locale: Locale; onChanged: () => void; onOpenCase?: (caseId: string) => void }) {
  const m = MSG[locale];
  const [detail, setDetail] = useState<HelpRequestDetail | null>(null);
  const [status, setStatus] = useState(item.status);
  const [text, setText] = useState("");
  const [facts, setFacts] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const claimed = status === "claimed";

  useEffect(() => {
    if (!claimed) return;
    explainApi.helpDetail(item.id).then(setDetail).catch(() => undefined);
  }, [claimed, item.id]);

  const run = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setMsg(null);
    try { await fn(); after?.(); onChanged(); } catch (e) { setMsg({ ok: false, text: parseApiError(e).message }); } finally { setBusy(false); }
  };

  return (
    <li data-testid={`help-item-${item.id}`} className="space-y-2 rounded-lg border border-gs-line bg-white p-3 text-xs text-gs-ink-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className={chip(claimed ? "t-cyan" : "t-amber")}>{claimed ? m.claimed : m.open}</span>
        <span className="font-mono text-gs-mute">{item.case_id.slice(0, 8)}</span>
        {claimed && item.claimed_by_name && <span className="text-gs-mute">{m.claimedBy}: {item.claimed_by_name}</span>}
        {onOpenCase && <button type="button" onClick={() => onOpenCase(item.case_id)} className="ml-auto rounded border border-gs-line-2 bg-white px-2 py-0.5 text-[11px] hover:bg-background">{m.openCase}</button>}
      </div>
      {item.summary && <p className="text-gs-ink">{item.summary}</p>}
      {item.stuck_point && <p><span className="font-semibold">{m.stuck}:</span> {item.stuck_point}</p>}
      {!claimed && (
        <button type="button" data-testid={`help-claim-${item.id}`} disabled={busy}
          onClick={() => void run(() => explainApi.claim(item.id), () => setStatus("claimed"))}
          className="rounded-lg bg-primary px-3 py-1.5 font-semibold text-white hover:bg-primary-container disabled:opacity-50">{m.claim}</button>
      )}
      {claimed && (
        <div className="space-y-2">
          {detail?.statement_text && <p className="rounded bg-background p-2"><span className="font-semibold">{m.driverSays}:</span> {detail.statement_text}</p>}
          {detail && detail.transcript.length > 0 && (
            <details><summary className="cursor-pointer text-gs-mute">{m.transcript}</summary>
              <ul className="mt-1 space-y-1">{detail.transcript.map((t) => (
                <li key={t.seq} className={t.kind === "driver_answer" ? "text-gs-ink" : "text-gs-mute"}>{t.kind === "driver_answer" ? "TX" : "AI"}: {t.text}</li>
              ))}</ul></details>
          )}
          <label className="block"><span className="font-semibold">{m.text}</span>
            <textarea data-testid="help-reply-text" value={text} onChange={(e) => setText(e.target.value)} rows={3}
              className="mt-1 w-full rounded-lg border border-gs-line-2 bg-white p-2 focus:border-primary focus:outline-none" /></label>
          <label className="block"><span className="font-semibold">{m.facts}</span>
            <textarea data-testid="help-reply-facts" value={facts} onChange={(e) => setFacts(e.target.value)} rows={2}
              className="mt-1 w-full rounded-lg border border-gs-line-2 bg-white p-2 focus:border-primary focus:outline-none" /></label>
          <button type="button" data-testid="help-reply-send" disabled={busy || !text.trim()}
            onClick={() => void run(() => explainApi.reply(item.id, text.trim(), facts.split("\n").map((f) => f.trim()).filter(Boolean)), () => setMsg({ ok: true, text: m.sent }))}
            className="rounded-lg bg-primary px-3 py-1.5 font-semibold text-white hover:bg-primary-container disabled:opacity-50">{m.send}</button>
        </div>
      )}
      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-gs-green-ink" : "text-gs-red"}>{msg.text}</p>}
    </li>
  );
}

export function HelpQueuePanel({ locale, open, onClose, onChanged, onOpenCase }: {
  locale: Locale; open: boolean; onClose: () => void; onChanged?: () => void; onOpenCase?: (caseId: string) => void;
}) {
  const m = MSG[locale];
  const [items, setItems] = useState<HelpRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rev, setRev] = useState(0);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    explainApi.helpList("open,claimed")
      .then((r) => { if (alive) { setItems(r.items); setError(null); } })
      .catch((e) => { if (alive) setError(parseApiError(e).message); });
    return () => { alive = false; };
  }, [open, rev]);

  if (!open) return null;
  const changed = () => { onChanged?.(); };
  return (
    <aside role="dialog" aria-label={m.title} data-testid="help-queue-panel"
      className="fixed right-0 top-16 z-40 flex h-[calc(100vh-4rem)] w-full max-w-md flex-col border-l border-gs-line-2 bg-background shadow-lg">
      <header className="flex items-center gap-2 border-b border-gs-line bg-white px-4 py-3">
        <span className="material-symbols-outlined text-[20px] text-primary">support_agent</span>
        <h2 className="flex-1 text-sm font-bold text-gs-ink">{m.title}</h2>
        <button type="button" onClick={() => setRev((r) => r + 1)} className="rounded border border-gs-line-2 bg-white px-2 py-1 text-[11px] hover:bg-background">{m.refresh}</button>
        <button type="button" onClick={onClose} aria-label={m.close} className="rounded p-1 text-gs-mute hover:bg-gs-cyan-soft">
          <span className="material-symbols-outlined text-[18px]">close</span>
        </button>
      </header>
      <div className="flex-1 overflow-y-auto p-3">
        {error && <p role="alert" className="text-xs text-gs-red">{error}</p>}
        {!error && items === null && <p className="text-xs text-gs-mute">{m.loading}</p>}
        {items && items.length === 0 && <p className="text-xs text-gs-mute">{m.empty}</p>}
        {items && items.length > 0 && (
          <ul className="space-y-2">
            {items.map((it) => <Item key={it.id} item={it} locale={locale} onOpenCase={onOpenCase}
              onChanged={() => { changed(); setRev((r) => r + 1); }} />)}
          </ul>
        )}
      </div>
    </aside>
  );
}
