"use client";

import React, { useState } from 'react';
import type { CaseDetailResponse, DisputeDossierResponse, PreliminaryJudgmentChoice, PrecedentSimilarityMatch, WorkflowTrace } from '@/types/schemas';
import { useLocale } from '@/lib/locale';
import { CaseLevelFacts } from '@/components/cockpit/case-facts';
import { workspaceMessages } from '@/lib/workspace-messages';
import { savedWorkspaceJudgment, workspaceMotivation } from '@/lib/workspace-data';
import { WorkflowTab } from './workflow-tab';
import { BadgeCheck, BookOpen, Bot, BrainCircuit, Gavel, Handshake, Info, ListChecks, Tags, ThumbsUp } from 'lucide-react';
import { IconTile } from '@/components/cockpit/icon-tile';

type Decision = 'Dismiss' | 'Request' | 'Approve';
interface FinalizationTabProps {
  caseDetail: CaseDetailResponse;
  workflow?: WorkflowTrace | null;
  isActive: boolean;
  canWrite: boolean;
  busy: boolean;
  choice: PreliminaryJudgmentChoice | '';
  onChoice: (choice: PreliminaryJudgmentChoice) => void;
  note: string;
  onNote: (note: string) => void;
  savingJudgment: boolean;
  onSaveJudgment: () => void;
  rationale: string;
  onRationale: (rationale: string) => void;
  onDecision: (action: Decision, rationale: string) => void;
  delta: string;
  disputeDossier?: DisputeDossierResponse | null;
  isApplyingPrecedent?: boolean;
  onApplyPrecedent?: (precedent: PrecedentSimilarityMatch) => void;
  onClaim?: () => void;
  canClaim?: boolean;
  claimBusy?: boolean;
}
export function FinalizationTab(props: FinalizationTabProps) {
  const { locale } = useLocale();
  const m = workspaceMessages[locale];
  const [formOpen, setFormOpen] = useState(false);
  const [motivation, setMotivation] = useState('');
  const [willingness, setWillingness] = useState('');
  const [notes, setNotes] = useState('');
  const judgment = savedWorkspaceJudgment(props.caseDetail);
  const revealed = Boolean(judgment && props.isActive);
  const modelMotivation = workspaceMotivation(props.caseDetail);
  const judgmentLabel = judgment?.judgment === 'Nghi ngờ vi phạm' ? m.suspected : judgment?.judgment === 'Nghi oan-bất khả kháng' ? m.noFraud : judgment?.judgment === 'Chưa đủ cơ sở' ? m.needEvidence : judgment?.judgment;
  const suggestion = props.caseDetail.adjudication?.ai_suggestion;
  const category = suggestion?.category ?? props.caseDetail.assessment?.category ?? props.caseDetail.case.category;
  const rawConfidence = suggestion?.confidence ?? props.caseDetail.assessment?.confidence ?? props.caseDetail.case.confidence;
  const confidence = rawConfidence != null && Number.isFinite(rawConfidence) && rawConfidence >= 0 && rawConfidence <= 100
    ? Math.round(rawConfidence * (rawConfidence <= 1 ? 100 : 1))
    : null;
  const decisions: Array<[Decision, string]> = [['Approve', m.approve], ['Dismiss', m.rejectConclusion], ['Request', m.request]];
  const rationale = [props.rationale.trim(), ...(motivation.trim() ? [`${m.motivation}: ${motivation.trim()}`] : []), ...(willingness.trim() ? [`${m.willingness}: ${willingness.trim()}`] : []), ...(notes.trim() ? [`${m.notes}: ${notes.trim()}`] : [])].join('\n');
  const precedent = props.disputeDossier?.matched_precedent;
  return (
    <div role="tabpanel" id="panel-finalization" aria-labelledby="tab-finalization" hidden={!props.isActive} inert={!props.isActive} className="space-y-3 p-3 bg-slate-50/60 border-x border-b border-slate-200 rounded-b-lg text-xs">
      <CaseLevelFacts caseDetail={props.caseDetail} />
      <WorkflowTab key={props.caseDetail.case.id} caseDetail={props.caseDetail} caseWorkflowTrace={props.workflow} aiRevealed={revealed} canWrite={props.canWrite && !props.busy} />
      {revealed && (
        <section role="region" aria-label={m.judgment} className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 shadow-xs space-y-1">
          <div className="flex items-center gap-1.5 pb-0.5">
            <IconTile icon={Gavel} tone="warning" />
            <h2 className="font-semibold text-slate-900">{m.judgment}</h2>
          </div>
          <p className="font-medium text-slate-800">{judgmentLabel}</p>
          {judgment?.note && <p className="text-slate-600 text-[11px]">{m.judgmentNote}: {judgment.note}</p>}
        </section>
      )}
      {revealed && precedent && (
        <section aria-label={m.matchedPrecedent} className="rounded-md border border-gs-blue/30 bg-gs-blue-soft/60 p-2.5 shadow-xs space-y-1.5">
          <div className="flex items-center gap-1.5">
            <IconTile icon={BookOpen} tone="violet" />
            <h2 className="font-semibold text-gs-blue">{precedent.title}</h2>
          </div>
          <p className="text-[11px] text-gs-blue">{m.similarity}: {Math.round(precedent.similarity_score * (precedent.similarity_score <= 1 ? 100 : 1))}%</p>
          <p className="text-[11px] text-slate-700">{precedent.confidence_rationale}</p>
          <ul className="list-disc pl-5 text-[11px] text-slate-600">{precedent.matching_factors.map((factor) => <li key={factor}>{factor}</li>)}</ul>
          <p className="text-[11px] text-slate-700">{m.procedure}: {precedent.recommended_procedure.join(' · ') || m.unavailable}</p>
          <button type="button" disabled={!props.canWrite || props.busy || props.isApplyingPrecedent} onClick={() => props.onApplyPrecedent?.(precedent)} className="rounded border border-gs-blue bg-white px-2.5 py-1 text-xs font-medium text-gs-blue shadow-2xs hover:bg-gs-blue-soft disabled:opacity-50 transition-colors">{props.isApplyingPrecedent ? m.saving : m.applyProcedure}</button>
        </section>
      )}
      {props.isActive && !judgment && (
        <section className="rounded-lg border border-gs-amber/30 bg-gs-amber-soft/70 p-3 shadow-xs space-y-2">
          <p className="text-gs-amber-ink font-medium">{m.gateIntro}</p>
          {!formOpen ? (
            <button
              type="button"
              onClick={() => setFormOpen(true)}
              className="rounded bg-primary hover:bg-primary-container px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors"
            >
              {m.viewAI}
            </button>
          ) : (
            <>
              <div role="radiogroup" aria-label={m.judgment} className="space-y-1.5 pt-1">
                {([['Nghi ngờ vi phạm', m.suspected], ['Nghi oan-bất khả kháng', m.noFraud], ['Chưa đủ cơ sở', m.needEvidence]] as Array<[PreliminaryJudgmentChoice, string]>).map(([value, label]) => (
                  <label key={value} className="flex items-center gap-2 cursor-pointer text-slate-800">
                    <input type="radio" name="preliminary-judgment" value={value} checked={props.choice === value} onChange={() => props.onChoice(value)} disabled={props.savingJudgment || !props.canWrite} className="accent-gs-green" />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              <label className="block text-slate-700 font-medium">
                {m.judgmentNote}
                <textarea aria-label={m.judgmentNote} value={props.note} onChange={event => props.onNote(event.target.value)} disabled={props.savingJudgment || !props.canWrite} className="mt-1 min-h-16 w-full rounded-md border border-slate-300 bg-white p-2 text-xs outline-none focus:border-gs-green focus:ring-2 focus:ring-gs-green/30" rows={2} />
              </label>
              <button disabled={!props.choice || props.savingJudgment || !props.canWrite} onClick={props.onSaveJudgment} className="rounded bg-gs-amber hover:bg-gs-amber px-3 py-1.5 text-xs font-medium text-white shadow-xs disabled:opacity-40 transition-colors">{props.savingJudgment ? m.saving : m.saveJudgment}</button>
            </>
          )}
        </section>
      )}
      {revealed && (
        <>
          <section aria-label={m.aiResults} className="rounded-lg border border-gs-cyan/30 bg-gs-cyan-soft/60 p-3 shadow-xs space-y-2">
            <div className="flex items-center gap-1.5">
              <IconTile icon={Bot} tone="info" />
              <h2 className="font-semibold text-slate-900">{m.aiResults}</h2>
            </div>
            <div className="grid grid-cols-1 gap-2 text-[13px] sm:grid-cols-2">
              <div className="flex min-w-0 items-center gap-2.5 rounded-lg border border-slate-200 bg-white p-2 shadow-2xs" aria-label={locale === 'en' ? `AI advice: ${category || m.unavailable}${confidence != null ? `, ${confidence}% confidence` : ''}` : `Kết luận AI: ${category || m.unavailable}${confidence != null ? `, độ tin cậy ${confidence}%` : ''}`} title={m.classification}>
                <IconTile icon={Tags} tone="success" size="sm" />
                <span className="sr-only">{m.classification}: </span>
                <span className="truncate text-slate-800 font-medium">{category || m.unavailable}{confidence != null ? ` (${confidence}%)` : ''}</span>
              </div>
              <div className="flex min-w-0 items-center gap-2.5 rounded-lg border border-slate-200 bg-white p-2 shadow-2xs" title={`${m.confidence}: ${m.confidenceHelp}`}>
                <IconTile icon={BadgeCheck} tone="success" size="sm" />
                <span className="sr-only">{m.confidence}: </span>
                <span className="truncate text-slate-800 font-medium">{confidence == null ? m.unavailable : `${confidence}%`}</span>
              </div>
              <div className="flex min-w-0 items-center gap-2.5 rounded-lg border border-slate-200 bg-white p-2 shadow-2xs" title={`${m.reasonCodes}: ${props.caseDetail.assessment?.reason_codes?.join(', ') || m.unavailable}`}>
                <IconTile icon={ListChecks} tone="success" size="sm" />
                <span className="sr-only">{m.reasonCodes}: </span>
                <span className="truncate text-slate-800 font-medium">{props.caseDetail.assessment?.reason_codes?.join(', ') || m.unavailable}</span>
              </div>
              <div className="flex min-w-0 items-center gap-2.5 rounded-lg border border-slate-200 bg-white p-2 shadow-2xs" title={m.recommendation}>
                <IconTile icon={ThumbsUp} tone="success" size="sm" />
                <span className="sr-only">{m.recommendation}: </span>
                <span className="truncate text-slate-800 font-medium">{suggestion?.recommended_action || m.unavailable}</span>
              </div>
            </div>
            <section aria-label={`${m.motivation} ${locale === 'vi' ? 'và' : 'and'} ${m.willingness}`} className="space-y-2 rounded-md border border-gs-green/30 bg-white/90 p-2 shadow-2xs">
              <div className="flex min-w-0 items-start gap-1.5">
                <IconTile icon={BrainCircuit} tone="violet" size="sm" />
                <div className="min-w-0">
                  <h3 className="font-semibold text-slate-900">{m.motivation}</h3>
                  <p className="line-clamp-2 text-slate-700" title={modelMotivation.state === 'available' ? modelMotivation.value.natural_vietnamese_narrative : m.notAssessed}>{modelMotivation.state === 'available' ? modelMotivation.value.natural_vietnamese_narrative : m.notAssessed}</p>
                  {modelMotivation.state === 'available' && <p className="font-semibold tabular-nums text-gs-green-ink mt-0.5">{m.economicIncentive}: {modelMotivation.value.economic_incentive_reward.toLocaleString(locale === 'vi' ? 'vi-VN' : 'en-US')} ₫</p>}
                </div>
              </div>
              <div className="flex min-w-0 items-start gap-1.5 border-t border-gs-green/30 pt-2">
                <IconTile icon={Handshake} tone="warning" size="sm" />
                <div className="min-w-0">
                  <h3 className="font-semibold text-slate-900">{m.willingness}</h3>
                  <p className="text-slate-700">{m.unknown}</p>
                </div>
              </div>
            </section>
            {modelMotivation.state === 'available' && <p className="text-[10px] text-slate-500">{m.modelEstimate} · {m.source}: {modelMotivation.source}</p>}
          </section>
          <section role="region" aria-label={m.counterargument} className="rounded-md border border-slate-200 bg-slate-50/70 p-2.5 shadow-xs">
            <span className="text-slate-800">{m.counterargumentText}</span>
            {props.delta ? (
              <span className="ml-1 text-slate-600 font-medium">
                {props.delta === 'match' ? m.deltaMatch : props.delta === 'mismatch' ? m.deltaMismatch : props.delta}
              </span>
            ) : null}
          </section>
        </>
      )}
      <fieldset disabled={!props.canWrite || props.busy} className="space-y-2.5 rounded-lg border border-slate-200 bg-white p-3 shadow-xs">
        <legend className="rounded-md bg-gs-blue-soft px-2 py-1 font-semibold text-gs-blue">{m.finalization}</legend>
        <label className="block text-slate-700 font-medium">
          {m.behavior}
          <textarea aria-label={m.rationale} placeholder={m.rationalePlaceholder} value={props.rationale} onChange={event => props.onRationale(event.target.value)} className="mt-1 min-h-16 w-full rounded-md border border-slate-300 p-2 text-xs outline-none focus:border-gs-green focus:ring-2 focus:ring-gs-green/30" rows={2} />
        </label>
        <section aria-label={`${m.motivation} ${locale === 'vi' ? 'và' : 'and'} ${m.willingness}`} className="space-y-2 rounded-md border border-slate-200 bg-slate-50/60 p-2.5">
          <label className="block text-slate-700 font-medium">
            {m.motivation}
            <textarea aria-label={m.motivation} placeholder={m.notAssessed} value={motivation} onChange={event => setMotivation(event.target.value)} className="mt-1 min-h-16 w-full rounded-md border border-slate-300 bg-white p-2 text-xs outline-none focus:border-gs-green focus:ring-2 focus:ring-gs-green/30" rows={2} />
          </label>
          <label className="block border-t border-slate-200 pt-2 text-slate-700 font-medium">
            {m.willingness}
            <textarea aria-label={m.willingness} placeholder={m.unknown} value={willingness} onChange={event => setWillingness(event.target.value)} className="mt-1 min-h-16 w-full rounded-md border border-slate-300 bg-white p-2 text-xs outline-none focus:border-gs-green focus:ring-2 focus:ring-gs-green/30" rows={2} />
          </label>
        </section>
        <label className="block text-slate-700 font-medium">
          {m.notes}
          <textarea aria-label={m.notes} value={notes} onChange={event => setNotes(event.target.value)} className="mt-1 min-h-16 w-full rounded-md border border-slate-300 p-2 text-xs outline-none focus:border-gs-green focus:ring-2 focus:ring-gs-green/30" rows={1} />
        </label>
        <p className="flex items-center gap-1 text-[10px] text-slate-500" title={m.sourceOnly}>
          <Info aria-hidden="true" size={13} className="block shrink-0 text-slate-400" />
          <span>{m.sourceOnly}</span>
        </p>
        {props.rationale.trim().length < 10 && <p className="text-gs-amber-ink text-[11px]">{m.rationaleMinimum}</p>}
        {!judgment && (
          <div className="flex items-center gap-2 text-gs-amber-ink text-[11px] font-medium">
            <p role="status" aria-label={m.judgmentRequired}>
              {m.judgmentRequired}
            </p>
            {!formOpen && (
              <button
                type="button"
                onClick={() => setFormOpen(true)}
                className="underline font-semibold hover:text-gs-amber-ink focus-visible:outline-gs-green"
              >
                {m.saveJudgment}
              </button>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          {decisions.map(([action, label]) => {
            const isBlockedByJudgment = action !== 'Request' && !judgment;
            const isBlockedByRationale = props.rationale.trim().length < 10;
            const disabledReason = !props.canWrite
              ? m.leaseRequired
              : isBlockedByJudgment
                ? m.judgmentRequired
                : isBlockedByRationale
                  ? m.rationaleMinimum
                  : undefined;
            return (
              <button
                key={action}
                type="button"
                disabled={isBlockedByRationale || props.busy || !props.canWrite || isBlockedByJudgment}
                onClick={() => props.onDecision(action, rationale)}
                title={disabledReason}
                aria-description={disabledReason}
                className="rounded border border-gs-green bg-white hover:bg-gs-green-soft px-3 py-1.5 text-xs font-medium text-gs-green-ink shadow-2xs disabled:opacity-40 transition-colors"
              >
                {props.busy ? m.saving : label}
              </button>
            );
          })}
        </div>
      </fieldset>
      {!props.canWrite && (
        <div className="flex items-center justify-between rounded-md border border-gs-amber/30 bg-gs-amber-soft p-2 text-xs">
          <p role="status" className="text-gs-amber-ink py-0.5">{m.leaseRequired}</p>
          {props.canClaim && props.onClaim && (
            <button
              type="button"
              disabled={props.claimBusy}
              onClick={props.onClaim}
              className="rounded bg-primary hover:bg-primary-container px-3 py-1 text-xs font-semibold text-white shadow-xs disabled:opacity-50 transition-colors"
            >
              {props.claimBusy ? m.claiming : m.claimCase}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
