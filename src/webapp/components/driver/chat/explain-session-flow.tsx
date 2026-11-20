"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { CheckCircle2, ChevronLeft, Loader2, Send, UserRound, Bot } from "lucide-react";
import {
  conflictCode,
  driverExplainClient as client,
  parseFormInvalid,
  pick,
  type ExplainAnswers,
  type ExplainField,
  type ExplainView,
  type FormInvalid,
} from "@/lib/driver-explain-client";

export const DRAFT_DEBOUNCE_MS = 700;
const CHECK_POLL_MS = 2000;
const HELP_POLL_MS = 5000;
const STEP_OF: Record<ExplainView["ui_status"], number> = { form: 1, checking: 1, chat: 2, summary: 3, submitted: 4 };

const primary =
  "w-full min-h-[52px] rounded-full bg-emerald-600 text-white text-base font-bold disabled:opacity-40 active:scale-[0.99] transition cursor-pointer";
const secondary =
  "w-full min-h-[48px] rounded-full border-2 border-emerald-600 text-emerald-700 dark:text-emerald-400 text-base font-bold disabled:opacity-40 cursor-pointer";
const inputCls =
  "w-full min-h-[48px] rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-base outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20";

export interface ExplainSessionFlowProps {
  caseId: string;
  initial: ExplainView;
  caseTitle?: string | null;
  deadline?: string | null;
  onClose: () => void;
}

export function ExplainSessionFlow({ caseId, initial, caseTitle, deadline, onClose }: ExplainSessionFlowProps) {
  const t = useTranslations("driver.explain");
  const tv = useTranslations("driver.explain.v2");
  const locale = useLocale();
  const [view, setView] = useState<ExplainView>(initial);
  const [answers, setAnswers] = useState<ExplainAnswers>(initial.form.answers ?? {});
  const [formErr, setFormErr] = useState<FormInvalid | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const dirty = useRef(false);
  const status = view.ui_status;
  const step = STEP_OF[status];

  const guard = useCallback(
    async (fn: () => Promise<ExplainView>): Promise<ExplainView | null> => {
      setBusy(true);
      setError(null);
      try {
        const next = await fn();
        setView(next);
        return next;
      } catch (e) {
        const code = conflictCode(e);
        if (code === "waiting_for_help") setError(tv("waitingBlocked"));
        else setError(tv("actionError"));
        if (code) {
          try { setView(await client.get(caseId)); } catch { /* keep current view */ }
        }
        return null;
      } finally {
        setBusy(false);
      }
    },
    [caseId, tv],
  );

  // Draft autosave while the form is open.
  useEffect(() => {
    if (status !== "form" || !dirty.current) return;
    const id = setTimeout(() => {
      setSaveState("saving");
      client.saveDraft(caseId, answers).then(() => setSaveState("saved")).catch(() => setSaveState("idle"));
    }, DRAFT_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [answers, caseId, status]);

  // Poll while the agent is checking or a help request blocks the chat.
  useEffect(() => {
    const polling = status === "checking" || (status === "chat" && view.waiting_for_help);
    if (!polling) return;
    const id = setInterval(() => {
      client.get(caseId).then(setView).catch(() => undefined);
    }, status === "checking" ? CHECK_POLL_MS : HELP_POLL_MS);
    return () => clearInterval(id);
  }, [status, view.waiting_for_help, caseId]);

  const setAnswer = (id: string, value: string) => {
    dirty.current = true;
    setSaveState("idle");
    setAnswers((a) => ({ ...a, [id]: value }));
    setFormErr((f) => (f ? { missing: f.missing.filter((m) => m !== id), invalid: f.invalid.filter((i) => i.field !== id) } : f));
  };

  const submitForm = async () => {
    setBusy(true);
    setError(null);
    try {
      setView(await client.submit(caseId, answers));
      setFormErr(null);
    } catch (e) {
      const bad = parseFormInvalid(e);
      if (bad) {
        setFormErr(bad);
        setError(tv("formErrors"));
        const first = [...bad.missing, ...bad.invalid.map((i) => i.field)][0];
        if (first) document.querySelector(`[data-testid="explain-field-${first}"]`)?.scrollIntoView?.({ block: "center" });
      } else {
        setError(tv("actionError"));
      }
    } finally {
      setBusy(false);
    }
  };

  const sendReply = async () => {
    const text = reply.trim();
    if (!text) return;
    const next = await guard(() => client.answer(caseId, text, [], undefined));
    if (next) setReply("");
  };

  const deadlineLabel = (() => {
    if (!deadline) return null;
    const d = new Date(deadline);
    if (Number.isNaN(d.getTime())) return null;
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}, ${d.toLocaleDateString("vi-VN")}`;
  })();

  const stepLabels = [tv("stepForm"), tv("stepChat"), tv("stepSummary"), tv("stepDone")];
  const statusText = pick(view.status_text ?? undefined, locale);

  if (status === "submitted") {
    return (
      <div data-testid="driver-explain-flow" role="dialog" aria-label={t("title")} className="absolute inset-0 z-50 flex flex-col bg-white dark:bg-slate-900">
        <div data-testid="explain-v2-submitted" className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-3">
          <span className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-600 text-white">
            <CheckCircle2 className="h-10 w-10" />
          </span>
          <h2 className="text-2xl font-bold">{tv("submittedTitle")}</h2>
          <p className="text-slate-600 dark:text-slate-300">{statusText || t("successDesc")}</p>
        </div>
        <div className="p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <button type="button" data-testid="driver-explain-done" onClick={onClose} className={primary}>
            {t("backToCase")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="driver-explain-flow" role="dialog" aria-label={t("title")} className="absolute inset-0 z-50 flex flex-col bg-[var(--driver-canvas)]">
      <div className="bg-white dark:bg-slate-900 px-3 pt-3 pb-3 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-1">
          <button type="button" aria-label={t("close")} onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-slate-100 dark:hover:bg-slate-800">
            <ChevronLeft className="h-6 w-6" />
          </button>
          <div className="flex-1 min-w-0 text-center pr-11">
            <h2 className="text-[17px] font-bold">{t("title")}</h2>
            {caseTitle && <p className="text-xs text-slate-500 truncate">{caseTitle}</p>}
          </div>
        </div>
        <div className="mt-2 flex items-center gap-1.5" role="img" aria-label={t("stepLabel", { current: step, total: 4 })}>
          {[1, 2, 3, 4].map((i) => (
            <span key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? "bg-emerald-600" : "bg-slate-200 dark:bg-slate-700"}`} />
          ))}
        </div>
        <div className="mt-1.5 flex justify-between text-xs">
          <span className="font-semibold text-emerald-700 dark:text-emerald-400">{stepLabels[step - 1]}</span>
          <span className="text-slate-500">{t("stepLabel", { current: step, total: 4 })}</span>
        </div>
      </div>
      {deadlineLabel && status === "form" && (
        <div className="flex items-center justify-between bg-[var(--driver-strip)] px-4 py-2 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
          <span>{t("timeLeft")}</span>
          <span>{deadlineLabel}</span>
        </div>
      )}

      {status === "form" && (
        <FormStep
          view={view}
          answers={answers}
          formErr={formErr}
          locale={locale}
          onChange={setAnswer}
          saveState={saveState}
          error={error}
          busy={busy}
          onSubmit={() => void submitForm()}
        />
      )}

      {status === "checking" && (
        <div data-testid="explain-v2-checking" role="status" className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-4">
          <Loader2 className="h-12 w-12 animate-spin text-emerald-600" />
          <h3 className="text-xl font-bold">{statusText || tv("checkingTitle")}</h3>
          <p className="text-slate-600 dark:text-slate-300">{tv("checkingDesc")}</p>
        </div>
      )}

      {status === "chat" && (
        <ChatStep
          view={view}
          reply={reply}
          setReply={setReply}
          busy={busy}
          error={error}
          onSend={() => void sendReply()}
          onEnd={() => void guard(() => client.end(caseId))}
        />
      )}

      {status === "summary" && (
        <SummaryStep
          view={view}
          editing={editing}
          editText={editText}
          setEditText={setEditText}
          busy={busy}
          error={error}
          onStartEdit={() => { setEditText(view.summary ?? ""); setEditing(true); }}
          onCancelEdit={() => setEditing(false)}
          onSaveEdit={async () => {
            const next = await guard(() => client.editSummary(caseId, editText.trim()));
            if (next) setEditing(false);
          }}
          onConfirm={() => void guard(() => client.confirm(caseId))}
        />
      )}
    </div>
  );
}

function FormStep({
  view, answers, formErr, locale, onChange, saveState, error, busy, onSubmit,
}: {
  view: ExplainView;
  answers: ExplainAnswers;
  formErr: FormInvalid | null;
  locale: string;
  onChange: (id: string, v: string) => void;
  saveState: "idle" | "saving" | "saved";
  error: string | null;
  busy: boolean;
  onSubmit: () => void;
}) {
  const tv = useTranslations("driver.explain.v2");
  return (
    <>
      <div data-testid="explain-v2-form" className="flex-1 overflow-y-auto px-4 py-5 space-y-4">
        <p className="text-sm text-slate-500">{tv("formHint")}</p>
        {view.form.fields.map((f) => {
          const missing = formErr?.missing.includes(f.id) ?? false;
          const invalid = formErr?.invalid.find((i) => i.field === f.id);
          const bad = missing || Boolean(invalid);
          const msg = missing ? tv("missingField") : invalid ? tv(invalid.code as "invalid_amount") : null;
          return (
            <div
              key={f.id}
              data-testid={`explain-field-${f.id}`}
              data-invalid={bad ? "true" : undefined}
              className={`rounded-2xl bg-white dark:bg-slate-800 p-4 shadow-xs space-y-2 ${bad ? "ring-2 ring-red-500" : ""}`}
            >
              <label htmlFor={`explain-input-${f.id}`} className="block text-[15px] font-semibold">
                {pick(f.label, locale)}
                {f.required ? <span className="text-red-600" aria-label={tv("required")}> *</span> : <span className="ml-2 text-xs font-normal text-slate-400">{tv("optional")}</span>}
              </label>
              <FieldInput field={f} value={String(answers[f.id] ?? "")} invalid={bad} locale={locale} onChange={(v) => onChange(f.id, v)} />
              {msg && <p role="alert" className="text-sm font-medium text-red-600">{msg}</p>}
            </div>
          );
        })}
        <p className="h-4 text-xs text-slate-400" aria-live="polite">
          {saveState === "saving" ? tv("saving") : saveState === "saved" ? tv("saved") : ""}
        </p>
        {error && <p role="alert" data-testid="explain-v2-error" className="text-sm font-medium text-red-600">{error}</p>}
      </div>
      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <button type="button" data-testid="explain-v2-submit" disabled={busy} onClick={onSubmit} className={primary}>
          {busy ? tv("submitting") : tv("submit")}
        </button>
      </div>
    </>
  );
}

function FieldInput({
  field, value, invalid, locale, onChange,
}: { field: ExplainField; value: string; invalid: boolean; locale: string; onChange: (v: string) => void }) {
  const tv = useTranslations("driver.explain.v2");
  const common = {
    id: `explain-input-${field.id}`,
    "data-testid": `explain-input-${field.id}`,
    "aria-invalid": invalid,
    className: inputCls,
  } as const;
  switch (field.type) {
    case "time":
      return <input {...common} type="time" value={value} onChange={(e) => onChange(e.target.value)} />;
    case "amount":
      return <input {...common} type="text" inputMode="numeric" placeholder={tv("amountHint")} value={value} onChange={(e) => onChange(e.target.value)} />;
    case "choice":
      return (
        <select {...common} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{tv("choose")}</option>
          {(field.options ?? []).map((o) => (
            <option key={o.value} value={o.value}>{o.label ? pick(o.label, locale) : o.value}</option>
          ))}
        </select>
      );
    case "ticket":
      return <input {...common} type="text" placeholder={tv("ticketHint")} value={value} onChange={(e) => onChange(e.target.value)} />;
    case "photo":
      return <textarea {...common} rows={2} placeholder={tv("photoHint")} value={value} onChange={(e) => onChange(e.target.value)} />;
    case "location":
      return <input {...common} type="text" autoComplete="street-address" value={value} onChange={(e) => onChange(e.target.value)} />;
    default:
      return <textarea {...common} rows={3} value={value} onChange={(e) => onChange(e.target.value)} />;
  }
}

function ChatStep({
  view, reply, setReply, busy, error, onSend, onEnd,
}: {
  view: ExplainView;
  reply: string;
  setReply: (v: string) => void;
  busy: boolean;
  error: string | null;
  onSend: () => void;
  onEnd: () => void;
}) {
  const tv = useTranslations("driver.explain.v2");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: "end" }); }, [view.messages.length, view.current_question?.seq]);
  const q = view.current_question;
  return (
    <>
      <div data-testid="explain-v2-chat" className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        <p className="text-xs text-slate-500">{tv("chatHint")}</p>
        {view.messages.filter((m) => !m.is_summary && m.seq !== q?.seq).map((m) => (
          <div key={m.seq} className={`flex gap-2 ${m.role === "driver" ? "flex-row-reverse" : ""}`}>
            <span className={`mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${m.role === "driver" ? "bg-emerald-600 text-white" : "bg-slate-200 dark:bg-slate-700"}`}>
              {m.role === "driver" ? <UserRound className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
            </span>
            <p className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[15px] whitespace-pre-wrap break-words ${m.role === "driver" ? "bg-emerald-600 text-white" : "bg-white dark:bg-slate-800 shadow-xs"}`}>
              {m.text}
            </p>
          </div>
        ))}
        {q && (
          <div className="flex gap-2">
            <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 dark:bg-slate-700"><Bot className="h-4 w-4" /></span>
            <p data-testid="explain-v2-question" className="max-w-[80%] rounded-2xl bg-white dark:bg-slate-800 px-4 py-2.5 text-[15px] shadow-xs">{q.text}</p>
          </div>
        )}
        {view.waiting_for_help && (
          <div data-testid="explain-v2-waiting" role="status" className="rounded-2xl bg-amber-50 dark:bg-amber-950/40 p-4 text-sm">
            <p className="flex items-center gap-2 font-bold text-amber-800 dark:text-amber-300"><Loader2 className="h-4 w-4 animate-spin" />{tv("waitingTitle")}</p>
            <p className="mt-1 text-amber-900/80 dark:text-amber-200/80">{tv("waitingDesc")}</p>
          </div>
        )}
        {error && <p role="alert" data-testid="explain-v2-error" className="text-sm font-medium text-red-600">{error}</p>}
        <div ref={endRef} />
      </div>
      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] space-y-2">
        {!view.waiting_for_help && q && (
          <div className="flex items-end gap-2">
            <textarea
              data-testid="explain-v2-answer"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={2}
              placeholder={tv("answerPlaceholder")}
              className={`${inputCls} flex-1 resize-none`}
            />
            <button
              type="button"
              data-testid="explain-v2-send"
              aria-label={tv("send")}
              disabled={busy || !reply.trim()}
              onClick={onSend}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white disabled:opacity-40 cursor-pointer"
            >
              {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
            </button>
          </div>
        )}
        {view.can_end && (
          <button type="button" data-testid="explain-v2-end" disabled={busy} onClick={onEnd} className={secondary} title={tv("endHint")}>
            {tv("end")}
          </button>
        )}
      </div>
    </>
  );
}

function SummaryStep({
  view, editing, editText, setEditText, busy, error, onStartEdit, onCancelEdit, onSaveEdit, onConfirm,
}: {
  view: ExplainView;
  editing: boolean;
  editText: string;
  setEditText: (v: string) => void;
  busy: boolean;
  error: string | null;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onConfirm: () => void;
}) {
  const tv = useTranslations("driver.explain.v2");
  return (
    <div data-testid="explain-v2-summary" className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-3">
        <div>
          <h3 className="text-lg font-bold">{tv("summaryTitle")}</h3>
          <p className="text-sm text-slate-500 mt-1">{tv("summaryHint")}</p>
        </div>
        {editing ? (
          <textarea
            data-testid="explain-v2-edit-text"
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={10}
            className={inputCls}
          />
        ) : (
          <div className="rounded-[20px] bg-white dark:bg-slate-800 p-4 shadow-xs text-[15px] whitespace-pre-wrap break-words">{view.summary}</div>
        )}
        <p className="text-xs text-slate-500" data-testid="explain-v2-edits-left">
          {view.edits_left > 0 ? tv("editsLeft", { count: view.edits_left }) : tv("noEditsLeft")}
        </p>
        {error && <p role="alert" data-testid="explain-v2-error" className="text-sm font-medium text-red-600">{error}</p>}
      </div>
      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] space-y-2">
        {editing ? (
          <>
            <button type="button" data-testid="explain-v2-edit-save" disabled={busy || !editText.trim()} onClick={onSaveEdit} className={primary}>{tv("saveEdit")}</button>
            <button type="button" onClick={onCancelEdit} className={secondary}>{tv("cancel")}</button>
          </>
        ) : (
          <>
            <button type="button" data-testid="explain-v2-confirm" disabled={busy} onClick={onConfirm} className={primary}>
              {busy ? tv("confirming") : tv("confirm")}
            </button>
            {view.edits_left > 0 && (
              <button type="button" data-testid="explain-v2-edit" disabled={busy} onClick={onStartEdit} className={secondary}>{tv("editSummary")}</button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
