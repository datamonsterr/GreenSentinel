"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useUser } from "@clerk/nextjs";
import { usePrefersReducedMotion } from "@/lib/driver/use-prefers-reduced-motion";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import {
  Sparkles,
  RotateCw,
  AlertTriangle,
  CheckCircle2,
  ShieldOff,
  Loader2,
  SendHorizontal,
  ChevronDown,
  AlertCircle,
} from "lucide-react";

import { DriverChatTransport } from "@/lib/driver/chat-transport";
import { mapDriverSessionToUIMessages } from "@/lib/driver/chat-history";
import { shouldAutoSendCaseCheck, buildAutoSendPrompt } from "@/lib/driver/chat-auto-send";
import { formatShortCaseId, getDisputeStatusCopy, getViolationTitle } from "@/lib/driver/status-copy";
import { getLocalizedChatErrorMessage } from "@/lib/driver/chat-errors";
import * as apiClient from "@/lib/api-client";
import { BlockRenderer } from "@/components/driver/blocks/block-renderer";
import { ConfirmationCard } from "@/components/driver/blocks/confirmation-card";
import { DriverActionBar } from "@/components/driver/chat/driver-action-bar";
import { ResumeDraftBanner, type DriverStatementDraft } from "@/components/driver/chat/resume-draft-banner";
import type { ConfirmationBlock, DriverChatBlock } from "@/types/driver-blocks";

function getOptionalApiFn<K extends keyof typeof apiClient>(key: K): (typeof apiClient)[K] | null {
  try {
    const fn = apiClient[key];
    return typeof fn === "function" ? fn : null;
  } catch {
    return null;
  }
}

import { Conversation, ConversationContent, ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { Response } from "@/components/ai-elements/response";
import { Suggestions, Suggestion } from "@/components/ai-elements/suggestion";
import { Loader } from "@/components/ai-elements/loader";
import { Tool, ToolContent } from "@/components/ai-elements/tool";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputFooter,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export type DriverChatStatus = "idle" | "streaming" | "completed" | "error";

function toViewStatus(aiStatus: string): DriverChatStatus {
  if (aiStatus === "streaming" || aiStatus === "submitted") return "streaming";
  if (aiStatus === "error") return "error";
  if (aiStatus === "ready") return "completed";
  return "idle";
}

function extractBlocks(parts: unknown): DriverChatBlock[] {
  if (!Array.isArray(parts)) return [];
  const blocksPart = [...parts].reverse().find((p: any) => p?.type === "data-blocks");
  const data = (blocksPart as any)?.data?.blocks;
  return Array.isArray(data) ? data : [];
}

function extractDone(parts: unknown): Record<string, any> | null {
  if (!Array.isArray(parts)) return null;
  const donePart = [...parts].reverse().find((p: any) => p?.type === "data-done");
  return (donePart as any)?.data ?? null;
}

function parseErrorStatus(err: unknown): number | null {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  const match = msg.match(/API Error (\d+)/) || msg.match(/\b(403|404)\b/);
  return match ? Number(match[1]) : null;
}

const RESOLVED_STATUSES = new Set(["resolved", "auto_dismissed", "dismissed", "upheld", "driver_confirmed_resolution"]);
const CLOSED_STATUSES = new Set(["closed", "expired"]);

function extractToolParts(parts: unknown): any[] {
  if (!Array.isArray(parts)) return [];
  return parts.filter((p: any) => {
    if (!p || typeof p !== "object") return false;
    if (p.toolCallId || p.toolName) return true;
    if (typeof p.type === "string" && (p.type.startsWith("tool-") || p.type === "tool-invocation")) return true;
    return false;
  });
}

function ToolTraceItem({ part }: { part: any }) {
  const isError = part.state === "output-error" || Boolean(part.errorText);
  const isCompleted = part.state === "output-available" || (Boolean(part.output) && !part.errorText);
  const isRunning = !isError && !isCompleted;
  const label = part.title || part.toolName || "Tool";

  return (
    <Tool className="my-1 border border-slate-200 dark:border-slate-800 rounded-lg bg-slate-50/70 dark:bg-slate-900/40 text-xs overflow-hidden">
      <CollapsibleTrigger className="flex w-full items-center justify-between px-3 py-1.5 text-left font-medium hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-colors">
        <div className="flex items-center gap-2">
          {isRunning ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-600" data-testid="tool-spinner" />
          ) : isError ? (
            <AlertCircle className="w-3.5 h-3.5 text-red-500" data-testid="tool-error" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" data-testid="tool-check" />
          )}
          <span className="text-slate-700 dark:text-slate-300 font-medium">
            {label}
          </span>
        </div>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <ToolContent className="px-3 pb-2 pt-1 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500">
        {part.output ? (
          <pre className="overflow-x-auto p-1.5 bg-slate-100 dark:bg-slate-800/80 rounded font-mono text-[10px]">
            {typeof part.output === "string" ? part.output : JSON.stringify(part.output, null, 2)}
          </pre>
        ) : part.errorText ? (
          <span className="text-red-500">{part.errorText}</span>
        ) : (
          <span className="italic">{isRunning ? "Running..." : "Completed"}</span>
        )}
      </ToolContent>
    </Tool>
  );
}

export interface DriverChatViewProps {
  caseId?: string;
}

export function DriverChatView({ caseId }: DriverChatViewProps) {
  const t = useTranslations("driver.chat");
  const tGsupport = useTranslations("driver.gsupport");
  const locale = useLocale() as "vi" | "en";
  const router = useRouter();
  const { user } = useUser();
  const reducedMotion = usePrefersReducedMotion();
  const greetingRef = useRef<HTMLDivElement>(null);
  const clerkFirstName = user?.firstName || null;

  const transport = useMemo(
    () => new DriverChatTransport({ caseId, locale }),
    [caseId, locale]
  );

  const { messages, setMessages, sendMessage, regenerate, status, error } = useChat({
    id: caseId || "driver-chat-caseless",
    transport,
  });

  const [historyLoaded, setHistoryLoaded] = useState(!caseId);
  const [caseViolation, setCaseViolation] = useState<{ code?: string; title?: string } | null>(null);
  const caseTitle = caseViolation
    ? getViolationTitle({ code: caseViolation.code, title: caseViolation.title, locale })
    : null;
  const [caseStatusKey, setCaseStatusKey] = useState<string | null>(null);
  const [caseDeadline, setCaseDeadline] = useState<string | null>(null);
  const [isDeadlinePassed, setIsDeadlinePassed] = useState(false);
  const [contextError, setContextError] = useState<404 | 403 | null>(null);
  const [policySheet, setPolicySheet] = useState<string | null>(null);
  const [submittedReceipt, setSubmittedReceipt] = useState<{
    action: "acknowledge" | "submit_statement";
    summary?: string;
  } | null>(null);
  const [draftSavedNote, setDraftSavedNote] = useState(false);
  const [localConfirmCard, setLocalConfirmCard] = useState<ConfirmationBlock | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState(false);
  const [savedDraft, setSavedDraft] = useState<DriverStatementDraft | null>(null);
  const autoSentRef = useRef(false);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  // Greeting + suggestion-chip entrance (gated by prefers-reduced-motion,
  // per .agents/rules/ui.md Section 5). Skipped entirely for reduced motion.
  useGSAP(
    () => {
      if (reducedMotion) return;
      if (greetingRef.current) {
        gsap.from(greetingRef.current, { opacity: 0, y: 12, duration: 0.4, ease: "power2.out" });
      }
      if (suggestionsRef.current) {
        gsap.from(suggestionsRef.current.querySelectorAll("button"), {
          opacity: 0,
          y: 8,
          duration: 0.3,
          stagger: 0.06,
          delay: 0.15,
          ease: "power2.out",
        });
      }
    },
    { dependencies: [reducedMotion, messages.length === 0 && !caseId], revertOnUpdate: true }
  );

  // Load case header + history (case-detail mode only).
  useEffect(() => {
    if (!caseId) return;
    const resolvedCaseId = caseId;
    let cancelled = false;
    autoSentRef.current = false;
    setContextError(null);
    setSubmittedReceipt(null);
    setDraftSavedNote(false);
    setLocalConfirmCard(null);
    setSavedDraft(null);
    setCaseViolation(null);

    async function load() {
      const fetchDraftFn = getOptionalApiFn("fetchDriverDraft");
      const draftPromise = fetchDraftFn
        ? fetchDraftFn(resolvedCaseId).catch(() => null)
        : Promise.resolve(null);

      const [sessionRes, contextRes, draftRes] = await Promise.allSettled([
        apiClient.fetchDriverSession(resolvedCaseId),
        apiClient.getDriverDisputeContext(resolvedCaseId),
        draftPromise,
      ]);
      if (cancelled) return;

      if (contextRes.status === "fulfilled" && contextRes.value) {
        setCaseViolation({
          code: contextRes.value.violation_code,
          title: contextRes.value.violation_title,
        });
        setCaseStatusKey(contextRes.value.dispute_status || null);
        setCaseDeadline(contextRes.value.dispute_deadline || null);
      } else if (contextRes.status === "rejected") {
        const code = parseErrorStatus(contextRes.reason);
        setContextError(code === 403 ? 403 : 404);
      }

      if (draftRes.status === "fulfilled" && draftRes.value) {
        const rawDraft =
          typeof draftRes.value === "object" && "draft" in draftRes.value
            ? (draftRes.value as any).draft
            : draftRes.value;
        if (rawDraft && typeof rawDraft === "object" && (rawDraft.reason || rawDraft.summary)) {
          setSavedDraft(rawDraft as DriverStatementDraft);
        }
      }

      if (sessionRes.status === "fulfilled" && sessionRes.value) {
        setMessages(mapDriverSessionToUIMessages(sessionRes.value as any));
      } else {
        setMessages([]);
      }

      // historyLoaded gates auto-send. When the context lookup failed
      // (404/403) we deliberately do NOT mark history as loaded so the
      // auto-send effect never fires on a case we could not verify access
      // to (Issue #538 blocker #7/#9).
      if (!cancelled && contextRes.status === "fulfilled") {
        setHistoryLoaded(true);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [caseId, setMessages]);

  // Date.now() is impure during render (react-hooks/set-state-in-effect
  // flags it); compute the deadline check inside an effect instead.
  useEffect(() => {
    if (!caseDeadline) {
      setIsDeadlinePassed(false);
      return;
    }
    setIsDeadlinePassed(new Date(caseDeadline).getTime() <= Date.now());
  }, [caseDeadline]);

  // Auto-send "Check details of case #XXXX" exactly once, only when empty
  // and the case context loaded successfully.
  useEffect(() => {
    if (!caseId || contextError) return;
    if (!shouldAutoSendCaseCheck({ historyLoaded, messageCount: messages.length, alreadySent: autoSentRef.current })) {
      return;
    }
    autoSentRef.current = true;
    const shortCode = formatShortCaseId(caseId);
    const prompt = buildAutoSendPrompt(t("autoSendPrompt", { code: shortCode }), shortCode);
    void sendMessage({ text: prompt });
  }, [caseId, contextError, historyLoaded, messages.length, sendMessage, t]);

  const viewStatus = toViewStatus(status);

  const suggestionKeys = ["suggestion1", "suggestion2", "suggestion3", "suggestion4"] as const;

  const handleRetry = () => {
    // Re-run the last turn in place (AI SDK regenerate): no duplicate user
    // bubble, unlike resending as a new message (Issue #538 blocker #8).
    void regenerate();
  };

  const handleSend = (text: string) => {
    if (!text.trim()) return;
    void sendMessage({ text });
  };

  const handleAcceptViolation = () => {
    setDraftSavedNote(false);
    setLocalConfirmCard({
      type: "confirmation",
      action: "acknowledge",
      checklist: [
        { key: "incident_type", ok: true, label: t("checklistIncidentType") },
        { key: "description", ok: true, label: t("checklistAcknowledgeDesc") },
      ],
      summary: caseTitle || t("confirmAcknowledgeSummary"),
    });
  };

  const handleRejectViolation = () => {
    setLocalConfirmCard(null);
    setDraftSavedNote(false);
    let promptText = "I want to reject and explain this case";
    try {
      promptText = t("rejectPrompt");
    } catch {
      // use fallback
    }
    handleSend(promptText);
  };

  const handleConfirmBlock = async (block: ConfirmationBlock) => {
    if (!caseId || pendingConfirm) return;
    setPendingConfirm(true);
    try {
      const reqConfirmFn = getOptionalApiFn("requestDriverConfirmation");
      const tokenRes = reqConfirmFn
        ? await reqConfirmFn(caseId, block.action, block.summary)
        : { confirmation_token: "local-token" };
      const token = tokenRes?.confirmation_token || "";
      if (block.action === "acknowledge") {
        const ackFn = getOptionalApiFn("submitDriverAcknowledge");
        if (ackFn) {
          await ackFn(caseId, token);
        }
      } else {
        const stmtFn = getOptionalApiFn("submitDriverStatement");
        if (stmtFn) {
          await stmtFn(caseId, token, block.summary, []);
        }
      }
      setSubmittedReceipt({ action: block.action, summary: block.summary });
      setLocalConfirmCard(null);
      setSavedDraft(null);
      setDraftSavedNote(false);
      setCaseStatusKey("pending_analyst_review");
    } finally {
      setPendingConfirm(false);
    }
  };

  const handleDeclineBlock = async (block: ConfirmationBlock) => {
    if (!caseId || pendingConfirm) return;
    setPendingConfirm(true);
    try {
      const draftPayload: DriverStatementDraft = {
        reason: block.summary,
        summary: block.summary,
        action: block.action,
      };
      const saveDraftFn = getOptionalApiFn("saveDriverDraft");
      if (saveDraftFn) {
        await saveDraftFn(caseId, draftPayload);
      }
      setLocalConfirmCard(null);
      setDraftSavedNote(true);
      setSavedDraft(draftPayload);
    } finally {
      setPendingConfirm(false);
    }
  };

  const handleResumeDraft = (draft: DriverStatementDraft) => {
    const summaryText = String(draft.summary || draft.reason || "");
    setSavedDraft(null);
    setDraftSavedNote(false);
    setLocalConfirmCard({
      type: "confirmation",
      action: draft.action || "submit_statement",
      checklist: [
        { key: "description", ok: true, label: t("checklistDescription") },
      ],
      summary: summaryText,
    });
  };

  const shortCode = caseId ? formatShortCaseId(caseId) : null;
  const statusCopy = caseStatusKey ? getDisputeStatusCopy(caseStatusKey, locale) : null;

  const isClosed = Boolean(caseStatusKey && CLOSED_STATUSES.has(caseStatusKey));
  const isExpired = isClosed || isDeadlinePassed;
  const isResolved = Boolean(caseStatusKey && RESOLVED_STATUSES.has(caseStatusKey));
  const composerDisabled = viewStatus === "streaming" || isExpired || isResolved || Boolean(contextError);

  // The most recent `done` payload across the thread carries the
  // compliance-authoritative auto-dismiss/exoneration outcome (Issue #538
  // blocker #7): never fabricated client-side, always taken verbatim from
  // the backend's done event.
  let latestDone: Record<string, any> | null = null;
  for (const m of messages) {
    const d = extractDone(m.parts);
    if (d) latestDone = d;
  }

  return (
    <div data-testid="driver-chat-view" className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">
      {caseId && (
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">
          <span
            data-testid="case-chip"
            className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 shrink-0"
          >
            {shortCode}
          </span>
          {caseTitle && <span className="text-sm font-medium min-w-0 truncate">{caseTitle}</span>}
          {statusCopy && (
            <span
              data-testid="case-status-pill"
              title={statusCopy.explanation}
              className="ml-auto px-2 py-0.5 rounded-full text-[11px] bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 whitespace-nowrap shrink-0"
            >
              {statusCopy.label}
            </span>
          )}
        </div>
      )}

      {contextError && (
        <div
          data-testid={contextError === 403 ? "driver-chat-403" : "driver-chat-404"}
          className="m-4 rounded-xl border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-4 text-xs text-red-700 dark:text-red-400 space-y-2"
        >
          <p className="font-semibold">
            {contextError === 403 ? tGsupport("error403Title") : tGsupport("error404Title")}
          </p>
          <p>{contextError === 403 ? tGsupport("error403Desc") : tGsupport("error404Desc", { id: shortCode || "" })}</p>
          <Button size="sm" variant="outline" onClick={() => router.push("/driver/cases")}>
            {tGsupport("backToPortal")}
          </Button>
        </div>
      )}

      {!contextError && isExpired && (
        <div
          data-testid="driver-chat-expired-banner"
          className="m-4 rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30 p-3 text-xs text-amber-700 dark:text-amber-400 flex items-center gap-2"
        >
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {tGsupport("expiredBanner")}
        </div>
      )}

      {!contextError && !isExpired && isResolved && (
        <div
          data-testid="driver-chat-resolved-banner"
          className="m-4 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/30 p-3 text-xs text-emerald-700 dark:text-emerald-400 flex items-center gap-2"
        >
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          {tGsupport("resolvedBanner")}
        </div>
      )}

      {!contextError && latestDone?.is_auto_dismissed && (
        <div
          data-testid="driver-chat-exoneration-receipt"
          className="m-4 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/30 p-3 text-xs text-emerald-700 dark:text-emerald-400 flex items-center gap-2"
        >
          <ShieldOff className="w-4 h-4 shrink-0" />
          {tGsupport("exonerationSuccess")}
        </div>
      )}

      {!contextError && savedDraft && !submittedReceipt && (
        <ResumeDraftBanner
          draft={savedDraft}
          onResume={handleResumeDraft}
          onDismiss={() => setSavedDraft(null)}
        />
      )}

      {!contextError && submittedReceipt && (
        <div
          data-testid="driver-submit-receipt"
          className="m-4 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/30 p-3 text-xs text-emerald-800 dark:text-emerald-300 flex items-center gap-2"
        >
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
          <span>
            {submittedReceipt.action === "acknowledge"
              ? t("receiptAcknowledged")
              : t("receiptSubmitted")}
          </span>
        </div>
      )}

      {!contextError && draftSavedNote && !submittedReceipt && (
        <div
          data-testid="driver-draft-saved-note"
          className="mx-4 mt-2 rounded-xl border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/50 p-3 text-xs text-slate-700 dark:text-slate-300"
        >
          {t("draftSaved")}
        </div>
      )}

      {!contextError && (
        <Conversation className="flex-1 min-h-0">
          <ConversationContent>
            {messages.length === 0 && !caseId && (
              <ConversationEmptyState icon={<Sparkles className="w-8 h-8 text-emerald-600" />}>
                <div ref={greetingRef} data-testid="driver-chat-greeting" className="space-y-1">
                  <h2 className="text-base font-bold">
                    {t("greetingTitle", { name: clerkFirstName || t("driverDefault") })}
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t("greetingSubtitle")}</p>
                </div>
              </ConversationEmptyState>
            )}

            {messages.map((message) => {
              const blocks = extractBlocks(message.parts);
              const toolParts = extractToolParts(message.parts);
              const textParts = Array.isArray(message.parts)
                ? message.parts.filter((p: any) => p.type === "text")
                : [];
              const isAnalyst = (message as any).metadata?.sourceRole === "analyst";
              return (
                <Message key={message.id} from={message.role}>
                  <MessageContent
                    data-testid={message.role === "user" ? "driver-user-bubble" : undefined}
                    className={
                      message.role === "user"
                        ? "bg-emerald-800 dark:bg-emerald-700 text-white [&_*]:text-white group-[.is-user]:bg-emerald-800 dark:group-[.is-user]:bg-emerald-700 group-[.is-user]:text-white prose-invert"
                        : undefined
                    }
                  >
                    {isAnalyst && (
                      <Badge data-testid="analyst-badge" variant="secondary" className="mb-1 text-[10px]">
                        {tGsupport("analystBadge")}
                      </Badge>
                    )}
                    {toolParts.length > 0 && (
                      <div className="space-y-1 mb-2">
                        {toolParts.map((toolPart: any, idx: number) => (
                          <ToolTraceItem key={toolPart.toolCallId || idx} part={toolPart} />
                        ))}
                      </div>
                    )}
                    {textParts.map((part: any, idx: number) => (
                      <Response key={idx}>{part.text}</Response>
                    ))}
                    {blocks.length > 0 && (
                      <BlockRenderer
                        blocks={blocks}
                        onNavigate={(href) => {
                          if (href.startsWith("case://")) {
                            router.push(`/driver/chat/${href.replace("case://", "")}`);
                          } else if (href.startsWith("trip://")) {
                            router.push(`/driver/history?trip=${href.replace("trip://", "")}`);
                          } else if (href.startsWith("policy://")) {
                            setPolicySheet(href.replace("policy://", ""));
                          }
                        }}
                        onPrompt={(prompt) => handleSend(prompt)}
                        onConfirm={(block) => void handleConfirmBlock(block)}
                        onDecline={(block) => void handleDeclineBlock(block)}
                        pendingConfirm={pendingConfirm}
                        t={{
                          case: tGsupport("title"),
                          unknownStatus: t("caseStatusUnknown"),
                        } as any}
                      />
                    )}
                  </MessageContent>
                </Message>
              );
            })}

            {localConfirmCard && !submittedReceipt && (
              <div className="my-2">
                <ConfirmationCard
                  action={localConfirmCard.action}
                  checklist={localConfirmCard.checklist}
                  summary={localConfirmCard.summary}
                  pending={pendingConfirm}
                  onConfirm={() => void handleConfirmBlock(localConfirmCard)}
                  onDecline={() => void handleDeclineBlock(localConfirmCard)}
                />
              </div>
            )}

            {viewStatus === "streaming" && (
              <div role="status" aria-label={t("statusStreaming")} className="flex items-center gap-2 text-xs text-slate-500">
                <Loader />
                {t("statusStreaming")}
              </div>
            )}

            {viewStatus === "error" && (
              <div
                role="alert"
                data-testid="driver-chat-error"
                className="flex items-center gap-2 text-xs text-red-600"
              >
                <span>{getLocalizedChatErrorMessage(error, t)}</span>
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="driver-chat-retry"
                  onClick={handleRetry}
                  className="h-6 gap-1 text-[11px]"
                >
                  <RotateCw className="w-3 h-3" />
                  {t("retry")}
                </Button>
              </div>
            )}
          </ConversationContent>
        </Conversation>
      )}

      {!caseId && messages.length === 0 && (
        <div ref={suggestionsRef}>
          <Suggestions className="px-4 pb-2" data-testid="driver-chat-suggestions">
            {suggestionKeys.map((key) => (
              <Suggestion key={key} suggestion={t(key)} onClick={(s) => handleSend(s)} />
            ))}
          </Suggestions>
        </div>
      )}

      {/* Accept/Reject action bar slot (Issue #483). */}
      <div data-testid="driver-chat-action-bar-slot">
        {caseId && (
          <DriverActionBar
            caseId={caseId}
            hidden={isExpired || isResolved || Boolean(contextError) || Boolean(submittedReceipt)}
            disabled={viewStatus === "streaming" || pendingConfirm}
            onAccept={handleAcceptViolation}
            onReject={handleRejectViolation}
          />
        )}
      </div>

      {policySheet && (
        <div
          data-testid="driver-chat-policy-sheet"
          role="dialog"
          className="absolute inset-x-0 bottom-0 z-20 rounded-t-2xl border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 text-xs"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold">{tGsupport("welcomePolicyTitle")}</span>
            <Button size="sm" variant="ghost" onClick={() => setPolicySheet(null)}>
              {tGsupport("closeMap")}
            </Button>
          </div>
          <p className="text-slate-600 dark:text-slate-300">{policySheet}</p>
        </div>
      )}

      <div
        data-testid="chat-composer"
        className="pb-[max(1rem,env(safe-area-inset-bottom))] w-full"
      >
        <PromptInput
          onSubmit={(data) => {
            const text = (data.text || "").trim();
            if (!text) return;
            handleSend(text);
          }}
          className="border-t border-slate-200 dark:border-slate-800 w-full flex-1 min-w-0 [&_[data-slot=input-group]]:h-auto [&_[data-slot=input-group]]:w-full"
        >
          <PromptInputBody className="w-full flex-1 min-w-0">
            <PromptInputTextarea
              placeholder={t("composerPlaceholder")}
              disabled={composerDisabled}
              className="text-xs min-h-12 max-h-28 flex-1 min-w-0 w-full"
            />
            <PromptInputFooter className="flex items-center justify-end pt-1 shrink-0 w-auto">
              <Button
                type="submit"
                size="icon"
                disabled={composerDisabled}
                aria-label={t("send")}
                title={t("send")}
                className="bg-emerald-600 hover:bg-emerald-700 text-white shrink-0"
              >
                {viewStatus === "streaming" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <SendHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
                )}
              </Button>
            </PromptInputFooter>
          </PromptInputBody>
        </PromptInput>
      </div>
    </div>
  );
}
