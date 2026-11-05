"use client";
import React from 'react';
import { BrainCircuit, FileText, Gauge, Compass, Handshake, Hourglass, LocateOff, Map as MapIcon, MessageSquareQuote, ShieldX, Timer, TriangleAlert, Wallet, Gift, BadgeMinus, MessagesSquare, Reply, Lock, IdCard } from 'lucide-react';
import type { CaseDetailResponse, DisputeDossierResponse } from '@/types/schemas';
import type { CenterTabType } from './center-panel-tabs';
import { useLocale } from '@/lib/locale';
import { workspaceMessages } from '@/lib/workspace-messages';
import { cn } from '@/lib/utils';
import { daviScore, finite, mockLocationRatio, motivationEvidence, relayTurns, speedSeries, willingnessEvidence, willingnessMetrics, type RelayTurn } from '@/lib/cockpit-signals';
import { EmptyState } from '@/components/cockpit/empty-state';
import { MetricCard } from '@/components/cockpit/metric-card';
import { MetricGrid } from '@/components/cockpit/metric-grid';
import { SectionCard } from '@/components/cockpit/section-card';
import { TripStatusRow } from '@/components/cockpit/trip-status-row';
import { toneDot } from '@/components/cockpit/icon-tile';
import { formatClock, numberLocale } from '@/components/cockpit/messages';

export { CopyId } from '@/components/cockpit/copy-id';

type Location = { latitude: number; longitude: number; label?: string };
interface OverviewTabProps {
  caseDetail: CaseDetailResponse;
  selectedCaseId?: string;
  disputeDossier?: DisputeDossierResponse | null;
  pickupLocation?: Location;
  initialDriverLocation?: Location;
  destinationLocation?: Location;
  mapTelemetry?: Array<Record<string, unknown>>;
  isActive?: boolean;
  onTabChange?: (tab: CenterTabType) => void;
  onClaim?: () => void;
  canClaim?: boolean;
  claimBusy?: boolean;
}

const copy = {
  en: {
    abnormal: 'Abnormal signals', abnormalHint: 'Measured abnormalities in the forensic brief',
    stationary: 'Stationary duration', davi: 'DAVI heading score', daviHint: 'Range −1 to 1; lower means larger heading deviation',
    mock: 'Mock-location samples', mockHint: 'Telemetry samples reporting a mock location / samples carrying the flag',
    peak: 'Peak speed', peakHint: 'Highest speed across telemetry samples', cancelledBy: 'Cancelled by',
    briefSubtitle: 'Forensic brief · measured signals only',
    motivationBrief: 'Not assessed: no motivation assessment recorded yet.', willingnessBrief: 'Undetermined: no willingness assessment recorded yet.',
    fare: 'Fare at stake', bonus: 'Bonus at stake', penalty: 'Cancellation penalty avoided', atStake: 'Measured value at stake',
    gainHint: 'Sum of the measured fare, bonus and penalty fields on this trip',
    questions: 'Questions answered', response: 'Avg. response time', replies: 'Driver replies',
    evidence: 'Conversation evidence', noRelay: 'No agent–driver conversation recorded yet.',
    agent: 'Agent', driver: 'Driver', refs: 'Evidence',
  },
  vi: {
    abnormal: 'Tín hiệu bất thường', abnormalHint: 'Bất thường đo được trong tóm tắt bằng chứng',
    stationary: 'Thời gian đứng yên', davi: 'Điểm hướng DAVI', daviHint: 'Thang −1 đến 1; càng thấp càng lệch hướng',
    mock: 'Mẫu vị trí giả', mockHint: 'Số mẫu telemetry báo vị trí giả / số mẫu có cờ này',
    peak: 'Tốc độ cao nhất', peakHint: 'Tốc độ cao nhất trong các mẫu telemetry', cancelledBy: 'Bên huỷ',
    briefSubtitle: 'Tóm tắt bằng chứng · chỉ tín hiệu đo được',
    motivationBrief: 'Chưa đánh giá: chưa có đánh giá động cơ.', willingnessBrief: 'Chưa xác định: chưa có đánh giá ý định thực hiện.',
    fare: 'Giá cước liên quan', bonus: 'Thưởng liên quan', penalty: 'Phạt huỷ chuyến tránh được', atStake: 'Giá trị đo được liên quan',
    gainHint: 'Tổng giá cước, thưởng và phạt đo được của chuyến này',
    questions: 'Câu hỏi đã trả lời', response: 'Thời gian phản hồi TB', replies: 'Lượt trả lời của tài xế',
    evidence: 'Bằng chứng hội thoại', noRelay: 'Chưa có hội thoại giữa trợ lý và tài xế.',
    agent: 'Trợ lý', driver: 'Tài xế', refs: 'Bằng chứng',
  },
} as const;

/** @deprecated Use TripStatusRow; kept for existing imports. */
export function TripFacts({ caseDetail, onOpen }: { caseDetail: CaseDetailResponse; onOpen?: () => void }) {
  return <TripStatusRow caseDetail={caseDetail} onOpen={onOpen} />;
}

type Assessment = { brief: string | null; signal: string | null; refs: string[] };

/** Brief text, signal pill and evidence refs from a free-text or structured assessment. */
function readAssessment(value: unknown): Assessment {
  if (typeof value === 'string') return { brief: value.trim() || null, signal: null, refs: [] };
  if (!value || typeof value !== 'object') return { brief: null, signal: null, refs: [] };
  const record = value as Record<string, unknown>;
  const label = record.narrative ?? record.label ?? record.assessment ?? record.value;
  const source = typeof record.source === 'string' && !record.narrative ? ` · ${record.source}` : '';
  const signal = record.signal ?? (record.narrative ? record.status : null);
  return {
    brief: label == null ? null : `${String(label)}${source}`,
    signal: signal == null ? null : String(signal),
    refs: Array.isArray(record.evidence_refs) ? record.evidence_refs.map(String) : [],
  };
}

function Quote({ turn, labels, locale }: { turn: RelayTurn; labels: { agent: string; driver: string }; locale: 'en' | 'vi' }) {
  const time = formatClock(turn.timestamp, locale);
  return (
    <blockquote className={cn('rounded-md border-l-2 bg-slate-50 px-3 py-2', turn.role === 'driver' ? 'border-emerald-600' : 'border-sky-500')}>
      <p className="text-[11px] font-semibold text-slate-600">
        {turn.role === 'driver' ? labels.driver : labels.agent}
        {time && <> · <time dateTime={turn.timestamp ?? undefined} className="font-mono font-normal">{time}</time></>}
      </p>
      <p className="mt-0.5 whitespace-pre-wrap break-words text-[13px] italic leading-relaxed text-slate-800">“{turn.text}”</p>
    </blockquote>
  );
}

function AssessmentSection({ icon, tone, title, assessment, emptyBrief, metrics, quotes, quoteLabels, evidenceTitle, noQuotes, locale }: {
  icon: typeof BrainCircuit; tone: 'violet' | 'warning'; title: string; assessment: Assessment; emptyBrief: string;
  metrics: React.ReactNode; quotes: RelayTurn[]; quoteLabels: { agent: string; driver: string }; evidenceTitle: string; noQuotes: string; locale: 'en' | 'vi';
}) {
  return (
    <SectionCard
      icon={icon}
      tone={tone}
      title={title}
      right={assessment.signal && <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-semibold', tone === 'violet' ? 'bg-violet-50 text-violet-800' : 'bg-amber-50 text-amber-800')}>{assessment.signal}</span>}
      bodyClassName="space-y-3"
    >
      {assessment.brief
        ? <p className="text-sm leading-relaxed text-slate-700">{assessment.brief}</p>
        : <p className="text-sm text-slate-500">{emptyBrief}</p>}
      {assessment.refs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {assessment.refs.map(ref => <span key={ref} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{ref}</span>)}
        </div>
      )}
      {metrics}
      <div className="space-y-2 border-t border-slate-100 pt-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{evidenceTitle}</h3>
        {quotes.length
          ? quotes.map((turn, index) => <Quote key={`${turn.role}-${index}`} turn={turn} labels={quoteLabels} locale={locale} />)
          : <EmptyState compact icon={MessageSquareQuote} hint={noQuotes} />}
      </div>
    </SectionCard>
  );
}

export const OverviewTab: React.FC<OverviewTabProps> = ({
  caseDetail,
  disputeDossier,
  mapTelemetry,
  onTabChange,
  onClaim,
  canClaim,
  claimBusy,
}) => {
  const { locale } = useLocale();
  const m = workspaceMessages[locale];
  const t = copy[locale];
  const fmt = (value: number, digits = 0) => value.toLocaleString(numberLocale(locale), { maximumFractionDigits: digits });
  const evidence = caseDetail.cockpit_evidence;
  const trip = caseDetail.trip;
  const brief = caseDetail.forensic_brief;
  const samples = (mapTelemetry?.length ? mapTelemetry : caseDetail.telemetry_samples) as Array<Record<string, unknown>> | undefined;
  const features = (caseDetail.features ?? {}) as Record<string, unknown>;

  const abnormalities = brief?.abnormalities ?? [];
  const abnormalCount = finite(brief?.abnormality_count) ?? (brief ? abnormalities.length : null);
  const stationary = finite(features.stall_duration_s) ?? finite(caseDetail.traffic_corroboration?.suspect_driver?.stall_duration_s);
  const davi = daviScore(caseDetail, samples);
  const mock = mockLocationRatio(samples);
  const speeds = speedSeries(samples);
  const peak = speeds.length ? Math.max(...speeds.map(point => point.speed)) : null;

  const turns = relayTurns(disputeDossier);
  const willingness = willingnessMetrics(turns);
  const motivation = readAssessment(evidence?.motivation_assessment || evidence?.motivation);
  const willingnessAssessment = readAssessment(evidence?.willingness_assessment || evidence?.willingness);
  const money = (value: number | null) => value === null ? null : `${fmt(value)} ₫`;
  const fare = finite(trip?.fare_amount_vnd);
  const bonus = finite(trip?.bonus_amount_vnd);
  const penalty = finite(trip?.cancellation_penalty_vnd);
  const measuredStake = [fare, bonus, penalty].filter((value): value is number => value !== null);
  const quoteLabels = { agent: t.agent, driver: t.driver };

  return (
    <div role="tabpanel" id="panel-overview" aria-labelledby="tab-overview" className="space-y-3 rounded-b-lg border-x border-b border-slate-200 bg-slate-50/60 p-3 text-xs">
      {canClaim && onClaim && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 shadow-2xs">
          <div className="flex items-center gap-2 text-[13px] font-medium text-amber-900">
            <Lock aria-hidden="true" size={16} className="block shrink-0 text-amber-700" />
            <span>{m.leaseRequired}</span>
          </div>
          <button
            type="button"
            disabled={claimBusy}
            onClick={onClaim}
            className="shrink-0 rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-emerald-800 disabled:opacity-50"
          >
            {claimBusy ? m.claiming : m.claimCase}
          </button>
        </div>
      )}
      <TripStatusRow caseDetail={caseDetail} onOpen={() => onTabChange?.('maps')} />
      <MetricGrid>
        <MetricCard icon={TriangleAlert} label={t.abnormal} hint={t.abnormalHint} value={abnormalCount === null ? null : fmt(abnormalCount)} severity={abnormalCount ? 'warning' : undefined} />
        <MetricCard icon={Hourglass} tone="warning" label={t.stationary} value={stationary === null ? null : `${fmt(stationary)} s`} />
        <MetricCard icon={Compass} tone="violet" label={t.davi} hint={t.daviHint} value={davi === null ? null : fmt(davi, 3)} />
        <MetricCard icon={LocateOff} tone="danger" label={t.mock} hint={t.mockHint} value={mock === null ? null : `${mock.flagged} / ${mock.total}`} severity={mock?.flagged ? 'danger' : undefined} />
        <MetricCard icon={Gauge} tone="info" label={t.peak} hint={t.peakHint} value={peak === null ? null : `${fmt(peak, 1)} km/h`} />
        <MetricCard icon={ShieldX} variant="text" label={t.cancelledBy} value={trip?.cancellation_actor || null} />
      </MetricGrid>
      <SectionCard icon={FileText} tone="success" title={m.behavior} subtitle={t.briefSubtitle} aria-label={m.brief}>
        {abnormalities.length ? (
          <ol className="space-y-2">
            {abnormalities.map((item, index) => (
              <li key={`${item.code}-${index}`} className="flex items-start gap-2.5 text-[13px] leading-relaxed text-slate-800" title={item.description}>
                <span aria-hidden="true" className={cn('mt-[7px] size-2 shrink-0 rounded-full', toneDot[item.severity === 'critical' ? 'danger' : item.severity === 'warning' ? 'warning' : 'neutral'])} />
                <span className="w-5 shrink-0 font-mono text-[11px] leading-[22px] text-slate-400">{String(index + 1).padStart(2, '0')}</span>
                <span className="min-w-0">{item.label}{item.observed_value && <> · <strong className="font-semibold tabular-nums text-slate-900">{item.observed_value}</strong></>}</span>
              </li>
            ))}
          </ol>
        ) : brief?.summary_text ? (
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">{brief.summary_text}</p>
        ) : <EmptyState compact icon={FileText} hint={m.noBrief} />}
        {Boolean(brief?.evidence_sources?.length) && (
          <p className="mt-3 text-[11px] text-slate-500">{m.source}: {brief?.evidence_sources.join(', ')}</p>
        )}
      </SectionCard>
      <AssessmentSection
        icon={BrainCircuit}
        tone="violet"
        title={m.motivation}
        assessment={motivation}
        emptyBrief={t.motivationBrief}
        locale={locale}
        metrics={(
          <div className="space-y-2">
            <MetricGrid>
              <MetricCard icon={Wallet} tone="success" label={t.fare} value={money(fare)} />
              <MetricCard icon={Gift} tone="violet" label={t.bonus} value={money(bonus)} />
              <MetricCard icon={BadgeMinus} tone="warning" label={t.penalty} value={money(penalty)} />
            </MetricGrid>
            {measuredStake.length > 0 && (
              <p className="text-[13px] text-slate-600" title={t.gainHint}>
                {t.atStake}: <strong className="text-base font-bold tabular-nums text-slate-900">{money(measuredStake.reduce((sum, value) => sum + value, 0))}</strong>
              </p>
            )}
          </div>
        )}
        quotes={motivationEvidence(turns)}
        quoteLabels={quoteLabels}
        evidenceTitle={t.evidence}
        noQuotes={t.noRelay}
      />
      <AssessmentSection
        icon={Handshake}
        tone="warning"
        title={m.willingness}
        assessment={willingnessAssessment}
        emptyBrief={t.willingnessBrief}
        locale={locale}
        metrics={(
          <MetricGrid>
            <MetricCard icon={MessagesSquare} tone="info" label={t.questions} value={willingness ? `${willingness.answered} / ${willingness.questions}` : null} />
            <MetricCard icon={Timer} tone="warning" label={t.response} value={willingness?.avgResponseSeconds == null ? null : `${fmt(willingness.avgResponseSeconds)} s`} />
            <MetricCard icon={Reply} tone="success" label={t.replies} value={willingness ? fmt(willingness.driverTurns) : null} />
          </MetricGrid>
        )}
        quotes={willingnessEvidence(turns)}
        quoteLabels={quoteLabels}
        evidenceTitle={t.evidence}
        noQuotes={t.noRelay}
      />
      <div className="flex flex-wrap gap-4 pt-1">
        <button type="button" onClick={() => onTabChange?.('maps')} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-700 hover:text-emerald-800 hover:underline">
          <MapIcon aria-hidden="true" size={16} className="block" />
          <span>{m.viewMaps}</span>
        </button>
        <button type="button" onClick={() => onTabChange?.('driver')} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-700 hover:text-emerald-800 hover:underline">
          <IdCard aria-hidden="true" size={16} className="block" />
          <span>{m.viewDriver}</span>
        </button>
      </div>
    </div>
  );
};
