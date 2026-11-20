"use client";
import React from 'react';
import { confirmCaseMotivation, generateCaseMotivation, getCaseMotivation, saveCaseMotivation } from '@/lib/api-client';
import type { CaseMotivationAssessment, CaseMotivationResponse, MotiveCategory } from '@/types/schemas';
import { cn } from '@/lib/utils';

export const MOTIVE_CATEGORIES: MotiveCategory[] = ['reward_threshold', 'subsidy_surge', 'fare_inflation', 'platform_fault', 'unclear'];

const copy = {
  en: {
    category: { reward_threshold: 'Reward threshold', subsidy_surge: 'Subsidy / surge', fare_inflation: 'Fare inflation', platform_fault: 'Platform fault', unclear: 'Unclear' },
    signal: { mock_location: 'Mock GPS samples', fare_delta: 'Fare above quote', surge_capture: 'Surge gain', subsidy: 'Subsidy gain', bonus: 'Bonus', platform_incident: 'Platform incident', route_deviation: 'Route deviation', stationary: 'Stationary' } as Record<string, string>,
    status: { confirmed: 'Confirmed', draft: 'Draft', unsaved: 'Not saved' },
    source: { ai: 'AI', rule: 'Rule', analyst: 'Analyst' },
    categoryLabel: 'Motive category', signals: 'Evidence signals', amount: 'Amount at stake', confidence: 'Confidence', rationale: 'Rationale', version: 'Version',
    generate: 'Generate', regenerate: 'Regenerate', edit: 'Edit', confirm: 'Confirm', save: 'Save', cancel: 'Cancel', working: 'Working…',
    loading: 'Loading motivation…', error: 'Could not load the motivation assessment.', actionError: 'Action failed. Reload and retry.',
    noSignals: 'No evidence signals.', readOnly: 'Read-only',
  },
  vi: {
    category: { reward_threshold: 'Chạm ngưỡng thưởng', subsidy_surge: 'Trợ giá / giờ cao điểm', fare_inflation: 'Tăng cước phí', platform_fault: 'Lỗi nền tảng', unclear: 'Chưa rõ' },
    signal: { mock_location: 'Mẫu GPS giả lập', fare_delta: 'Cước vượt báo giá', surge_capture: 'Lợi ích giờ cao điểm', subsidy: 'Lợi ích trợ giá', bonus: 'Thưởng', platform_incident: 'Sự cố nền tảng', route_deviation: 'Lệch lộ trình', stationary: 'Đứng yên' } as Record<string, string>,
    status: { confirmed: 'Đã xác nhận', draft: 'Bản nháp', unsaved: 'Chưa lưu' },
    source: { ai: 'AI', rule: 'Quy tắc', analyst: 'Kiểm soát viên' },
    categoryLabel: 'Nhóm động cơ', signals: 'Dấu hiệu bằng chứng', amount: 'Số tiền liên quan', confidence: 'Độ tin cậy', rationale: 'Lý giải', version: 'Phiên bản',
    generate: 'Tạo đánh giá', regenerate: 'Tạo lại', edit: 'Sửa', confirm: 'Xác nhận', save: 'Lưu', cancel: 'Hủy', working: 'Đang xử lý…',
    loading: 'Đang tải đánh giá động cơ…', error: 'Không tải được đánh giá động cơ.', actionError: 'Thao tác thất bại. Hãy tải lại và thử lại.',
    noSignals: 'Chưa có dấu hiệu bằng chứng.', readOnly: 'Chỉ xem',
  },
} as const;

const btnPrimary = 'rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-container disabled:opacity-50';
const btnSecondary = 'rounded-md border border-gs-line-2 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50';

function signalValue(value: unknown, unit?: string | null, locale: 'en' | 'vi' = 'en'): string {
  if (value === true) return '✓';
  if (typeof value === 'number') return `${value.toLocaleString(locale === 'vi' ? 'vi-VN' : 'en-US', { maximumFractionDigits: 3 })}${unit ? ` ${unit === 'VND' ? '₫' : unit === 'samples' && locale === 'vi' ? 'mẫu' : unit}` : ''}`;
  return value == null ? '' : String(value);
}

/** Guards against malformed payloads (older API, proxies): require a known assessment shape. */
function validResponse(value: unknown): CaseMotivationResponse | null {
  const response = value as CaseMotivationResponse | null;
  const a = response?.assessment;
  if (!response || !a || !MOTIVE_CATEGORIES.includes(a.motive_category)) return null;
  const confidence = Number.isFinite(a.confidence) ? a.confidence : 0;
  return { ...response, assessment: { ...a, signals: Array.isArray(a.signals) ? a.signals : [], confidence, rationale: a.rationale ?? '' } };
}

/** Remounts per case so state never leaks between cases. */
export function MotivationCard(props: { caseId: string; canWrite: boolean; locale: 'en' | 'vi'; fallbackAmountVnd?: number | null }) {
  return <MotivationCardBody key={props.caseId} {...props} />;
}

function MotivationCardBody({ caseId, canWrite, locale, fallbackAmountVnd }: { caseId: string; canWrite: boolean; locale: 'en' | 'vi'; fallbackAmountVnd?: number | null }) {
  const t = copy[locale];
  const [data, setData] = React.useState<CaseMotivationResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<{ category: MotiveCategory; confidence: number; rationale: string }>({ category: 'unclear', confidence: 0, rationale: '' });

  React.useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => getCaseMotivation(caseId, controller.signal))
      .then(response => {
        if (controller.signal.aborted) return;
        const valid = validResponse(response);
        if (valid) setData(valid); else setError(t.error);
      })
      .catch(() => { if (!controller.signal.aborted) setError(t.error); });
    return () => controller.abort();
  }, [caseId, t.error]);

  const run = async (action: () => Promise<CaseMotivationResponse>) => {
    setBusy(true); setError(null);
    try {
      const valid = validResponse(await action());
      if (!valid) throw new Error('invalid response');
      setData(valid); setEditing(false);
    } catch { setError(t.actionError); } finally { setBusy(false); }
  };

  if (error && !data) return <p className="text-sm text-slate-500">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">{t.loading}</p>;

  const a: CaseMotivationAssessment = data.assessment;
  const statusKey = !data.persisted ? 'unsaved' : a.status;
  const statusClass = statusKey === 'confirmed' ? 'bg-gs-green-soft text-gs-green-ink' : statusKey === 'draft' ? 'bg-gs-amber-soft text-gs-amber-ink' : 'bg-slate-100 text-slate-600';
  const pct = Math.round(a.confidence * 100);
  const startEdit = () => { setDraft({ category: a.motive_category, confidence: pct, rationale: a.rationale }); setEditing(true); };

  return (
    <div className="space-y-3" data-testid="motivation-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-gs-cyan-soft px-2.5 py-0.5 text-xs font-semibold text-gs-cyan">{t.category[a.motive_category]}</span>
        <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-semibold', statusClass)}>{t.status[statusKey]}</span>
        <span className="text-[11px] text-slate-500">{t.source[a.source]}{data.persisted && ` · ${t.version} ${a.version}`}</span>
        {!canWrite && <span className="ml-auto text-[11px] text-slate-500">{t.readOnly}</span>}
      </div>

      {editing ? (
        <div className="space-y-2">
          <label className="block text-[11px] font-semibold text-slate-600">
            {t.categoryLabel}
            <select aria-label={t.categoryLabel} value={draft.category} onChange={e => setDraft({ ...draft, category: e.target.value as MotiveCategory })} className="mt-1 block w-full rounded-md border border-slate-300 bg-white p-1.5 text-[13px] font-normal outline-none focus:border-primary focus:ring-2 focus:ring-primary/30">
              {MOTIVE_CATEGORIES.map(c => <option key={c} value={c}>{t.category[c]}</option>)}
            </select>
          </label>
          <label className="block text-[11px] font-semibold text-slate-600">
            {t.confidence}: {draft.confidence}%
            <input aria-label={t.confidence} type="range" min={0} max={100} value={draft.confidence} onChange={e => setDraft({ ...draft, confidence: Number(e.target.value) })} className="mt-1 block w-full accent-primary" />
          </label>
          <label className="block text-[11px] font-semibold text-slate-600">
            {t.rationale}
            <textarea aria-label={t.rationale} rows={3} maxLength={2000} value={draft.rationale} onChange={e => setDraft({ ...draft, rationale: e.target.value })} className="mt-1 block w-full rounded-md border border-slate-300 bg-white p-2 text-[13px] font-normal outline-none focus:border-primary focus:ring-2 focus:ring-primary/30" />
          </label>
          <div className="flex gap-2">
            <button type="button" disabled={busy || !draft.rationale.trim()} className={btnPrimary}
              onClick={() => void run(() => saveCaseMotivation(caseId, { motive_category: draft.category, signals: a.signals, confidence: draft.confidence / 100, rationale: draft.rationale.trim(), expected_version: a.version }))}>{busy ? t.working : t.save}</button>
            <button type="button" disabled={busy} className={btnSecondary} onClick={() => setEditing(false)}>{t.cancel}</button>
          </div>
        </div>
      ) : (
        <>
          <div>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.signals}</h3>
            {a.signals.length ? (
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {a.signals.map((s, i) => (
                  <li key={`${s.code}-${i}`} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-700">
                    {t.signal[s.code] ?? s.code}{signalValue(s.value, s.unit, locale) && <> · <span className="font-mono tabular-nums">{signalValue(s.value, s.unit, locale)}</span></>}
                  </li>
                ))}
              </ul>
            ) : <p className="mt-1 text-xs text-slate-500">{t.noSignals}</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.amount}</div>
              <div className="text-base font-bold tabular-nums text-slate-900">{(a.amount_at_stake_vnd ?? fallbackAmountVnd) == null ? '—' : `${(a.amount_at_stake_vnd ?? fallbackAmountVnd as number).toLocaleString(locale === 'vi' ? 'vi-VN' : 'en-US')} ₫`}</div>
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.confidence}</div>
              <div className="flex items-center gap-2">
                <div role="progressbar" aria-label={t.confidence} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-xs font-semibold tabular-nums text-slate-900">{pct}%</span>
              </div>
            </div>
          </div>
          <div>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.rationale}</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{a.rationale}</p>
          </div>
          {canWrite && (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} className={data.persisted ? btnSecondary : btnPrimary} onClick={() => void run(() => generateCaseMotivation(caseId))}>{busy ? t.working : data.persisted ? t.regenerate : t.generate}</button>
              <button type="button" disabled={busy} className={btnSecondary} onClick={startEdit}>{t.edit}</button>
              {data.persisted && a.status === 'draft' && (
                <button type="button" disabled={busy} className={btnPrimary} onClick={() => void run(() => confirmCaseMotivation(caseId, a.version))}>{t.confirm}</button>
              )}
            </div>
          )}
        </>
      )}
      {error && <p role="alert" className="text-xs text-gs-red">{error}</p>}
    </div>
  );
}
