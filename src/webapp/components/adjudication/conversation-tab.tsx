"use client";

import React from "react";
import { History, MessagesSquare, Quote, Star } from "lucide-react";
import type { CaseDetailResponse, DisputeDossierResponse, PrecedentSimilarityMatch, WorkflowTrace } from "@/types/schemas";
import { useLocale } from "@/lib/locale";
import { tripTimeline } from "@/lib/cockpit-signals";
import { SectionCard } from "@/components/cockpit/section-card";
import { EmptyState } from "@/components/cockpit/empty-state";
import { ChatThread } from "@/components/cockpit/chat-thread";
import { EventTimeline } from "@/components/cockpit/event-timeline";
import { TripStatusRow } from "@/components/cockpit/trip-status-row";
import { DisputeFacts } from "@/components/cockpit/case-facts";

interface ConversationTabProps { caseDetail: CaseDetailResponse; disputeDossier?: DisputeDossierResponse | null; caseWorkflowTrace?: WorkflowTrace | null; activeCaseDriverName?: string; isApplyingPrecedent?: boolean; isLockedByOther?: boolean; onApplyPrecedent?: (precedent: PrecedentSimilarityMatch) => void; }
const copy = {
  en: {
    title: "Customer", customer: "Customer statement", rating: "Customer rating", noStatement: "The customer has not filed a statement for this trip.",
    turn: "turn", turns: "turns", summaryLabel: "Conversation summary",
    conversationLabel: "Driver–customer conversation", summary: "Driver: {driver} · Customer: {customer}",
    latest: "Latest", latestDriver: "Driver", latestCustomer: "Customer", timeline: "Trip status timeline", cancelled: "Cancelled", empty: "No driver/customer conversation recorded.",
  },
  vi: {
    title: "Khách hàng", customer: "Giải trình khách hàng", rating: "Điểm đánh giá khách", noStatement: "Khách hàng chưa gửi giải trình cho chuyến này.",
    turn: "lượt", turns: "lượt", summaryLabel: "Tóm tắt hội thoại",
    conversationLabel: "Hội thoại tài xế–khách hàng", summary: "Tài xế: {driver} · Khách hàng: {customer}",
    latest: "Mới nhất", latestDriver: "Tài xế", latestCustomer: "Khách hàng", timeline: "Dòng thời gian trạng thái", cancelled: "Đã huỷ", empty: "Chưa có hội thoại giữa tài xế và hành khách.",
  }
} as const;

export const ConversationTab: React.FC<ConversationTabProps> = ({ caseDetail, activeCaseDriverName = "Driver" }) => {
  const { locale } = useLocale();
  const t = copy[locale];
  const trip = caseDetail.trip;
  // Customer evidence comes only from the trip conversation. Driver Relay
  // maintains its own transcript; relay messages cannot become trip evidence.
  const messages = (Array.isArray(caseDetail.conversation) ? caseDetail.conversation : [])
    .map((message, index) => ({ message, index }))
    .sort((a, b) => {
      const left = a.message.occurred_at ? Date.parse(a.message.occurred_at) : NaN;
      const right = b.message.occurred_at ? Date.parse(b.message.occurred_at) : NaN;
      return Number.isFinite(left) && Number.isFinite(right) ? left - right : a.index - b.index;
    })
    .map(({ message }) => message);
  const driverTurns = messages.filter(message => message.role === "driver").length;
  const customerTurns = messages.filter(message => message.role === "customer").length;
  const latest = messages.at(-1);
  const statement = trip?.passenger_statement || trip?.cancellation_reason;
  const rating = trip?.passenger_rating ?? trip?.customer_rating;
  const turnLabel = messages.length === 1 ? t.turn : t.turns;
  const events = tripTimeline(caseDetail, t.cancelled);

  return (
    <div role="tabpanel" id="panel-customer" aria-labelledby="tab-customer" className="space-y-3 rounded-b-lg border-x border-b border-slate-200 bg-slate-50/60 p-3 text-xs">
      <h2 className="sr-only">{t.title}</h2>
      <TripStatusRow caseDetail={caseDetail} />
      <DisputeFacts caseDetail={caseDetail} />
      <SectionCard
        icon={Quote}
        tone="info"
        title={t.customer}
        headingLevel={3}
        right={rating != null && rating !== "" && (
          <span title={t.rating} className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[13px] font-semibold text-amber-800">
            <Star aria-hidden="true" size={14} className="block fill-amber-400 text-amber-500" />
            <span className="sr-only">{t.rating}: </span><span>{String(rating)}</span>
          </span>
        )}
      >
        {statement
          ? <p title={`${t.customer}: ${statement}`} className="whitespace-pre-wrap break-words border-l-2 border-sky-400 pl-3 text-sm italic leading-relaxed text-slate-800">{String(statement)}</p>
          : <EmptyState compact icon={Quote} hint={t.noStatement} />}
      </SectionCard>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <SectionCard
          icon={MessagesSquare}
          tone="info"
          title={t.conversationLabel}
          headingLevel={3}
          right={<span className="whitespace-nowrap text-xs text-slate-500">{messages.length} {turnLabel}</span>}
          className="h-[32rem] lg:col-span-2"
          bodyClassName="flex min-h-0 flex-1 flex-col p-0"
        >
          <p role="status" aria-label={t.summaryLabel} className="truncate border-b border-slate-100 bg-slate-50/70 px-3 py-1.5 text-[11px] text-slate-500">
            {t.summary.replace("{driver}", String(driverTurns)).replace("{customer}", String(customerTurns))}
            {latest && <> · {t.latest} ({latest.role === "driver" ? t.latestDriver : t.latestCustomer}): {latest.text.slice(0, 120)}{latest.text.length > 120 ? "…" : ""}</>}
          </p>
          <ChatThread data-testid="conversation-chat-feed" messages={messages} driverLabel={activeCaseDriverName} emptyHint={t.empty} className="flex-1" />
        </SectionCard>
        <SectionCard icon={History} tone="violet" title={t.timeline} headingLevel={3} className="h-[32rem]" bodyClassName="flex min-h-0 flex-1 flex-col p-0">
          <EventTimeline events={events} className="flex-1" />
        </SectionCard>
      </div>
    </div>
  );
};
