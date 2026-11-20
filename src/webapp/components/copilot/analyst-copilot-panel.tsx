"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "ai";
import { defaultRehypePlugins } from "streamdown";
import {
  Bot as BotIcon,
  User as UserIcon,
  MessageSquare as MessageSquareIcon,
  Paperclip as PaperclipIcon,
  Send as SendIcon,
  Link as LinkIcon,
  ExternalLink as ExternalLinkIcon,
  MapPin as MapPinIcon,
  CheckCircle2 as CheckCircle2Icon,
  AlertCircle as AlertCircleIcon,
  ChevronDown as ChevronDownIcon,
  BookOpen as BookOpenIcon,
  X as XIcon,
} from "lucide-react";

import { CaseCopilotTransport } from "@/lib/copilot/transport";
import { getToolLabel } from "@/lib/copilot/tool-labels";
import { mapAgentSessionToUIMessages } from "@/lib/copilot/history";
import { parseEntityHref } from "@/lib/copilot/entity-links";
import {
  getAgentContext,
  clearAgentContext,
  type AgentContextResponse,
} from "@/lib/copilot/context-api";
import {
  fetchAgentSession,
  fetchDriverScorecard,
} from "@/lib/api-client";
import type { DriverScorecardResponse } from "@/types/schemas";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/locale";

import { Conversation } from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { Response } from "@/components/ai-elements/response";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputAttachments,
  PromptInputAttachment,
  usePromptInputAttachments,
} from "@/components/ai-elements/prompt-input";
import {
  Context,
  ContextTrigger,
  ContextContent,
  ContextContentHeader,
  ContextContentBody,
} from "@/components/ai-elements/context";
import { Suggestions, Suggestion } from "@/components/ai-elements/suggestion";
import {
  Sources,
  SourcesTrigger,
  SourcesContent,
} from "@/components/ai-elements/sources";
import { Loader } from "@/components/ai-elements/loader";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { Button } from "@/components/ui/button";
import { InputGroupAddon } from "@/components/ui/input-group";

export interface AnalystCopilotPanelProps {
  caseId: string;
  isLockedByMe: boolean;
  placeholder?: string;
  onSelectCase?: (caseId: string) => void;
  onOpenTrip?: (tripId: string) => void;
  activeTab?: "copilot" | "relay";
  onTabChange?: (tab: "copilot" | "relay") => void;
  driverTabContent?: React.ReactNode;
  onTurnIdChange?: (turnId: string | null) => void;
  className?: string;
}

interface CitationItem {
  id: string;
  source: string;
  section: string;
  content: string;
  score: number | null;
}

// Custom rehype plugins to allow custom link protocols in Streamdown
const defaultSanitize = defaultRehypePlugins.sanitize as unknown as [any, any];
const defaultHarden = defaultRehypePlugins.harden as unknown as [any, any];

const customSanitize: any = [
  defaultSanitize[0],
  {
    ...defaultSanitize[1],
    protocols: {
      ...defaultSanitize[1]?.protocols,
      href: [
        ...(defaultSanitize[1]?.protocols?.href || []),
        "case",
        "driver",
        "trip",
        "policy",
      ],
    },
  },
];

const customHarden: any = [
  defaultHarden[0],
  {
    ...defaultHarden[1],
    allowedProtocols: [
      "case:",
      "driver:",
      "trip:",
      "policy:",
      "https:",
      "http:",
    ],
    allowedLinkPrefixes: ["*"],
  },
];

const copilotRehypePlugins: any = [
  defaultRehypePlugins.raw,
  customSanitize,
  customHarden,
];

function AttachmentTrigger({ disabled }: { disabled?: boolean }) {
  const { openFileDialog } = usePromptInputAttachments();
  const { locale } = useLocale();
  const label = locale === "vi" ? "Đính kèm hình ảnh" : "Attach image";
  return (
    <Button
      type="button"
      size="icon-sm"
      variant="ghost"
      disabled={disabled}
      onClick={() => openFileDialog()}
      title={label}
      aria-label={label}
      className="size-8 shrink-0 text-slate-500 hover:text-slate-800 disabled:opacity-40 cursor-pointer"
    >
      <PaperclipIcon className="h-4 w-4" />
    </Button>
  );
}

type ToolTrace = {
  toolName: string;
  toolCallId: string;
  state: "running" | "completed" | "failed";
  output?: unknown;
  args?: unknown;
  errorText?: string;
  durationMs?: number;
};

const TRAFFIC_POLICY_GUIDANCE =
  "Đối chiếu thêm chứng cứ theo Điều 12.2; không tự động kết luận gian lận hoặc miễn trừ. Chuyên viên quyết định.";

function formatTrafficEvidence(tool: ToolTrace, vi: boolean): Array<{ label: string; value: string }> {
  if (!tool.output || typeof tool.output !== "object") return [];
  const raw = tool.output as Record<string, unknown>;
  const output = (raw.result && typeof raw.result === "object" ? raw.result : raw) as Record<string, unknown>;
  const label = (vietnamese: string, english: string) => vi ? vietnamese : english;
  const yesNo = (value: unknown) => (value === true ? label("Có", "Yes") : label("Không", "No"));
  const rows: Array<{ label: string; value: string }> = [];

  if (tool.toolName === "fetch_corridor_historical_traffic") {
    if (typeof output.source_type === "string") rows.push({ label: label("Nguồn", "Source"), value: output.source_type });
    if (typeof output.peer_count === "number") rows.push({ label: label("Đối chứng", "Peers"), value: `${output.peer_count} ${label("chuyến đối chứng", "peer trips")}` });
    if (typeof output.window_start === "string" && typeof output.window_end === "string") {
      rows.push({ label: label("Cửa sổ", "Window"), value: `${output.window_start} - ${output.window_end}` });
    }
    if (typeof output.observed_speed_kmh === "number") rows.push({ label: label("Tốc độ quan sát", "Observed speed"), value: `${output.observed_speed_kmh} km/h` });
    if (typeof output.free_flow_speed_kmh === "number") rows.push({ label: label("Baseline tự do", "Free-flow baseline"), value: `${output.free_flow_speed_kmh} km/h` });
    if (typeof output.congestion_ratio === "number") rows.push({ label: label("Tỷ lệ tắc nghẽn", "Congestion ratio"), value: `${Math.round(output.congestion_ratio * 100)}%` });
    if (typeof output.congested === "boolean") rows.push({ label: label("Tắc nghẽn", "Congestion"), value: yesNo(output.congested) });
  }

  if (tool.toolName === "query_traffic_incident_feed") {
    if (output.status === "unavailable") rows.push({ label: label("Trạng thái", "Status"), value: label("Không thể xác minh sự cố", "Incident could not be verified") });
    if (typeof output.reason === "string") rows.push({ label: label("Lý do", "Reason"), value: output.reason });
    if (typeof output.retention === "string") rows.push({ label: label("Lưu trữ", "Retention"), value: output.retention });
    if (typeof output.observed_at === "string") rows.push({ label: label("Quan sát lúc", "Observed at"), value: output.observed_at });
    if (typeof output.incident_count === "number") rows.push({ label: label("Số sự cố", "Incident count"), value: String(output.incident_count) });
    if (typeof output.congested === "boolean") rows.push({ label: label("Tắc nghẽn", "Congestion"), value: yesNo(output.congested) });
    if (output.historical_absence_proven === false) {
      rows.push({ label: label("Giới hạn", "Limitation"), value: label("Không chứng minh được vắng sự cố lịch sử", "Historical absence of incidents is not proven") });
    }
  }
  return rows;
}

function safeToolDetails(value: unknown): unknown {
  if (typeof value === "string") {
    return value
      .replace(/Bearer\s+[^\s"<>]+/gi, "Bearer [REDACTED]")
      .replace(/((?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)[^\s,;"<>]+/gi, "$1[REDACTED]");
  }
  if (Array.isArray(value)) return value.map(safeToolDetails);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
    const sensitive = /key|token|secret|password|authorization|provider_payload/i.test(key);
    return [key, sensitive ? "[REDACTED]" : safeToolDetails(item)];
  }));
}

function ToolTraceChip({ tool, vi, showEvidence = true }: { tool: ToolTrace; vi: boolean; showEvidence?: boolean }) {
  const [open, setOpen] = useState(false);
  const status = tool.state === "completed" ? (vi ? "Hoàn tất" : "done")
    : tool.state === "failed" ? (vi ? "Thất bại" : "failed") : (vi ? "Đang chạy" : "running");
  const duration = typeof tool.durationMs === "number" && Number.isFinite(tool.durationMs) && tool.durationMs >= 0
    ? `${Math.round(tool.durationMs)} ms` : (vi ? "Chưa có thời lượng" : "Duration unavailable");
  const evidence = showEvidence ? formatTrafficEvidence(tool, vi) : [];
  const detailsId = React.useId();
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white text-[11px]">
      <button type="button" aria-expanded={open} aria-controls={detailsId}
        aria-label={`${tool.toolName}, ${status}, ${duration}`}
        onClick={() => setOpen(!open)}
        className="flex w-full min-w-0 items-center gap-1.5 px-2 py-1.5 text-left text-slate-600 hover:bg-slate-50 cursor-pointer">
        {tool.state === "completed" ? <CheckCircle2Icon aria-hidden="true" className="size-3.5 shrink-0 text-gs-green-ink" />
          : tool.state === "failed" ? <AlertCircleIcon aria-hidden="true" className="size-3.5 shrink-0 text-gs-red" />
          : <Loader size={14} className="shrink-0 animate-spin text-gs-amber-ink" />}
        <span className="min-w-0 break-all font-medium">{tool.toolName}</span>
        <span className="shrink-0 text-[10px]">{status}</span>
        <span className="ml-auto text-right text-[10px] text-slate-500">{duration}</span>
        <ChevronDownIcon aria-hidden="true" className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && <div id={detailsId} className="space-y-2 border-t border-slate-100 p-2">
        <div><p className="font-medium">{vi ? "Tham số" : "Arguments"}</p>
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed">{JSON.stringify(safeToolDetails(tool.args ?? null), null, 2)}</pre></div>
        <div><p className="font-medium">{vi ? "Kết quả" : "Result"}</p>
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed">{tool.errorText ? safeToolDetails(tool.errorText) as string : JSON.stringify(safeToolDetails(tool.output ?? null), null, 2)}</pre></div>
        {evidence.length > 0 && <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 border-l border-slate-200 pl-2">
          {evidence.map(row => <React.Fragment key={row.label}><dt className="font-medium">{row.label}</dt><dd className="break-words">{row.value}</dd></React.Fragment>)}
        </dl>}
      </div>}
    </div>
  );
}

function GroupedToolsRow({ tools }: { tools: ToolTrace[] }) {
  const [open, setOpen] = useState(false);
  const detailsId = React.useId();

  return (
    <div className="my-1 rounded border border-slate-200 bg-slate-50/80">
      <div className="flex flex-wrap gap-1 border-b border-slate-100 px-2.5 py-1.5">
        {tools.map((tool) => (
          <span
            key={tool.toolCallId}
            aria-label={`Tool ${tool.toolName}, done`}
            className="inline-flex items-center gap-1 rounded border border-gs-green/30 bg-gs-green-soft px-1.5 py-0.5 text-[10px] text-gs-green-ink"
          >
            <CheckCircle2Icon aria-hidden="true" className="h-3 w-3 shrink-0" />
            {tool.toolName}
          </span>
        ))}
      </div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:text-slate-900 cursor-pointer"
      >
        <div className="flex items-center gap-1.5">
          <CheckCircle2Icon className="h-3.5 w-3.5 text-gs-green-ink shrink-0" />
          <span>Đã dùng {tools.length} công cụ</span>
        </div>
        <ChevronDownIcon
          className={cn("h-3.5 w-3.5 text-slate-400 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div id={detailsId} className="space-y-1 px-2.5 pb-2 pt-0.5 border-t border-slate-100">
          {tools.map((t, tIdx) => {
            const info = getToolLabel(t.toolName);
            const evidence = formatTrafficEvidence(t, true);
            return (
              <div key={tIdx} className="py-0.5 text-[10px] text-slate-600">
                <div className="flex items-center gap-1.5">
                  <CheckCircle2Icon className="h-3 w-3 text-gs-green-ink shrink-0" />
                  <span>{info.done}</span>
                </div>
                <ToolTraceChip tool={t} vi={true} showEvidence={false} />
                {evidence.length > 0 && (
                  <dl className="ml-4 mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 border-l border-slate-200 pl-2">
                    {evidence.map((row) => (
                      <React.Fragment key={`${row.label}-${row.value}`}>
                        <dt className="font-medium text-slate-500">{row.label}</dt>
                        <dd className="break-words text-slate-700">{row.value}</dd>
                      </React.Fragment>
                    ))}
                  </dl>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ReasoningTrace({ text, running, durationMs, vi }: { text: string; running: boolean; durationMs?: number; vi: boolean }) {
  const [open, setOpen] = useState(running);
  const [elapsedMs, setElapsedMs] = useState<number>();
  const startedAt = React.useRef<number | null>(null);
  const wasRunning = React.useRef(false);
  const id = React.useId();
  useEffect(() => {
    if (running && !wasRunning.current) {
      startedAt.current = Date.now();
      setElapsedMs(undefined);
      setOpen(true);
    } else if (!running && wasRunning.current) {
      if (startedAt.current !== null) setElapsedMs(Math.max(0, Date.now() - startedAt.current));
      startedAt.current = null;
      setOpen(false);
    }
    wasRunning.current = running;
  }, [running]);
  const duration = durationMs ?? elapsedMs;
  return <div className="rounded-lg border border-slate-200 bg-white text-[11px] text-slate-600">
    <button type="button" aria-label={vi ? "Suy nghĩ" : "Thinking"} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left cursor-pointer">
      {running ? <Loader size={14} className="animate-spin" /> : <CheckCircle2Icon aria-hidden="true" className="size-3.5 text-gs-green-ink" />}
      <span>{vi ? "Suy nghĩ" : "Thinking"}</span>
      {!running && duration !== undefined && <span className="text-slate-500">{Math.round(duration)} ms</span>}
      <ChevronDownIcon aria-hidden="true" className={cn("ml-auto size-3", open && "rotate-180")} />
    </button>
    {open && <p id={id} className="whitespace-pre-wrap break-words border-t border-slate-100 p-2">{text}</p>}
  </div>;
}

export function AnalystCopilotPanel({
  caseId,
  isLockedByMe,
  placeholder,
  onSelectCase,
  onOpenTrip,
  activeTab: controlledActiveTab,
  onTabChange: controlledOnTabChange,
  driverTabContent,
  onTurnIdChange,
  className,
}: AnalystCopilotPanelProps) {
  const { locale } = useLocale();
  const vi = locale === "vi";
  // Controlled or uncontrolled activeTab ("copilot" | "relay")
  const [internalTab, setInternalTab] = useState<"copilot" | "relay">("copilot");
  const activeTab = controlledActiveTab ?? internalTab;
  const onTabChange = controlledOnTabChange ?? setInternalTab;

  // Usage state for context ring & breakdown
  const [contextOpen, setContextOpen] = useState(false);
  const [usage, setUsage] = useState<AgentContextResponse>({
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    context_window: 128000,
    breakdown: {
      system: 0,
      dossier: 0,
      history: 0,
      tool_results: 0,
      query: 0,
    },
    turn_count: 0,
  });

  const [confirmingClear, setConfirmingClear] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Driver scorecard dialog state
  const [driverDialogOpen, setDriverDialogOpen] = useState(false);
  const [selectedDriverId, setSelectedDriverId] = useState<string | null>(null);
  const [driverScorecard, setDriverScorecard] = useState<DriverScorecardResponse | null>(null);
  const [driverLoading, setDriverLoading] = useState(false);
  const [driverError, setDriverError] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((prev) => (prev === msg ? null : prev));
    }, 2500);
  }, []);

  const transport = useMemo(() => new CaseCopilotTransport({ caseId }), [caseId]);

  const {
    messages,
    setMessages,
    sendMessage,
    status,
    error: chatError,
  } = useChat({
    id: caseId,
    transport,
  });

  // Load initial history and agent context on case change
  useEffect(() => {
    let cancelled = false;

    async function loadInitial() {
      try {
        const [sessionRes, contextRes] = await Promise.allSettled([
          fetchAgentSession(caseId),
          getAgentContext(caseId),
        ]);

        if (cancelled) return;

        if (sessionRes.status === "fulfilled" && sessionRes.value) {
          setMessages(mapAgentSessionToUIMessages(sessionRes.value));
        } else {
          setMessages([]);
        }

        if (contextRes.status === "fulfilled" && contextRes.value && contextRes.value.breakdown) {
          setUsage(contextRes.value);
        }
      } catch {
        if (!cancelled) {
          setMessages([]);
        }
      }
    }

    void loadInitial();

    return () => {
      cancelled = true;
    };
  }, [caseId, setMessages]);

  // Update usage when data-usage part is received in messages
  useEffect(() => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (!lastAssistant || !Array.isArray(lastAssistant.parts)) return;

    for (const part of lastAssistant.parts) {
      if ((part as any).type === "data-usage" && (part as any).data) {
        const data = (part as any).data;
        setUsage((prev) => ({
          ...prev,
          prompt_tokens: data.prompt_tokens ?? prev.prompt_tokens,
          completion_tokens: data.completion_tokens ?? prev.completion_tokens,
          total_tokens: data.total_tokens ?? prev.total_tokens,
          context_window: data.context_window ?? prev.context_window,
          breakdown: data.breakdown ?? prev.breakdown,
        }));
      }
    }
  }, [messages]);

  // Report latest agent turn id
  useEffect(() => {
    if (!onTurnIdChange) return;
    const latestTurn = [...messages].reverse().find((m) => {
      const turnId = (m.metadata as any)?.turn_id;
      return (
        m.role === "assistant" &&
        turnId &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(turnId)
      );
    });
    const tid = (latestTurn?.metadata as any)?.turn_id || null;
    onTurnIdChange(tid);
  }, [messages, onTurnIdChange]);

  // Handle Clear Context
  const handleClearContext = async () => {
    if (!isLockedByMe || isClearing) return;
    setIsClearing(true);
    try {
      await clearAgentContext(caseId);
      setMessages([]);
      const updated = await getAgentContext(caseId);
      setUsage(updated);
      showToast(vi ? "Đã xóa ngữ cảnh hội thoại" : "Conversation context cleared");
    } catch {
      showToast(vi ? "Lỗi khi xóa ngữ cảnh" : "Could not clear context");
    } finally {
      setIsClearing(false);
      setConfirmingClear(false);
    }
  };

  // Open Driver Scorecard Dialog
  const handleOpenDriver = useCallback(
    async (driverId: string) => {
      setSelectedDriverId(driverId);
      setDriverDialogOpen(true);
      setDriverLoading(true);
      setDriverError(null);
      setDriverScorecard(null);
      try {
        const data = await fetchDriverScorecard(driverId);
        setDriverScorecard(data);
      } catch (err) {
        setDriverError(err instanceof Error ? err.message : (vi ? "Không thể tải thẻ điểm tài xế" : "Could not load driver scorecard"));
      } finally {
        setDriverLoading(false);
      }
    },
    [vi]
  );

  // Extract suggestions from the latest assistant message
  const lastAssistantMessage = useMemo(() => {
    return [...messages].reverse().find((m) => m.role === "assistant");
  }, [messages]);

  const suggestions: Array<{ label: string; prompt: string }> = useMemo(() => {
    if (!lastAssistantMessage || !Array.isArray(lastAssistantMessage.parts)) return [];
    const part = lastAssistantMessage.parts.find((p) => (p as any).type === "data-suggestions");
    return ((part as any)?.data?.items || []).slice(0, 3);
  }, [lastAssistantMessage]);

  // Custom link renderer for markdown
  const renderLinkComponent = useCallback(
    (citations: CitationItem[]) => {
      return function CustomLink({
        href,
        children,
        title,
      }: {
        href?: string;
        children?: React.ReactNode;
        title?: string;
      }) {
        const entity = parseEntityHref(href);
        if (!entity) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gs-green-ink underline underline-offset-2 hover:text-gs-green-ink"
              title={title}
            >
              {children}
            </a>
          );
        }

        if (entity.type === "case") {
          const targetCaseId = entity.id;
          const handleClick = async (e: React.MouseEvent) => {
            e.preventDefault();
            if (e.ctrlKey || e.metaKey) {
              onSelectCase?.(targetCaseId);
              return;
            }
            try {
              if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(targetCaseId);
              } else {
                throw new Error("Clipboard API unavailable");
              }
            } catch {
              try {
                const textArea = document.createElement("textarea");
                textArea.value = targetCaseId;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand("copy");
                document.body.removeChild(textArea);
              } catch {}
            }
            showToast("Đã sao chép mã vụ việc");
          };

          return (
            <span className="inline-flex items-center gap-0.5">
              <button
                type="button"
                onClick={handleClick}
                title={targetCaseId}
                className="inline-flex items-center gap-1 font-medium text-gs-green-ink underline underline-offset-2 hover:text-gs-green-ink cursor-pointer"
              >
                <span>{children}</span>
                <LinkIcon className="inline h-3 w-3 shrink-0" />
              </button>
              {onSelectCase && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onSelectCase(targetCaseId);
                  }}
                  title={`${vi ? "Mở vụ việc" : "Open case"} ${targetCaseId}`}
                  aria-label={`${vi ? "Mở vụ việc" : "Open case"} ${targetCaseId}`}
                  className="p-0.5 text-slate-400 hover:text-slate-700 rounded cursor-pointer"
                >
                  <ExternalLinkIcon className="h-2.5 w-2.5" />
                </button>
              )}
            </span>
          );
        }

        if (entity.type === "driver") {
          const driverId = entity.id;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                void handleOpenDriver(driverId);
              }}
              title={`${vi ? "Hồ sơ tài xế" : "Driver profile"}: ${driverId}`}
              className="font-medium text-gs-green-ink underline underline-offset-2 hover:text-gs-green-ink cursor-pointer"
            >
              {children}
            </button>
          );
        }

        if (entity.type === "trip") {
          const tripId = entity.id;
          const label =
            entity.pickup && entity.dest
              ? `${entity.pickup} → ${entity.dest}`
              : String(children || `${vi ? "Chuyến đi" : "Trip"} #${tripId}`);
          return (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                onOpenTrip?.(tripId);
              }}
              title={`${vi ? "Mở chuyến đi" : "Open trip"} ${tripId}`}
              className="inline-flex items-center gap-1 rounded-full bg-gs-green-soft border border-gs-green/30 px-2 py-0.5 text-[11px] font-medium text-gs-green-ink hover:bg-gs-green-soft transition-colors cursor-pointer"
            >
              <MapPinIcon className="h-3 w-3 shrink-0 text-gs-green-ink" />
              <span>{label}</span>
            </button>
          );
        }

        if (entity.type === "policy") {
          const citationId = entity.id;
          const matching = citations.filter((c) => c.id === citationId);
          return (
            <HoverCard closeDelay={150} openDelay={100}>
              <HoverCardTrigger asChild>
                <sup className="ml-0.5 cursor-pointer rounded bg-gs-green-soft px-1 py-0.2 text-[9px] font-bold text-gs-green-ink hover:bg-gs-green/20">
                  [{children || citationId}]
                </sup>
              </HoverCardTrigger>
              <HoverCardContent className="w-80 p-3 bg-white text-xs space-y-2 shadow-lg border border-slate-200 rounded-md">
                <div className="font-semibold text-slate-800 flex items-center justify-between border-b pb-1">
                  <span>{vi ? "Quy chế trích dẫn" : "Policy citation"} [{citationId}]</span>
                </div>
                {matching.length === 0 ? (
                  <p className="text-slate-500 italic">{vi ? "Không có nội dung trích dẫn chi tiết." : "No detailed citation available."}</p>
                ) : (
                  matching.map((c, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex items-center justify-between text-[11px] text-slate-600 font-medium">
                        <span>{c.source}</span>
                        {c.section && <span className="text-gs-green-ink">{c.section}</span>}
                      </div>
                      {c.content && (
                        <blockquote className="border-l-2 border-gs-green pl-2 text-[10px] text-slate-600 italic bg-slate-50 p-1.5 rounded">
                          {c.content}
                        </blockquote>
                      )}
                    </div>
                  ))
                )}
              </HoverCardContent>
            </HoverCard>
          );
        }

        return <a href={href}>{children}</a>;
      };
    },
    [handleOpenDriver, onOpenTrip, onSelectCase, showToast, vi]
  );

  // Group tool parts and status parts within an assistant message
  const renderAssistantMessageParts = useCallback(
    (message: UIMessage) => {
      const parts = message.parts || [];
      const citations: CitationItem[] = parts
        .filter((p) => (p as any).type === "data-citation" && (p as any).data)
        .map((p) => (p as any).data as CitationItem);

      type GroupedItem =
        | { type: "reasoning"; text: string; running: boolean; durationMs?: number }
        | { type: "tool"; tool: ToolTrace }
        | { type: "text"; text: string };
      const items: GroupedItem[] = [];
      const hasReasoning = parts.some(part => {
        const value = part as unknown as Record<string, any>;
        return (value.type === "reasoning" || value.type === "reasoning-delta") && Boolean(value.text || value.delta || value.state === "streaming");
      });
      for (const [partIndex, part] of parts.entries()) {
        const record = part as unknown as Record<string, any>;
        const pType = record.type as string;
        if (pType === "data-status" || pType === "reasoning" || pType === "reasoning-delta") {
          if (pType === "data-status" && hasReasoning) continue;
          const text = pType === "data-status" ? record.data?.label ?? record.label : record.text ?? record.delta ?? "";
          if (typeof text !== "string" || (pType === "data-status" && !text.trim())) continue;
          const laterContent = parts.slice(partIndex + 1).some(next => next.type === "text" || next.type === "reasoning" || next.type === "dynamic-tool" || next.type.startsWith("tool-"));
          const running = message.id === messages.at(-1)?.id && (status === "submitted" || status === "streaming") && (pType === "reasoning" || pType === "reasoning-delta" ? record.state === "streaming" || pType === "reasoning-delta" : !laterContent);
          const startedAt = Date.parse(record.startedAt ?? record.startTime ?? "");
          const completedAt = Date.parse(record.completedAt ?? record.endTime ?? "");
          const suppliedDuration = record.providerMetadata?.copilot?.durationMs ?? record.durationMs ?? record.duration_ms ?? (Number.isFinite(startedAt) && Number.isFinite(completedAt) && completedAt >= startedAt ? completedAt - startedAt : undefined);
          const durationMs = typeof suppliedDuration === "number" && Number.isFinite(suppliedDuration) && suppliedDuration >= 0 ? suppliedDuration : undefined;
          const previous = items.at(-1);
          const previousPartType = (parts[partIndex - 1] as { type: string } | undefined)?.type;
          if (previous?.type === "reasoning" && (previousPartType === "reasoning" || previousPartType === "reasoning-delta" || previousPartType === "data-status")) {
            previous.text += `${previous.text && text ? "\n\n" : ""}${text}`;
            previous.running ||= running;
            // Status labels are not measured reasoning segments.
            previous.durationMs = previousPartType === "data-status" ? durationMs
              : previous.durationMs !== undefined && durationMs !== undefined ? previous.durationMs + durationMs : undefined;
          } else {
            items.push({ type: "reasoning", text, running, durationMs });
          }
        } else if (pType === "dynamic-tool" || pType?.startsWith("tool-")) {
          const invocation = record.toolInvocation || record;
          const state = invocation.state;
          items.push({ type: "tool", tool: {
            toolName: invocation.toolName || (pType !== "tool-invocation" && pType.startsWith("tool-") ? pType.slice(5) : (vi ? "Công cụ" : "Tool")),
            toolCallId: invocation.toolCallId || `tool-${items.length}`,
            state: state === "output-error" || state === "error" ? "failed"
              : state === "output-available" || state === "result" ? "completed" : "running",
            args: invocation.input ?? invocation.args,
            output: invocation.output ?? invocation.result,
            errorText: invocation.errorText,
            durationMs: invocation.durationMs ?? invocation.duration_ms,
          } });
        } else if (pType === "text" && record.text) {
          items.push({ type: "text", text: record.text });
        }
      }
      const completedTrafficTools = items.flatMap(item => item.type === "tool" && item.tool.state === "completed" ? [item.tool.toolName] : []);
      const renderedText = items
        .filter((item): item is Extract<GroupedItem, { type: "text" }> => item.type === "text")
        .map((item) => item.text)
        .join("\n");
      if (
        completedTrafficTools.includes("fetch_corridor_historical_traffic") &&
        completedTrafficTools.includes("query_traffic_incident_feed") &&
        !/(?:Điều|Article) 12\.2/.test(renderedText)
      ) {
        items.push({ type: "text", text: vi ? TRAFFIC_POLICY_GUIDANCE : "Cross-check further evidence under Article 12.2; do not automatically conclude fraud or an exemption. The analyst decides." });
      }

      // Group adjacent tools only, retaining their place between reasoning and answers.
      const displayItems: Array<GroupedItem | { type: "tools"; tools: ToolTrace[] }> = [];
      for (const item of items) {
        const previous = displayItems.at(-1);
        if (item.type === "tool" && item.tool.state === "completed") {
          if (previous?.type === "tools") previous.tools.push(item.tool);
          else displayItems.push({ type: "tools", tools: [item.tool] });
        } else displayItems.push(item);
      }
      return (
        <div className="space-y-1.5">
          {displayItems.map((item, idx) => {
            if (item.type === "tools") {
              return <GroupedToolsRow key={item.tools[0].toolCallId} tools={item.tools} />;
            }
            if (item.type === "tool") {
              return <ToolTraceChip key={item.tool.toolCallId} tool={item.tool} vi={vi} />;
            }
            if (item.type === "reasoning" && (item.text || item.running)) {
              return <ReasoningTrace key={idx} text={item.text} running={item.running} durationMs={item.durationMs} vi={vi} />;
            }

            if (item.type === "text") {
              return (
                <div key={idx} className="text-[11px] leading-relaxed text-slate-700">
                  <Response
                    key={locale}
                    rehypePlugins={copilotRehypePlugins}
                    components={
                      {
                        a: renderLinkComponent(citations) as any,
                        table: ({ children, ...props }: any) => (
                          <div className="my-2 overflow-x-auto rounded border border-slate-200">
                            <table className="w-full text-left text-xs [&_th]:border-b [&_th]:bg-slate-50 [&_th]:p-1.5 [&_td]:p-1.5" {...props}>
                              {children}
                            </table>
                          </div>
                        ),
                        p: ({ children, ...props }: any) => (
                          <p className="my-1.5 leading-relaxed text-[11px] text-slate-700" {...props}>
                            {children}
                          </p>
                        ),
                        inlineCode: ({ children }: any) => (
                          <code className="rounded bg-slate-200/80 px-1 py-0.5 font-mono text-[0.9em] leading-[inherit] text-slate-800 [overflow-wrap:anywhere]">{children}</code>
                        ),
                        code: ({ className, children }: any) => (
                          <pre className="my-2 max-w-full overflow-x-auto rounded-md bg-slate-900 p-2.5 text-[11px] leading-relaxed text-slate-100"><code className={cn("font-mono text-[inherit]", className)}>{children}</code></pre>
                        ),
                        ul: ({ children, ...props }: any) => <ul className="my-1.5 list-disc space-y-0.5 pl-5 text-[11px]" {...props}>{children}</ul>,
                        ol: ({ children, ...props }: any) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5 text-[11px]" {...props}>{children}</ol>,
                        li: ({ children, ...props }: any) => <li className="pl-0.5" {...props}>{children}</li>,
                      } as any
                    }
                  >
                    {item.text}
                  </Response>
                </div>
              );
            }

            return null;
          })}

          {citations.length > 0 && (
            <Sources className="mt-2 text-xs">
              <SourcesTrigger
                count={citations.length}
                aria-label={`Nguồn trích dẫn / Sources (${citations.length})`}
                className="text-slate-500 hover:text-slate-700 text-[11px] font-medium"
              >
                <span className="font-medium">Nguồn trích dẫn ({citations.length})</span>
                <ChevronDownIcon className="h-3.5 w-3.5" />
              </SourcesTrigger>
              <SourcesContent className="space-y-1.5 pt-1.5">
                {citations.map((cit, cIdx) => (
                  <div key={cIdx} className="flex items-start gap-1.5 rounded bg-slate-50 border border-slate-200 p-2 text-[10px]">
                    <BookOpenIcon className="h-3.5 w-3.5 text-gs-green-ink shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-slate-800">
                        {cit.source} {cit.section ? `• ${cit.section}` : ""}
                      </div>
                      {cit.content && <p className="text-slate-500 line-clamp-2 mt-0.5">{cit.content}</p>}
                    </div>
                  </div>
                ))}
              </SourcesContent>
            </Sources>
          )}
        </div>
      );
    },
    [renderLinkComponent, vi, locale, messages, status]
  );

  const contextPercent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(usage.total_tokens / (usage.context_window || 128000));
  const contextUsageSummary = `${contextPercent} (${usage.total_tokens.toLocaleString(locale)} / ${(usage.context_window || 128000).toLocaleString(locale)} tokens)`;

  const resolvedPlaceholder =
    placeholder ||
    (isLockedByMe
      ? (vi ? "Hỏi Trợ lý về vụ việc này…" : "Ask Agents about this case…")
      : (vi ? "Nhận vụ việc để trò chuyện với AI Copilot…" : "Claim case to chat with AI Copilot…"));

  return (
    <div data-testid="analyst-copilot-panel" className={cn("flex shrink-0 flex-col h-full min-h-0 bg-white select-none overflow-hidden lg:shrink", className)}>
      {/* Toast Notification */}
      {toastMessage && (
        <div
          role="status"
          className="absolute top-12 right-4 z-50 rounded bg-slate-900 px-3 py-1.5 text-xs text-white shadow-md transition-all animate-in fade-in"
        >
          {toastMessage}
        </div>
      )}

      {/* 1. Header (h-10): Left switcher "Analyst Copilot" | "Driver", Right context ring */}
      <div className="h-10 px-3 border-b border-slate-200 flex items-center justify-between gap-2 bg-slate-50/70 shrink-0">
        <div
          role="tablist"
          aria-label={vi ? "Bảng trợ lý" : "Agent panels"}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next =
              event.key === "Home"
                ? "copilot"
                : event.key === "End"
                ? "relay"
                : activeTab === "copilot"
                ? "relay"
                : "copilot";
            onTabChange(next);
            document
              .getElementById(`tab-${next === "copilot" ? "ai-copilot" : "driver-relay"}`)
              ?.focus();
          }}
          className="inline-flex items-center rounded-lg bg-slate-200/60 p-0.5 text-slate-600"
        >
          <button
            type="button"
            role="tab"
            id="tab-ai-copilot"
            aria-controls="panel-ai-copilot"
            aria-selected={activeTab === "copilot"}
            onClick={() => onTabChange("copilot")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all cursor-pointer",
              activeTab === "copilot"
                ? "bg-white text-slate-900 font-semibold shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            )}
          >
            <BotIcon className="h-3.5 w-3.5" />
            <span>{vi ? "Trợ lý phân tích" : "Analyst Copilot"}</span>
          </button>
          <button
            type="button"
            role="tab"
            id="tab-driver-relay"
            aria-controls="panel-driver-relay"
            aria-selected={activeTab === "relay"}
            onClick={() => onTabChange("relay")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all cursor-pointer",
              activeTab === "relay"
                ? "bg-white text-slate-900 font-semibold shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            )}
          >
            <MessageSquareIcon className="h-3.5 w-3.5" />
            <span>{vi ? "Tài xế" : "Driver"}</span>
          </button>
        </div>

        {/* Right: Context Ring Button */}
        <Context
          open={contextOpen}
          onOpenChange={setContextOpen}
          usedTokens={usage.total_tokens}
          maxTokens={usage.context_window || 128000}
        >
          <ContextTrigger>
            <Button type="button" variant="ghost"
              aria-label={`AI Copilot context usage · Mức sử dụng ngữ cảnh AI Copilot: ${contextUsageSummary}`}
              title={`${vi ? "Mức sử dụng ngữ cảnh" : "Context usage"}: ${contextUsageSummary}`}
              onClick={() => setContextOpen((prev) => !prev)}
              className="h-7 shrink-0 px-2 text-xs flex items-center gap-1.5 border border-slate-200/80 bg-white hover:bg-slate-50 cursor-pointer">
              <span>{contextPercent}</span>
              <svg aria-hidden="true" className="size-5 shrink-0 -rotate-90" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" opacity="0.2" />
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" pathLength="100" strokeDasharray="100" strokeDashoffset={100 - Math.min(100, Math.max(0, usage.total_tokens / (usage.context_window || 128000) * 100))} />
              </svg>
            </Button>
          </ContextTrigger>
          <ContextContent className="w-72 p-3 bg-white shadow-lg border border-slate-200 rounded-lg text-xs space-y-3">
            <ContextContentHeader />
            <ContextContentBody className="space-y-2 p-0">
              <div className="space-y-1.5 text-slate-600">
                <div className="flex justify-between">
                  <span>{vi ? "Hệ thống" : "System"}</span>
                  <span className="font-mono">{(usage.breakdown?.system ?? 0).toLocaleString(locale)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Hồ sơ vụ việc</span>
                  <span className="font-mono">{(usage.breakdown?.dossier ?? 0).toLocaleString(locale)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Lịch sử hội thoại</span>
                  <span className="font-mono">{(usage.breakdown?.history ?? 0).toLocaleString(locale)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Kết quả công cụ</span>
                  <span className="font-mono">{(usage.breakdown?.tool_results ?? 0).toLocaleString(locale)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Câu hỏi</span>
                  <span className="font-mono">{(usage.breakdown?.query ?? 0).toLocaleString(locale)}</span>
                </div>
              </div>

              {/* Destructive Clear Context */}
              <div className="pt-2 border-t border-slate-100">
                {confirmingClear ? (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] text-gs-red font-medium">Xác nhận xóa?</span>
                    <div className="flex gap-1.5">
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        disabled={!isLockedByMe || isClearing}
                        onClick={handleClearContext}
                        className="h-6 px-2 text-[10px]"
                      >
                        {isClearing ? "Đang xóa..." : "Xác nhận"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isClearing}
                        onClick={() => setConfirmingClear(false)}
                        className="h-6 px-2 text-[10px]"
                      >
                        {vi ? "Hủy" : "Cancel"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!isLockedByMe || isClearing}
                    onClick={() => setConfirmingClear(true)}
                    className="w-full text-gs-red hover:text-gs-red hover:bg-gs-red-soft border-gs-red/30 text-xs h-7 cursor-pointer"
                  >
                    Xóa ngữ cảnh
                  </Button>
                )}
              </div>
            </ContextContentBody>
          </ContextContent>
        </Context>
      </div>

      {/* Copilot Tab Content */}
      <div
        role="tabpanel"
        id="panel-ai-copilot"
        aria-labelledby="tab-ai-copilot"
        hidden={activeTab !== "copilot"}
        className="flex-1 min-h-0 flex flex-col"
      >
        <Conversation className="z-0 flex-1 basis-0 min-h-0 overflow-y-auto p-2.5 space-y-2.5 text-xs">
          {messages.length === 0 ? (
            <p className="py-8 text-center text-xs text-slate-400">
              {vi ? "Chưa có tin nhắn nào trong vụ việc này." : "No messages in this case yet."}
            </p>
          ) : (
            messages.map((msg) => {
              const timestamp = (msg.metadata as any)?.created_at || (msg.metadata as any)?.timestamp || (msg as any).createdAt;
              const date = timestamp ? new Date(timestamp) : null;
              const validDate = date && Number.isFinite(date.getTime()) ? date : null;
              const timeLabel = validDate?.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
              if (msg.role === "user") {
                const textPart = msg.parts?.find((p) => p.type === "text") as { text: string } | undefined;
                const fileParts = (msg.parts?.filter((p) => (p as any).type === "file" || (p as any).type === "image") || []) as Array<{
                  url?: string;
                  filename?: string;
                }>;

                return (
                  <Message key={msg.id} from="user" className="!flex !flex-row max-w-full items-start justify-end gap-2">
                    <div className="flex min-w-0 max-w-[calc(100%-2rem)] flex-col items-end gap-1">
                      <MessageContent className="w-fit !rounded-2xl !rounded-tr-md !p-3 text-white !text-white text-[11px]">
                        <span className="text-[10px] font-semibold text-white/70">{vi ? "Bạn" : "You"}</span>
                        {fileParts.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mb-1.5">
                            {fileParts.map((f, fIdx) => (
                              <div key={fIdx} className="rounded overflow-hidden border border-slate-700 max-h-36">
                                {f.url && (
                                  <img
                                    src={f.url}
                                    alt={f.filename || (vi ? "Ảnh đính kèm" : "Attached image")}
                                    className="max-h-36 w-auto object-contain rounded"
                                  />
                                )}
                                {f.filename && (
                                  <span className="block text-[9px] text-slate-400 font-mono px-1 py-0.5 truncate">
                                    {f.filename}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                        <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{textPart?.text || ""}</div>
                      </MessageContent>
                      {timeLabel && <time dateTime={validDate?.toISOString()} className="px-1 text-[9px] text-slate-400">{timeLabel}</time>}
                    </div>
                    <div aria-hidden="true" className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600"><UserIcon className="size-3.5" /></div>
                  </Message>
                );
              }

              return (
                <Message key={msg.id} from="assistant" className="!flex !flex-row max-w-full items-start gap-2">
                  <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gs-green-soft text-gs-green-ink" aria-label={vi ? "Trợ lý" : "Assistant"}><BotIcon className="h-3.5 w-3.5" /></div>
                  <div className="min-w-0 max-w-[calc(100%-2rem)] flex-1">
                    <MessageContent className="w-full rounded-2xl rounded-tl-md border border-slate-200 bg-slate-50/70 p-3 text-xs">
                      <span className="text-[10px] font-semibold text-slate-500">{vi ? "Trợ lý" : "Assistant"}</span>
                      {renderAssistantMessageParts(msg)}
                    </MessageContent>
                    {timeLabel && <time dateTime={validDate?.toISOString()} className="mt-1 block text-[9px] text-slate-400">{timeLabel}</time>}
                  </div>
                </Message>
              );
            })
          )}
          {chatError && (
            <div role="alert" className="text-xs text-gs-red py-1">
              {chatError.message || (vi ? "Lỗi xử lý yêu cầu" : "Could not process request")}
            </div>
          )}
        </Conversation>

        {/* Suggestions chips */}
        {suggestions.length > 0 && (
          <div className="relative z-10 shrink-0 px-2.5 py-1.5 border-t border-slate-100 bg-slate-50/50">
            <Suggestions className="gap-1.5">
              {suggestions.map((s, idx) => (
                <Suggestion
                  key={idx}
                  suggestion={s.label}
                  onClick={() => {
                    void sendMessage({ text: s.prompt });
                  }}
                  className="text-[11px] h-6 px-2.5 border-slate-200 hover:bg-slate-100 text-slate-700"
                >
                  {s.label}
                </Suggestion>
              ))}
            </Suggestions>
          </div>
        )}

        {/* Input area */}
        <div className="relative z-10 p-2 border-t border-slate-200 bg-white shrink-0">
          <PromptInput
            accept="image/png,image/jpeg,image/webp"
            multiple={false}
            maxFiles={3}
            maxFileSize={4 * 1024 * 1024}
            inputGroupClassName="h-auto flex-col items-stretch"
            onSubmit={(data) => {
              const text = data.text.trim();
              const files = data.files || [];
              if (!text && files.length === 0) return;
              void sendMessage({ text, files });
            }}
            className="w-full [&_[data-slot=input-group]]:h-auto [&_[data-slot=input-group]]:flex-col [&_[data-slot=input-group]]:items-stretch"
          >
            <PromptInputAttachments>
              {(file) => <PromptInputAttachment key={file.id} data={file} />}
            </PromptInputAttachments>
            <div className="flex w-full items-center">
              <InputGroupAddon align="inline-start" className="shrink-0">
                <AttachmentTrigger
                  disabled={!isLockedByMe || status === "submitted" || status === "streaming"}
                />
              </InputGroupAddon>
              <PromptInputTextarea
                placeholder={resolvedPlaceholder}
                disabled={!isLockedByMe || status === "submitted" || status === "streaming"}
                className="min-w-0 flex-1 text-xs min-h-12 max-h-28"
              />
              <InputGroupAddon align="inline-end" className="shrink-0">
                <Button
                  type="submit"
                  size="icon-sm"
                  disabled={!isLockedByMe || status === "submitted" || status === "streaming"}
                  aria-label={vi ? "Gửi tin nhắn" : "Send message"}
                  title={vi ? "Gửi tin nhắn" : "Send message"}
                  className="size-7 cursor-pointer rounded-md bg-transparent text-gs-green-ink shadow-none hover:bg-transparent hover:text-gs-green-ink disabled:opacity-40"
                >
                  <SendIcon className="h-3.5 w-3.5" />
                </Button>
              </InputGroupAddon>
            </div>
          </PromptInput>
        </div>
      </div>

      {/* Driver Relay Tab Content */}
      <div
        role="tabpanel"
        id="panel-driver-relay"
        aria-labelledby="tab-driver-relay"
        hidden={activeTab !== "relay"}
        className="flex-1 min-h-0 flex flex-col"
      >
        {driverTabContent || (
          <div className="p-4 text-center text-xs text-slate-400">
            {vi ? "Chưa có nội dung Driver Relay" : "No driver conversation yet."}
          </div>
        )}
      </div>

      {/* Driver Scorecard Dialog */}
      <Dialog open={driverDialogOpen} onOpenChange={setDriverDialogOpen}>
        <DialogContent className="max-w-md bg-white p-4">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold text-slate-900">
              {vi ? "Hồ sơ tài xế" : "Driver profile · Hồ sơ tài xế"} {selectedDriverId ? `(#${selectedDriverId})` : ""}
            </DialogTitle>
          </DialogHeader>
          {driverLoading ? (
            <div role="status" aria-label={vi ? "Đang tải thẻ điểm" : "Loading scorecard"} className="py-8 text-center text-xs text-slate-500 space-y-2">
              <Loader size={16} className="animate-spin mx-auto text-gs-green-ink" />
              <p>{vi ? "Đang tải hồ sơ tài xế..." : "Loading driver profile…"}</p>
            </div>
          ) : driverError ? (
            <div role="alert" className="py-4 text-center text-xs text-gs-red space-y-2">
              <p>{driverError}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleOpenDriver(selectedDriverId!)}
              >
                {vi ? "Thử lại" : "Retry"}
              </Button>
            </div>
          ) : driverScorecard ? (
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-2 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                <div>
                  <span className="text-[10px] text-slate-500 block">{vi ? "Tỷ lệ vi phạm (90 ngày)" : "Violation rate (90 days)"}</span>
                  <span className="font-semibold text-slate-800">{driverScorecard.violation_ratio_90d}%</span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 block">{vi ? "Điểm chuẩn (Benchmark)" : "Benchmark"}</span>
                  <span className="font-semibold text-slate-800">{driverScorecard.benchmark_violation_ratio}%</span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 block">{vi ? "Tỷ lệ xử phạt" : "Penalty rate"}</span>
                  <span className="font-semibold text-slate-800">{driverScorecard.fined_ratio}%</span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 block">{vi ? "Điểm rủi ro tái phạm" : "Repeat-offense risk"}</span>
                  <span className="font-semibold text-slate-800">{driverScorecard.repeat_offense_risk_score}/100</span>
                </div>
                <div className="col-span-2">
                  <span className="text-[10px] text-slate-500 block">{vi ? "Thâm niên hoạt động" : "Tenure"}</span>
                  <span className="font-semibold text-slate-800">{driverScorecard.tenure_months} {vi ? "tháng" : "months"}</span>
                </div>
              </div>

              <div>
                <h4 className="font-semibold text-slate-800 text-[11px] mb-1.5">{vi ? "Lịch sử sự vụ gần nhất" : "Recent incidents"}</h4>
                {driverScorecard.past_incidents && driverScorecard.past_incidents.length > 0 ? (
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {driverScorecard.past_incidents.map((inc, i) => (
                      <div key={i} className="rounded border border-slate-200 p-2 text-[10px] space-y-0.5">
                        <div className="flex justify-between font-medium text-slate-700">
                          <span>{inc.violation_type}</span>
                          <span className="text-slate-400">
                            {inc.occurred_at ? new Date(inc.occurred_at).toLocaleDateString(locale) : ""}
                          </span>
                        </div>
                        <p className="text-slate-600">{inc.investigation_finding}</p>
                        <p className="text-gs-green-ink font-medium">{inc.action_taken}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-slate-400 text-[11px] italic">{vi ? "Không có lịch sử vi phạm quá khứ." : "No previous violations."}</p>
                )}
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-xs text-slate-500">{vi ? "Không có dữ liệu thẻ điểm tài xế" : "No driver scorecard data"}</p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
