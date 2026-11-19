"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, ChevronLeft, Circle, CircleDot, Lightbulb } from "lucide-react";

export const EXPLAIN_MIN_CHARS = 20;
export const EXPLAIN_MAX_CHARS = 500;
const STEPS = 4;
const REASONS = ["NotDone", "RealTrip", "Tech", "Customer", "Other"] as const;
type Reason = (typeof REASONS)[number];

export interface DriverExplainFlowProps {
  caseTitle?: string | null;
  deadline?: string | null;
  onClose: () => void;
  /** Resolve on success, throw/reject on failure. Receives the composed statement. */
  onSubmit: (summary: string) => Promise<void>;
}

export function DriverExplainFlow({ caseTitle, deadline, onClose, onSubmit }: DriverExplainFlowProps) {
  const t = useTranslations("driver.explain");
  const [step, setStep] = useState(1);
  const [reason, setReason] = useState<Reason | null>(null);
  const [detail, setDetail] = useState("");
  const [evidence, setEvidence] = useState("");
  const [touched, setTouched] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const trimmed = detail.trim();
  const missing = Math.max(0, EXPLAIN_MIN_CHARS - trimmed.length);
  const reasonLabel = reason ? t(`reason${reason}`) : "";

  const validationError =
    step === 1 && touched && !reason
      ? t("reasonRequired")
      : step === 2 && touched && missing > 0
        ? t("detailTooShort", { min: EXPLAIN_MIN_CHARS, missing })
        : null;

  const next = () => {
    setTouched(true);
    if (step === 1 && !reason) return;
    if (step === 2 && missing > 0) return;
    setTouched(false);
    setStep((s) => Math.min(STEPS, s + 1));
  };

  const submit = async () => {
    setSending(true);
    setError(null);
    const parts = [`${t("reviewReason")}: ${reasonLabel}`, `${t("reviewDetail")}: ${trimmed}`];
    if (evidence.trim()) parts.push(`${t("reviewEvidence")}: ${evidence.trim()}`);
    try {
      await onSubmit(parts.join("\n"));
      setDone(true);
    } catch {
      setError(t("sendError"));
    } finally {
      setSending(false);
    }
  };

  const deadlineLabel = (() => {
    if (!deadline) return null;
    const d = new Date(deadline);
    if (Number.isNaN(d.getTime())) return null;
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}, ${d.toLocaleDateString("vi-VN")}`;
  })();

  const primary =
    "w-full min-h-[52px] rounded-full bg-emerald-600 text-white text-base font-bold disabled:opacity-40 active:scale-[0.99] transition cursor-pointer";

  if (done) {
    return (
      <div data-testid="driver-explain-flow" role="dialog" aria-label={t("title")} className="absolute inset-0 z-50 flex flex-col bg-white dark:bg-slate-900">
        <div className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-3">
          <span className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-600 text-white">
            <CheckCircle2 className="h-10 w-10" />
          </span>
          <h2 className="text-2xl font-bold">{t("successTitle")}</h2>
          <p className="text-slate-600 dark:text-slate-300">{t("successDesc")}</p>
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
          <button
            type="button"
            aria-label={step === 1 ? t("close") : t("back")}
            onClick={() => (step === 1 ? onClose() : setStep(step - 1))}
            className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
          <div className="flex-1 min-w-0 text-center pr-11">
            <h2 className="text-[17px] font-bold">{t("title")}</h2>
            {caseTitle && <p className="text-xs text-slate-500 truncate">{caseTitle}</p>}
          </div>
        </div>
        <div className="mt-2 flex items-center gap-1.5" role="img" aria-label={t("stepLabel", { current: step, total: STEPS })}>
          {Array.from({ length: STEPS }, (_, i) => (
            <span key={i} className={`h-1.5 flex-1 rounded-full ${i < step ? "bg-emerald-600" : "bg-slate-200 dark:bg-slate-700"}`} />
          ))}
        </div>
        <div className="mt-1.5 flex justify-between text-xs">
          <span className="font-semibold text-emerald-700 dark:text-emerald-400">{t(`step${step}`)}</span>
          <span className="text-slate-500">{t("stepLabel", { current: step, total: STEPS })}</span>
        </div>
      </div>
      {deadlineLabel && (
        <div className="flex items-center justify-between bg-[var(--driver-strip)] px-4 py-2 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
          <span>{t("timeLeft")}</span>
          <span>{deadlineLabel}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-4">
        {step === 1 && (
          <>
            <div>
              <h3 className="text-lg font-bold">{t("reasonTitle")} <span className="text-red-600">*</span></h3>
              <p className="text-sm text-slate-500 mt-1">{t("reasonHint")}</p>
            </div>
            <div role="radiogroup" aria-label={t("reasonTitle")} className="space-y-2.5">
              {REASONS.map((r) => {
                const on = reason === r;
                return (
                  <button
                    key={r}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    data-testid={`explain-reason-${r}`}
                    onClick={() => setReason(r)}
                    className={`w-full min-h-[56px] flex items-center gap-3 rounded-2xl border-2 px-4 text-left text-[15px] font-semibold transition cursor-pointer ${
                      on ? "border-emerald-600 bg-[var(--driver-strip)]" : "border-transparent bg-white dark:bg-slate-800 shadow-xs"
                    }`}
                  >
                    {on ? <CircleDot className="h-5 w-5 text-emerald-600 shrink-0" /> : <Circle className="h-5 w-5 text-slate-300 shrink-0" />}
                    {t(`reason${r}`)}
                  </button>
                );
              })}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h3 className="text-lg font-bold">{t("detailTitle")} <span className="text-red-600">*</span></h3>
              <p className="text-sm text-slate-500 mt-1">{t("detailHint")}</p>
            </div>
            <textarea
              data-testid="explain-detail"
              value={detail}
              maxLength={EXPLAIN_MAX_CHARS}
              onChange={(e) => setDetail(e.target.value)}
              placeholder={t("detailPlaceholder")}
              aria-invalid={Boolean(validationError)}
              rows={7}
              className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 text-base outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20"
            />
            <div className="flex items-start justify-between gap-3 text-xs text-slate-500">
              <p className="flex gap-1.5"><Lightbulb className="h-4 w-4 shrink-0 text-amber-500" />{t("detailTips")}</p>
              <span className="shrink-0 tabular-nums">{t("detailCount", { count: detail.length, max: EXPLAIN_MAX_CHARS })}</span>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div>
              <h3 className="text-lg font-bold">{t("evidenceTitle")}</h3>
              <p className="text-sm text-slate-500 mt-1">{t("evidenceHint")}</p>
            </div>
            <textarea
              data-testid="explain-evidence"
              value={evidence}
              maxLength={EXPLAIN_MAX_CHARS}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder={t("evidencePlaceholder")}
              rows={5}
              className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 text-base outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20"
            />
            <button type="button" onClick={() => { setEvidence(""); setStep(4); }} className="min-h-11 text-sm font-semibold text-emerald-700 dark:text-emerald-400 underline cursor-pointer">
              {t("evidenceNone")}
            </button>
          </>
        )}

        {step === 4 && (
          <>
            <div>
              <h3 className="text-lg font-bold">{t("reviewTitle")}</h3>
              <p className="text-sm text-slate-500 mt-1">{t("reviewHint")}</p>
            </div>
            <div className="rounded-[20px] bg-white dark:bg-slate-800 shadow-xs divide-y divide-slate-100 dark:divide-slate-700" data-testid="explain-review">
              {([
                ["reviewReason", reasonLabel, 1],
                ["reviewDetail", trimmed, 2],
                ["reviewEvidence", evidence.trim() || "—", 3],
              ] as const).map(([k, v, target]) => (
                <div key={k} className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{t(k)}</span>
                    <button type="button" onClick={() => setStep(target)} className="min-h-9 px-2 text-sm font-semibold text-emerald-700 dark:text-emerald-400 cursor-pointer">
                      {t("edit")}
                    </button>
                  </div>
                  <p className="mt-1 text-[15px] whitespace-pre-wrap break-words">{v}</p>
                </div>
              ))}
            </div>
          </>
        )}

        {validationError && (
          <p role="alert" data-testid="explain-error" className="text-sm font-medium text-red-600">{validationError}</p>
        )}
        {error && <p role="alert" data-testid="explain-send-error" className="text-sm font-medium text-red-600">{error}</p>}
      </div>

      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {step < STEPS ? (
          <button type="button" data-testid="explain-next" onClick={next} className={primary}>
            {t("next")}
          </button>
        ) : (
          <button type="button" data-testid="explain-submit" disabled={sending} onClick={() => void submit()} className={primary}>
            {sending ? t("sending") : t("submit")}
          </button>
        )}
      </div>
    </div>
  );
}
