"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import type { Locale } from "@/lib/locale";
import {
  FEEDBACK_ERROR_TYPES, FLAG_KEYS, canGiveFeedback, diffStatements, explainApi, flagTone, isNoSession, latestFeedbackPerAuthor, roundStateTone,
  type ExplainView,
} from "@/lib/explain-client";
import { SectionCard } from "@/components/cockpit/section-card";

const MSG = {
  vi: {
    title: "Giải trình AI", subtitle: "Phiên hỏi đáp tự động với tài xế", loading: "Đang tải giải trình AI…", error: "Không tải được giải trình AI.",
    statements: "Bản giải trình", version: "Phiên bản", source: "Nguồn", diff: "So với bản trước", noDiff: "Không có thay đổi.", show: "Xem", hide: "Ẩn",
    rounds: "Vòng đánh giá", round: "Vòng", confidence: "Độ tin cậy", turns: "Lượt hỏi", flags: "Cờ", noFlags: "Không có cờ nào.",
    provenance: "Nguồn tri thức", noProv: "Chưa có nguồn tri thức nào được dùng.", scenario: "Kịch bản", behavior: "Hành vi", motive: "Động cơ", workflow: "Quy trình",
    suggestion: "Gợi ý của AI", noSuggestion: "Chưa có gợi ý.", reason: "Lý do", suggestedQuestions: "Câu hỏi gợi ý", turnsUsed: "Lượt đã dùng",
    help: "Yêu cầu trợ giúp", noHelp: "Không có yêu cầu trợ giúp.", reply: "Phản hồi", by: "bởi",
    feedback: "Phản hồi về AI", agree: "Đồng ý", disagree: "Không đồng ý", errorTypes: "Loại lỗi", comment: "Nhận xét", submit: "Gửi phản hồi",
    needType: "Chọn ít nhất một loại lỗi.", saved: "Đã ghi nhận phản hồi.", saveError: "Không gửi được phản hồi.", noFeedback: "Chưa có phản hồi.", readOnly: "Chỉ xem.",
    state: { eligible: "Đủ điều kiện", not_eligible: "Chưa đủ điều kiện", needs_driver: "Cần tài xế bổ sung", missing_internal: "Thiếu dữ liệu nội bộ" },
    flag: { novel_scenario: "Kịch bản mới", statement_changed: "Lời khai thay đổi", ai_inconclusive: "AI chưa kết luận", session_interrupted: "Phiên bị gián đoạn", asked_for_help: "Đã nhờ trợ giúp", asked_for_help_skipped: "Bỏ qua trợ giúp" },
    err: { wrong_facts: "Sai sự kiện", wrong_reasoning: "Suy luận sai", missing_question: "Thiếu câu hỏi", redundant_or_tone: "Thừa hoặc giọng điệu", missing_tool_source: "Thiếu nguồn công cụ", wrong_scenario_or_workflow: "Sai kịch bản/quy trình" },
    helpStatus: { open: "Đang chờ", claimed: "Đã nhận", replied: "Đã trả lời", expired: "Hết hạn" },
  },
  en: {
    title: "AI explanation", subtitle: "Automated Q&A session with the driver", loading: "Loading AI explanation…", error: "Could not load the AI explanation.",
    statements: "Statements", version: "Version", source: "Source", diff: "Diff vs previous", noDiff: "No changes.", show: "Show", hide: "Hide",
    rounds: "Assessment rounds", round: "Round", confidence: "Confidence", turns: "Turns", flags: "Flags", noFlags: "No flags raised.",
    provenance: "Provenance", noProv: "No knowledge objects used yet.", scenario: "Scenario", behavior: "Behavior", motive: "Motive", workflow: "Workflow",
    suggestion: "AI suggestion", noSuggestion: "No suggestion yet.", reason: "Reason", suggestedQuestions: "Suggested questions", turnsUsed: "Turns used",
    help: "Help requests", noHelp: "No help requests.", reply: "Reply", by: "by",
    feedback: "Feedback on the AI", agree: "Agree", disagree: "Disagree", errorTypes: "Error types", comment: "Comment", submit: "Send feedback",
    needType: "Select at least one error type.", saved: "Feedback recorded.", saveError: "Could not send feedback.", noFeedback: "No feedback yet.", readOnly: "Read-only.",
    state: { eligible: "Eligible", not_eligible: "Not eligible", needs_driver: "Needs driver input", missing_internal: "Missing internal data" },
    flag: { novel_scenario: "Novel scenario", statement_changed: "Statement changed", ai_inconclusive: "AI inconclusive", session_interrupted: "Session interrupted", asked_for_help: "Asked for help", asked_for_help_skipped: "Help skipped" },
    err: { wrong_facts: "Wrong facts", wrong_reasoning: "Wrong reasoning", missing_question: "Missing question", redundant_or_tone: "Redundant or tone", missing_tool_source: "Missing tool source", wrong_scenario_or_workflow: "Wrong scenario/workflow" },
    helpStatus: { open: "Open", claimed: "Claimed", replied: "Replied", expired: "Expired" },
  },
} as const;

const chip = (tone: string) => `gs-tone ${tone} inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold`;
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const fmt = (iso: string | null | undefined, locale: Locale) =>
  iso ? new Date(iso).toLocaleString(locale === "vi" ? "vi-VN" : "en-GB", { dateStyle: "short", timeStyle: "short" }) : "—";
const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x : JSON.stringify(x))) : typeof v === "string" && v ? [v] : []);
const h = "text-[11px] font-semibold uppercase tracking-wide text-gs-mute";

export function ExplainSection({ caseId, locale, roles }: { caseId: string; locale: Locale; roles: readonly string[] | null | undefined }) {
  const m = MSG[locale];
  const [data, setData] = useState<ExplainView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [verdict, setVerdict] = useState<"agree" | "disagree">("agree");
  const [types, setTypes] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const view = await explainApi.get(caseId);
      setData(view && view.session ? view : null);
      setError(false);
    } catch (err) {
      setData(null);
      setError(!isNoSession(err));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    setLoading(true); setData(null); setOpen(null); setNote(null); // eslint-disable-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (loading) return <p role="status" className="my-2 text-xs text-gs-mute">{m.loading}</p>;
  if (error) return <p role="status" data-testid="explain-error" className="my-2 text-xs text-gs-mute">{m.error}</p>;
  if (!data) return null;

  const canWrite = canGiveFeedback(roles);
  const canSubmit = !busy && (verdict === "agree" || types.length > 0);
  const send = async () => {
    setBusy(true); setNote(null);
    try {
      await explainApi.feedback(caseId, { verdict, error_types: verdict === "agree" ? [] : types, comment: comment.trim() });
      setNote({ ok: true, text: m.saved }); setTypes([]); setComment("");
      await load();
    } catch {
      setNote({ ok: false, text: m.saveError });
    } finally {
      setBusy(false);
    }
  };
  const activeFlags = FLAG_KEYS.filter((f) => data.flags?.[f]);
  const sug = data.suggestion;
  const versions = data.statement_versions ?? [];

  return (
    <div data-testid="explain-section" className="my-3 space-y-3">
      <SectionCard icon={Sparkles} tone="violet" title={m.title} subtitle={`${data.session.reason} · ${data.session.state}`}
        right={<span className={chip("t-purple")}>AI</span>} bodyClassName="space-y-4">
        <div>
          <p className={h}>{m.flags}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {activeFlags.length === 0 && <span className="text-xs text-gs-mute">{m.noFlags}</span>}
            {activeFlags.map((f) => <span key={f} data-testid={`flag-${f}`} className={chip(flagTone(f))}>{m.flag[f]}</span>)}
          </div>
        </div>

        <div>
          <p className={h}>{m.statements}</p>
          <ul className="mt-1 space-y-1.5">
            {versions.map((v, i) => {
              const expanded = open === v.version;
              const diff = i > 0 ? diffStatements(versions[i - 1].text, v.text) : null;
              return (
                <li key={v.version} className="rounded-lg border border-gs-line bg-white p-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gs-ink">{m.version} {v.version}</span>
                    <span className="text-gs-mute">{m.source}: {v.source} · {fmt(v.created_at, locale)}</span>
                    <button type="button" data-testid={`version-toggle-${v.version}`} aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? null : v.version)}
                      className="ml-auto rounded border border-gs-line-2 bg-white px-2 py-0.5 text-[11px] text-gs-ink-2 hover:bg-background">
                      {expanded ? m.hide : m.show}
                    </button>
                  </div>
                  {expanded && (
                    <div className="mt-2 space-y-1">
                      {diff ? (
                        <div aria-label={m.diff}>
                          <p className={h}>{m.diff}</p>
                          {diff.every((d) => d.op === "same") && <p className="text-gs-mute">{m.noDiff}</p>}
                          {diff.map((d, k) => (
                            <p key={k} data-testid={d.op === "add" ? "diff-add" : d.op === "del" ? "diff-del" : undefined}
                              className={d.op === "add" ? "rounded bg-gs-green-soft px-1 text-gs-green-ink" : d.op === "del" ? "rounded bg-gs-red-soft px-1 text-gs-red line-through" : "px-1 text-gs-ink-2"}>
                              {d.op === "add" ? "+ " : d.op === "del" ? "− " : "  "}{d.text}
                            </p>
                          ))}
                        </div>
                      ) : <p className="whitespace-pre-wrap text-gs-ink-2">{v.text || "—"}</p>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        <div>
          <p className={h}>{m.rounds}</p>
          <ul className="mt-1 space-y-1.5">
            {data.rounds.map((r) => (
              <li key={r.round} data-testid={`round-${r.round}`} data-state={r.state}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-gs-line bg-white p-2 text-xs">
                <span className="font-semibold text-gs-ink">{m.round} {r.round}</span>
                <span className={chip(roundStateTone(r.state))}>{m.state[r.state] ?? r.state}</span>
                <span className="text-gs-mute">{m.confidence}: {pct(r.confidence)} · {m.turns}: {r.turns_used}/{r.n_max} · {fmt(r.created_at, locale)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div data-testid="provenance">
          <p className={h}>{m.provenance}</p>
          {data.provenance.length === 0 ? <p className="mt-1 text-xs text-gs-mute">{m.noProv}</p> : (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {data.provenance.map((p, i) => (
                <li key={`${p.type}-${p.code}-${i}`} className="rounded-lg border border-gs-line bg-white px-2 py-1 text-xs text-gs-ink-2">
                  <span className="text-gs-mute">{(m as Record<string, unknown>)[p.type] as string ?? p.type}</span>{" "}
                  <span className="font-mono font-semibold text-gs-ink">{p.code}</span> v{p.version ?? "?"}
                  {p.tool && <span className="ml-1 text-gs-mute">· {p.tool}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div data-testid="suggestion">
          <p className={h}>{m.suggestion}</p>
          {!sug ? <p className="mt-1 text-xs text-gs-mute">{m.noSuggestion}</p> : (
            <div className="mt-1 space-y-1 rounded-lg border border-gs-purple/30 bg-white p-2 text-xs text-gs-ink-2">
              <p className="flex flex-wrap items-center gap-2">
                <span className={chip(roundStateTone(sug.state))}>{m.state[sug.state] ?? sug.state}</span>
                <span>{m.confidence}: {pct(sug.confidence)}</span>
                <span>{m.turnsUsed}: {sug.turns_used} / {sug.n_max}</span>
                {sug.reason_code && <span>{m.reason}: <span className="font-mono">{sug.reason_code}</span></span>}
              </p>
              {typeof sug.motive === "string" && sug.motive && <p>{sug.motive}</p>}
              {asList(sug.suggested_questions).length > 0 && (
                <div><p className={h}>{m.suggestedQuestions}</p>
                  <ul className="list-disc pl-4">{asList(sug.suggested_questions).map((q, i) => <li key={i}>{q}</li>)}</ul></div>
              )}
            </div>
          )}
        </div>

        <div data-testid="help-history">
          <p className={h}>{m.help}</p>
          {data.help_requests.length === 0 ? <p className="mt-1 text-xs text-gs-mute">{m.noHelp}</p> : (
            <ul className="mt-1 space-y-1.5">
              {data.help_requests.map((r) => (
                <li key={r.id} className="rounded-lg border border-gs-line bg-white p-2 text-xs text-gs-ink-2">
                  <p className="flex items-center gap-2">
                    <span className={chip(r.status === "replied" ? "t-green" : r.status === "expired" ? "t-grey" : r.status === "claimed" ? "t-cyan" : "t-amber")}>
                      {(m.helpStatus as Record<string, string>)[r.status] ?? r.status}
                    </span>
                    <span>{r.summary}</span>
                  </p>
                  {r.reply && <p className="mt-1 rounded bg-gs-cyan-soft p-1.5">{m.reply}: {r.reply}{r.replied_by_name ? ` (${m.by} ${r.replied_by_name})` : ""}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className={h}>{m.feedback}</p>
          {(() => {
            const latest = latestFeedbackPerAuthor(data.feedback);
            if (latest.length === 0) return <p className="mt-1 text-xs text-gs-mute">{m.noFeedback}</p>;
            return (
              <ul className="mt-1 space-y-1">
                {latest.map((f) => (
                  <li key={f.id} data-testid="feedback-entry" className="flex flex-wrap items-center gap-2 rounded-lg border border-gs-line bg-white p-2 text-xs text-gs-ink-2">
                    <span className={chip(f.verdict === "agree" ? "t-green" : "t-red")}>{f.verdict === "agree" ? m.agree : m.disagree}</span>
                    <span className="font-semibold">{f.author_name ?? "—"}</span>
                    <span className="text-gs-mute">{fmt(f.created_at, locale)}</span>
                    {f.error_types.map((e) => <span key={e} className={chip("t-grey")}>{(m.err as Record<string, string>)[e] ?? e}</span>)}
                    {f.comment && <span className="w-full">{f.comment}</span>}
                  </li>
                ))}
              </ul>
            );
          })()}
          {!canWrite ? <p className="mt-2 text-xs text-gs-mute">{m.readOnly}</p> : (
            <form data-testid="feedback-form" className="mt-2 space-y-2 rounded-lg border border-gs-line bg-white p-2"
              onSubmit={(e) => { e.preventDefault(); if (canSubmit) void send(); }}>
              <div role="group" aria-label={m.feedback} className="flex gap-2">
                {(["agree", "disagree"] as const).map((v) => (
                  <button key={v} type="button" data-testid={`feedback-${v}`} aria-pressed={verdict === v} onClick={() => setVerdict(v)}
                    className={`rounded-lg border px-3 py-1 text-xs font-semibold ${verdict === v ? "border-primary bg-gs-cyan-soft text-primary" : "border-gs-line-2 bg-white text-gs-ink-2 hover:bg-background"}`}>
                    {v === "agree" ? m.agree : m.disagree}
                  </button>
                ))}
              </div>
              {verdict === "disagree" && (
                <fieldset className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                  <legend className={h}>{m.errorTypes}</legend>
                  {FEEDBACK_ERROR_TYPES.map((t) => (
                    <label key={t} className="flex items-center gap-1.5 text-xs text-gs-ink-2">
                      <input type="checkbox" checked={types.includes(t)}
                        onChange={(e) => setTypes((cur) => (e.target.checked ? [...cur, t] : cur.filter((x) => x !== t)))} />
                      {m.err[t]}
                    </label>
                  ))}
                  {types.length === 0 && <p className="col-span-full text-[11px] text-gs-amber-ink">{m.needType}</p>}
                </fieldset>
              )}
              <textarea data-testid="feedback-comment" aria-label={m.comment} placeholder={m.comment} value={comment} onChange={(e) => setComment(e.target.value)}
                rows={2} maxLength={2000} className="w-full rounded-lg border border-gs-line-2 bg-white p-2 text-xs text-gs-ink focus:border-primary focus:outline-none" />
              <div className="flex items-center gap-2">
                <button type="submit" data-testid="feedback-submit" disabled={!canSubmit}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-container disabled:opacity-50">{m.submit}</button>
                {note && <span role={note.ok ? "status" : "alert"} className={`text-xs ${note.ok ? "text-gs-green-ink" : "text-gs-red"}`}>{note.text}</span>}
              </div>
            </form>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
