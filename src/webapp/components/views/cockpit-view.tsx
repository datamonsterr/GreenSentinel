"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  fetchCases,
  fetchCaseHistory,
  fetchCurrentAnalyst,
  fetchCaseDetail,
  fetchForensicBrief,
  claimCase,
  releaseCase,
  recordCaseAction,
  adjudicateCase,
  subscribeCaseStream,
  getDisputeDossier,
  delegateAnalystInquiry,
  applyPrecedentProcedure,
  getCaseWorkflowTrace,
  recordPreliminaryJudgment,
} from "@/lib/api-client";
import { CaseDetailResponse, DisputeDossierResponse, WorkflowTrace, PreliminaryJudgmentChoice, PrecedentSimilarityMatch } from "@/types/schemas";
import { CenterPanelTabs, CenterTabType } from "@/components/adjudication/center-panel-tabs";
import { useLocale } from "@/lib/locale";
import { workspaceMessages } from "@/lib/workspace-messages";
import { savedWorkspaceJudgment } from "@/lib/workspace-data";
import { CopyId } from "@/components/adjudication/overview-tab";
import { QueueFilterBar } from "@/components/cockpit/case-queue-filters";
import { caseStatusTone } from "@/lib/status-tone";
import { EMPTY_FILTERS, applyFilters, isQueueExpanded, queueText, toFetchParams, withQueueExpanded, type Availability, type QueueFilters } from "@/lib/case-queue";

import { MapsTab } from "@/components/adjudication/maps-tab";
import { FinalizationTab } from "@/components/adjudication/finalization-tab";
import { OverviewTab } from "@/components/adjudication/overview-tab";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { DriverRelayTab } from "@/components/adjudication/driver-relay-tab";
import { DriverInfoTab } from "@/components/adjudication/driver-info-tab";
import { WorkflowTab } from "@/components/adjudication/workflow-tab";
import { MapLibreView } from "@/components/map/maplibre-view";
import dynamic from "next/dynamic";
import {
  CockpitWorkspaceSkeleton,
  CockpitDetailSkeleton,
  CockpitChatSkeleton,
  Skeleton,
} from "@/components/ui/skeleton";

const AnalystCopilotPanel = dynamic(
  () =>
    import("@/components/copilot/analyst-copilot-panel").then(
      (m) => m.AnalystCopilotPanel
    ),
  {
    ssr: false,
    loading: () => <CockpitChatSkeleton asSubpanel />,
  }
);

function coordinateLocation(coordinates: unknown, label?: string) {
  if (!Array.isArray(coordinates) || coordinates.length < 2 || !coordinates.slice(0, 2).every(Number.isFinite)) return undefined;
  const [longitude, latitude] = coordinates;
  if (Math.abs(longitude) > 180 || Math.abs(latitude) > 90) return undefined;
  return { longitude, latitude, label };
}
interface RelayInquiry {
  caseId: string;
  generation: number;
  request: {
    case_id: string;
    analyst_id: string;
    instruction: string;
    turn_id: string;
  };
}

interface CaseItem {
  id: string;
  code: string;
  severity: "P0" | "P1" | "P2";
  lockedBy?: string;
  sla: string;
  driverName: string;
  plate: string;
  district: string;
  tag: string;
  tagClass?: string;
  version?: number;
  category?: string | null;
  confidence?: number | null;
  status?: string;
  assignedAnalystName?: string | null;
  preliminaryJudgment?: string | null;
  aiSuggestion?: { category?: string | null; confidence?: number | null } | null;
  delta?: string | null;
  openedAt?: string | null;
}

function preliminaryDelta(judgment: string | undefined, category: string | null | undefined): "match" | "mismatch" {
  // Match the service's exact category alignment; unknown categories remain mismatches.
  const alignedChoice: Record<string, PreliminaryJudgmentChoice> = {
    "ERR-01": "Nghi ngờ vi phạm", "ERR-02": "Nghi ngờ vi phạm", "ERR-03": "Nghi ngờ vi phạm",
    "ERR-04": "Nghi ngờ vi phạm", "ERR-05": "Nghi ngờ vi phạm", intentional_dic: "Nghi ngờ vi phạm",
    confirmed_fraud: "Nghi ngờ vi phạm", suspected_fraud: "Nghi ngờ vi phạm",
    no_violation: "Nghi oan-bất khả kháng", exonerated: "Nghi oan-bất khả kháng", force_majeure: "Nghi oan-bất khả kháng",
    insufficient_evidence: "Chưa đủ cơ sở",
  };
  return judgment && judgment === alignedChoice[category ?? ""] ? "match" : "mismatch";
}

export function CockpitWorkspaceView({ initialCaseId }: { initialCaseId?: string } = {}) {
  const { locale } = useLocale();
  const m = workspaceMessages[locale];
  const getUrlCaseId = React.useCallback(() => {
    if (initialCaseId) return initialCaseId;
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const p = params.get("caseId") || params.get("case_id");
      if (p) return p;
    }
    return "";
  }, [initialCaseId]);

  const [cases, setCases] = useState<CaseItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState(() => getUrlCaseId());
  const [clockNow, setClockNow] = useState(() => Date.now());
  useEffect(() => { const timer = window.setInterval(() => setClockNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);

  useEffect(() => {
    if (initialCaseId) {
      setSelectedCaseId(initialCaseId);
    }
  }, [initialCaseId]);
  const selectedCaseIdRef = useRef(selectedCaseId);
  const selectionVersionRef = useRef(0);
  // Keep async mutation guards current in the same render as the selection change.
  // eslint-disable-next-line react-hooks/refs
  selectedCaseIdRef.current = selectedCaseId;
  const selectCase = (caseId: string) => { selectionVersionRef.current += 1; selectedCaseIdRef.current = caseId; setSelectedCaseId(caseId); };
  const [caseDetail, setCaseDetail] = useState<CaseDetailResponse | null>(null);
  const caseDetailRef = useRef(caseDetail);
  caseDetailRef.current = caseDetail;
  const caseDetailCacheRef = useRef<Map<string, CaseDetailResponse>>(new Map());
  const [currentAnalyst, setCurrentAnalyst] = useState<{id:string; name:string; role:string} | null>(null);
  const currentAnalystRef = useRef(currentAnalyst);
  currentAnalystRef.current = currentAnalyst;
  const [loading, setLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailRevision, setDetailRevision] = useState(0);
  const [lockFilter, setLockFilter] = useState<Availability>('available');
  const [facets, setFacets] = useState<Pick<QueueFilters, 'statuses' | 'priority' | 'category' | 'assignee' | 'from' | 'to'>>({ statuses: [], priority: '', category: '', assignee: '', from: '', to: '' });
  const [queueExpanded, setQueueExpanded] = useState(() => typeof window !== 'undefined' && isQueueExpanded(window.location.search));
  const setExpanded = React.useCallback((next: boolean) => {
    setQueueExpanded(next);
    const qs = withQueueExpanded(window.location.search, next);
    window.history.replaceState(null, '', `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`);
  }, []);
  const [rationale, setRationale] = useState('');
  const [ownershipBusy, setOwnershipBusy] = useState<Record<string, 'claim' | 'release'>>({});
  const ownershipPending = useRef(new Set<string>());
  const [ownershipErrors, setOwnershipErrors] = useState<Record<string, string>>({});
  const [ownership, setOwnership] = useState<Record<string, CaseDetailResponse>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submissionRef = useRef<object | null>(null);
  const submissionGenerationRef = useRef(0);
  const [failedDecision, setFailedDecision] = useState<{
    caseId: string; selectionVersion: number; action: 'Dismiss'|'Request'|'Approve'|'Agree'|'Disagree'|'Request More Evidence'; rationale: string;
  } | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState(false);
  const [latestAgentTurnId, setLatestAgentTurnId] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  const [disputeDossier, setDisputeDossier] = useState<DisputeDossierResponse | null>(null);
  const [caseWorkflowTrace, setCaseWorkflowTrace] = useState<WorkflowTrace | null>(null);
  const [isApplyingPrecedent, setIsApplyingPrecedent] = useState(false);
  const [activeAgentTab, setActiveAgentTab] = useState<"copilot" | "relay">("copilot");
  const [relayInput, setRelayInput] = useState("");
  const [relaySending, setRelaySending] = useState(false);
  const [relayError, setRelayError] = useState<string | null>(null);
  const [relayRetryInquiry, setRelayRetryInquiry] = useState<RelayInquiry | null>(null);
  const relaySendingRef = useRef(false);
  const relayCaseGenerationRef = useRef(0);
  const dossierRequestRef = useRef(0);

  useEffect(() => {
    selectedCaseIdRef.current = selectedCaseId;
    relayCaseGenerationRef.current += 1;
    submissionRef.current = null;
    setIsSubmitting(false);
    setFailedDecision(null);
    relaySendingRef.current = false;
    setRelaySending(false);
    setRelayError(null);
    setRelayRetryInquiry(null);
    setRelayInput("");
    return () => { relayCaseGenerationRef.current += 1; };
  }, [selectedCaseId]);
  const [activeCenterTab, setActiveCenterTab] = useState<CenterTabType>("overview");
  const [searchQuery, setSearchQuery] = useState("");
  const [queueTab, setQueueTab] = useState<'active' | 'history'>('active');
  const [historyStatus, setHistoryStatus] = useState<string>('');
  const historyLimit = 20;
  const [historyOffset, setHistoryOffset] = useState<number>(0);
  const [historyTotal, setHistoryTotal] = useState<number>(0);
  const [preliminaryChoice, setPreliminaryChoice] = useState<PreliminaryJudgmentChoice | "">("");
  const [preliminaryNote, setPreliminaryNote] = useState("");
  const [preliminarySaving, setPreliminarySaving] = useState(false);
  useEffect(() => { setPreliminaryChoice(""); setPreliminaryNote(""); setLatestAgentTurnId(null); }, [selectedCaseId]);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadCases = React.useCallback(async (silent = false) => {
    if (!silent) setQueueError(null);
    try {
      if (queueTab === 'history') {
        const [res, analyst] = await Promise.all([
          fetchCaseHistory({
            search: searchQuery.trim() || undefined,
            status: historyStatus.trim() || undefined,
            limit: historyLimit,
            offset: historyOffset,
          }),
          fetchCurrentAnalyst(),
        ]);
        if (!isMountedRef.current) return false;
        setCurrentAnalyst(analyst);
        setHistoryTotal(res.total);
        const mapped: CaseItem[] = res.items.map(item => ({
          id: item.id,
          code: `#${item.id.slice(-8)}`,
          severity: (item.priority as CaseItem['severity']) || 'P1',
          sla: (item.status || 'resolved').toUpperCase(),
          driverName: item.driver_name || item.driver_id || m.unavailable,
          plate: item.vehicle_plate || '—',
          district: item.district || '—',
          tag: item.status || 'Resolved',
          category: item.category || 'Processed',
          confidence: item.confidence != null ? Math.round(item.confidence <= 1 ? item.confidence * 100 : item.confidence) : undefined,
          version: item.version,
          status: item.status,
          assignedAnalystName: item.assigned_analyst_name,
          preliminaryJudgment: item.preliminary_judgment?.judgment,
          aiSuggestion: item.ai_suggestion,
          delta: item.delta,
          openedAt: item.opened_at,
        }));
        setCases(mapped);
        setSelectedCaseId(prev => mapped.some(c => c.id === prev) ? prev : mapped[0]?.id ?? '');
        return true;
      } else {
        const [res, analyst] = await Promise.all([
          fetchCases({
            ...toFetchParams({ ...EMPTY_FILTERS, search: searchQuery, availability: lockFilter }),
            limit: 200,
          }),
          fetchCurrentAnalyst(),
        ]);
        if (!isMountedRef.current) return false;
        setCurrentAnalyst(analyst);
        let mapped: CaseItem[] = res.items.map(item => {
          const leaseExpiresAt = item.active_lease_expires_at ? Date.parse(item.active_lease_expires_at) : 0;
          const isLeaseActive = !Number.isNaN(leaseExpiresAt) && leaseExpiresAt > Date.now();
          return {
            id: item.id,
            code: `#${item.id.slice(-8)}`,
            severity: item.priority as CaseItem['severity'],
            lockedBy: isLeaseActive ? (item.active_lease_analyst_id || undefined) : undefined,
            sla: item.sla_countdown_s == null ? '—' : `${Math.floor(Math.max(0,item.sla_countdown_s)/60).toString().padStart(2,'0')}:${(Math.max(0,item.sla_countdown_s)%60).toString().padStart(2,'0')}`,
            driverName: item.driver_name || item.driver_id || m.unavailable,
            plate: item.vehicle_plate || '—',
            district: item.district || '—',
            tag: item.category || 'Review',
            category: item.category || 'Review',
            confidence: item.confidence != null ? Math.round(item.confidence <= 1 ? item.confidence * 100 : item.confidence) : undefined,
            version: item.version,
            status: item.status,
            assignedAnalystName: item.assigned_analyst_name,
            preliminaryJudgment: item.preliminary_judgment?.judgment,
            aiSuggestion: item.ai_suggestion,
            delta: item.delta,
            openedAt: item.opened_at,
          };
        });
        const targetUrlId = getUrlCaseId();
        let targetSelectedId = targetUrlId;
        if (targetUrlId && !mapped.some(c => c.id === targetUrlId)) {
          try {
            const detail = await fetchCaseDetail(targetUrlId);
            if (detail && detail.case) {
              const leaseExpiresAt = detail.active_lease?.expires_at ? Date.parse(detail.active_lease.expires_at) : 0;
              const isLeaseActive = !Number.isNaN(leaseExpiresAt) && leaseExpiresAt > Date.now();
              const injected: CaseItem = {
                id: detail.case.id,
                code: `#${detail.case.id.slice(-8)}`,
                severity: (detail.case.priority || 'P1') as CaseItem['severity'],
                lockedBy: isLeaseActive ? (detail.active_lease?.analyst_id || undefined) : undefined,
                sla: (detail.case.status || 'READY').toUpperCase(),
                driverName: detail.trip?.driver_name || detail.case.driver_name || 'Driver',
                plate: detail.trip?.vehicle_plate || detail.case.vehicle_plate || '—',
                district: detail.trip?.district || detail.case.district || '—',
                tag: detail.assessment?.category || detail.case.category || 'Review',
                category: detail.assessment?.category || detail.case.category || 'Review',
                confidence: detail.assessment?.confidence != null ? Math.round(detail.assessment.confidence <= 1 ? detail.assessment.confidence * 100 : detail.assessment.confidence) : undefined,
                version: detail.case.version,
                status: detail.case.status,
                assignedAnalystName: detail.case.assigned_analyst_name || undefined,
                openedAt: detail.case.opened_at,
              };
              mapped = [injected, ...mapped];
              targetSelectedId = detail.case.id;
            }
          } catch {
            // Target case detail not found in backend, keep default queue
          }
        }
        setCases(mapped);
        setSelectedCaseId(prev => {
          if (targetSelectedId && mapped.some(c => c.id === targetSelectedId)) return targetSelectedId;
          if (targetUrlId) return targetUrlId;
          return mapped.some(c => c.id === prev) ? prev : mapped[0]?.id ?? '';
        });
        return true;
      }
    } catch (error) {
      // A failed refresh is not evidence that the selected case disappeared.
      if (isMountedRef.current && !silent) { setQueueError(error instanceof Error ? error.message : m.queueError); }
      return false;
    } finally { if (isMountedRef.current && !silent) setLoading(false); }
  }, [queueTab, lockFilter, searchQuery, historyStatus, historyOffset, getUrlCaseId]);

  const cancelRetryRef = useRef<(() => void) | null>(null);

  const handleManualRefresh = React.useCallback(() => {
    cancelRetryRef.current?.();
    return loadCases();
  }, [loadCases]);

  useEffect(() => {
    let cancelled = false;
    let timer: NodeJS.Timeout | undefined;

    cancelRetryRef.current = () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };

    const runMountLoad = async () => {
      const backoffs = [1000, 2000, 4000];
      for (let attempt = 0; attempt <= backoffs.length; attempt++) {
        if (cancelled) break;
        const ok = await loadCases();
        if (ok || cancelled) break;
        if (attempt < backoffs.length) {
          await new Promise<void>((resolve) => {
            timer = setTimeout(resolve, backoffs[attempt]);
          });
        }
      }
    };

    void runMountLoad();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [loadCases]);

  const loadCasesRef = useRef(loadCases);
  useEffect(() => { loadCasesRef.current = loadCases; }, [loadCases]);

  // Periodic background queue synchronization for concurrent analyst sessions (Issue #144)
  useEffect(() => {
    const syncQueue = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      if (isSubmitting) return;
      await loadCasesRef.current(true);
      const currentId = selectedCaseIdRef.current;
      if (currentId) {
        fetchCaseDetail(currentId)
          .then((detail) => {
            caseDetailCacheRef.current.set(currentId, detail);
            if (isMountedRef.current && selectedCaseIdRef.current === currentId) setCaseDetail(detail);
          })
          .catch(() => {});
      }
    };

    const interval = setInterval(() => { void syncQueue(); }, 10000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void syncQueue();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [isSubmitting]);

  const refreshDossier = React.useCallback(async (isCancelled?: () => boolean) => {
    if (!selectedCaseId || typeof getDisputeDossier !== "function") return;
    const generation = relayCaseGenerationRef.current;
    const request = ++dossierRequestRef.current;
    try {
      const updated = await getDisputeDossier(selectedCaseId);
      if (isMountedRef.current && !isCancelled?.() &&
          generation === relayCaseGenerationRef.current && selectedCaseIdRef.current === selectedCaseId &&
          request === dossierRequestRef.current && updated?.case_id === selectedCaseId) {
        setDisputeDossier(updated);
        if (updated.workflow_trace) setCaseWorkflowTrace(updated.workflow_trace);
      }
    } catch {
      // Keep the last known transcript when a background refresh fails.
    }
  }, [selectedCaseId]);


  useEffect(() => {
    let current = true;
    // Retain the mounted map while fetching; the workspace hides stale detail
    // until its case identity matches the selected queue item.
    setDetailError(null); setRationale('');  setFeedbackMessage(null); setFailedDecision(null);
    if (!selectedCaseId) { setCaseDetail(null); setDetailLoading(false); return; }
    const cachedDetail = caseDetailCacheRef.current.get(selectedCaseId);
    if (cachedDetail) {
      setCaseDetail(cachedDetail);
      setDetailLoading(false);
    } else {
      setDetailLoading(true);
    }
    fetchCaseDetail(selectedCaseId)
      .then((detail) => {
        caseDetailCacheRef.current.set(selectedCaseId, detail);
        if (!current) return;
        // Publish telemetry/routes immediately. The optional forensic brief can
        // be slow (LLM fallback); awaiting it here blocks the map's first paint
        // and makes a fresh case selection miss the GIS render budget.
        setCaseDetail(detail);
        setOwnership(previous => ({ ...previous, [selectedCaseId]: detail }));
        const briefText =
          detail.forensic_brief?.summary_text || '';
        if (briefText) {
          setRationale((prev) => (prev ? prev : briefText));
        }
        if (!detail.forensic_brief && !detail.assessment?.forensic_brief) {
          void Promise.resolve().then(() => fetchForensicBrief(selectedCaseId)).then((brief) => {
            if (!current) return;
            setCaseDetail((prev) => {
              if (!prev || prev.case.id !== selectedCaseId) return prev;
              const updated = { ...prev, forensic_brief: brief };
              caseDetailCacheRef.current.set(selectedCaseId, updated);
              return updated;
            });
            const summary = brief?.summary_text || '';
            if (summary) setRationale((prev) => prev || summary);
          }).catch(() => {
            // Optional fallback if forensic-brief endpoint is not available.
          });
        }
      })
      .catch(error => {
        if (current && !caseDetailCacheRef.current.has(selectedCaseId)) {
          setDetailError(error instanceof Error ? error.message : 'Unable to load case');
        }
      })
      .finally(() => { if(current) setDetailLoading(false); });
    const unsubscribe = subscribeCaseStream(selectedCaseId, (event:any) => {
      if (!current) return;
      const isTelemetrySample = Boolean(event?.payload?.position || event?.position || event?.telemetry_sample);
      if (isTelemetrySample) {
        const sample = event.telemetry_sample || {...event.payload, position:event.position || event.payload?.position, recorded_at:event.recorded_at || event.occurred_at || event.timestamp};
        setCaseDetail(prev => prev ? {...prev,telemetry_samples:[...(prev.telemetry_samples || []),sample]} : prev);
      }
      // Intermediate pipeline progress does not change queue membership. Avoid
      // four competing queue/analyst reads while the selected map is loading.
      const intermediateProgress = ['telemetry_ingested', 'features_extracted', 'guardrails_checked'].includes(event?.status);
      if (event?.status && !intermediateProgress && !isTelemetrySample) void refreshDossier();
      if ((event?.status && !intermediateProgress) || event?.event_type?.includes('lease') || event?.event_type?.includes('claim')) void loadCasesRef.current(true);
    }, () => {});
    return () => { current = false; unsubscribe(); };
  }, [selectedCaseId, detailRevision, refreshDossier]);

  useEffect(() => {
    let active = true;
    setDisputeDossier(null);
    setCaseWorkflowTrace(null);
    if (!selectedCaseId) return;
    if (detailLoading || caseDetail?.case.id !== selectedCaseId) return;

    void refreshDossier(() => !active);

    if (typeof getCaseWorkflowTrace === "function") {
      getCaseWorkflowTrace(selectedCaseId)
        .then((trace) => {
          if (active && trace) setCaseWorkflowTrace(trace);
        })
        .catch(() => {
          if (active) setCaseWorkflowTrace(null);
        });
    }

    return () => {
      active = false;
    };
  }, [selectedCaseId, detailLoading, caseDetail?.case.id, refreshDossier]);

  const handleApplyPrecedent = async (precedent: PrecedentSimilarityMatch) => {
    if (!selectedCaseId || !caseDetail || !isLockedByMe || !savedWorkspaceJudgment(caseDetail) || isApplyingPrecedent) return;
    const targetCaseId = selectedCaseId; setIsApplyingPrecedent(true); setFailedDecision(null);
    try {
      const applied = await applyPrecedentProcedure(targetCaseId, precedent.precedent_id);
      if (selectedCaseIdRef.current === targetCaseId) { setFailedDecision(null); setRationale(applied.recommended_rationale); setFeedbackMessage(`${m.appliedPrecedent}: ${precedent.title}`); setFeedbackError(false); }
    } catch (error) { if (selectedCaseIdRef.current === targetCaseId) { setFailedDecision(null); setFeedbackError(true); setFeedbackMessage(error instanceof Error ? error.message : m.saveError); } }
    finally { setIsApplyingPrecedent(false); }
  };

  const handleRelaySend = async (retry?: RelayInquiry) => {
    const instruction = (retry?.request.instruction ?? relayInput).trim();
    if (!instruction || !selectedCaseId || relaySendingRef.current || relaySessionClosed) return;
    const generation = relayCaseGenerationRef.current;
    if (retry && (retry.caseId !== selectedCaseId || retry.generation !== generation)) return;
    const inquiry: RelayInquiry = retry ?? {
      caseId: selectedCaseId,
      generation,
      request: {
        case_id: selectedCaseId,
        analyst_id: currentAnalyst?.id || "analyst-001",
        instruction,
        turn_id: crypto.randomUUID(),
      },
    };
    const isCurrent = () => isMountedRef.current &&
      relayCaseGenerationRef.current === inquiry.generation && selectedCaseIdRef.current === inquiry.caseId;
    // A synchronous guard prevents duplicate submits before React commits.
    relaySendingRef.current = true;
    setRelaySending(true);
    setRelayError(null);
    try {
      await delegateAnalystInquiry(inquiry.caseId, inquiry.request);
      if (!isCurrent()) return;
      setRelayInput("");
      setRelayRetryInquiry(null);
      setRelayError(null);
      await refreshDossier();
    } catch (error) {
      if (!isCurrent()) return;
      setRelayError(error instanceof Error ? error.message : "Không thể gửi yêu cầu tới tài xế.");
      setRelayRetryInquiry(inquiry);
    } finally {
      if (isCurrent()) {
        relaySendingRef.current = false;
        setRelaySending(false);
      }
    }
  };

  const handleRelayRetry = () => {
    if (relayRetryInquiry) void handleRelaySend(relayRetryInquiry);
  };

  const activeCase = cases.find(item => item.id === selectedCaseId);
  const sameCaseDetail = caseDetail?.case.id === selectedCaseId ? caseDetail : null;
  const isTerminalCase = Boolean(
    sameCaseDetail?.case &&
    ["resolved", "dismissed", "auto_dismissed"].includes(sameCaseDetail?.case.status?.toLowerCase() || "")
  );
  const relaySessionClosed = Boolean(
    isTerminalCase ||
    ["resolved", "closed"].includes(sameCaseDetail?.case?.status?.toLowerCase() || "") ||
    ["resolved", "closed"].includes(disputeDossier?.dispute_status?.toLowerCase() || "")
  );
  useEffect(() => {
    if (activeAgentTab !== "relay" || !selectedCaseId || relaySessionClosed) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await refreshDossier(() => cancelled);
      if (!cancelled) timer = setTimeout(() => { void poll(); }, 10_000);
    };
    timer = setTimeout(() => { void poll(); }, 10_000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeAgentTab, selectedCaseId, relaySessionClosed, refreshDossier]);

  const lease = sameCaseDetail?.active_lease;
  const leaseAlive = Boolean(lease && (!lease.expires_at || Date.parse(lease.expires_at) > clockNow));
  const activeLockHolder = leaseAlive ? lease?.analyst_id : undefined;
  const isLeaseExpired = Boolean(lease?.expires_at && !leaseAlive);
  const isLockedByOther = Boolean(!isTerminalCase && activeLockHolder && activeLockHolder !== currentAnalyst?.id);
  const isLockedByMe = Boolean(!isTerminalCase && activeLockHolder && activeLockHolder === currentAnalyst?.id);

  useEffect(() => {
    if (!isLockedByMe || !selectedCaseId) return;

    const interval = setInterval(async () => {
      const analyst = currentAnalystRef.current;
      const currentDetail = caseDetailRef.current;
      if (!analyst || !isMountedRef.current || selectedCaseIdRef.current !== selectedCaseId) return;

      const activeLease = currentDetail?.case?.id === selectedCaseId ? currentDetail.active_lease : undefined;
      const expiresAt = activeLease?.expires_at ? Date.parse(activeLease.expires_at) : 0;
      const remainingSeconds = expiresAt ? (expiresAt - Date.now()) / 1000 : 0;

      if (remainingSeconds < 900) {
        try {
          await claimCase(selectedCaseId, {
            analyst_id: analyst.id,
            lease_duration_seconds: 1800,
          });
          const detail = await fetchCaseDetail(selectedCaseId);
          if (!isMountedRef.current || selectedCaseIdRef.current !== selectedCaseId) return;
          caseDetailCacheRef.current.set(selectedCaseId, detail);
          setCaseDetail(detail);
          setOwnership(previous => ({ ...previous, [selectedCaseId]: detail }));
        } catch {
          try {
            const detail = await fetchCaseDetail(selectedCaseId);
            if (!isMountedRef.current || selectedCaseIdRef.current !== selectedCaseId) return;
            caseDetailCacheRef.current.set(selectedCaseId, detail);
            setCaseDetail(detail);
            setOwnership(previous => ({ ...previous, [selectedCaseId]: detail }));
          } catch {
            /* Keep existing detail on refresh error */
          }
        }
      }
    }, 60000);

    return () => {
      clearInterval(interval);
    };
  }, [isLockedByMe, selectedCaseId]);

  const chatPlaceholder = !selectedCaseId
    ? "Ask Agents about this case…"
    : isTerminalCase
    ? "Case is resolved. Chat is closed."
    : isLockedByOther
    ? "Case claimed by another analyst. Claim required to chat."
    : isLeaseExpired
    ? "Review lease expired. Claim case to chat with AI Copilot…"
    : !isLockedByMe
    ? "Claim case to chat with AI Copilot…"
    : "Ask Agents about this case…";
  const updateLock = async (caseIdOrRelease: string | boolean = false, releaseArgument = false) => {
    const caseId = typeof caseIdOrRelease === 'string' ? caseIdOrRelease : selectedCaseId;
    const release = typeof caseIdOrRelease === 'boolean' ? caseIdOrRelease : releaseArgument;
    if (!currentAnalyst || !caseId || ownershipPending.current.has(caseId) || !['analyst', 'fraud_analyst', 'senior_analyst', 'admin'].includes(currentAnalyst.role.toLowerCase())) return;
    ownershipPending.current.add(caseId);
    setOwnershipErrors(previous => { const next = { ...previous }; delete next[caseId]; return next; });
    setOwnershipBusy(previous => ({ ...previous, [caseId]: release ? 'release' : 'claim' }));
    setFeedbackMessage(null); setFailedDecision(null);
    try {
      if (release) await releaseCase(caseId, { analyst_id: currentAnalyst.id });
      else await claimCase(caseId, { analyst_id: currentAnalyst.id, lease_duration_seconds: 1800 });
      const detail = await fetchCaseDetail(caseId);
      if (!isMountedRef.current) return;
      setOwnership(previous => ({ ...previous, [caseId]: detail }));
      if (selectedCaseIdRef.current === caseId) setCaseDetail(detail);
      await loadCasesRef.current(true);
    } catch (error) {
      if (!isMountedRef.current) return;
      setFeedbackError(true);
      const conflict = error instanceof Error && error.message.includes('409');
      const message = conflict ? m.conflict : `${m.claimError}${error instanceof Error ? ` (${error.message})` : ''}`;
      setOwnershipErrors(previous => ({ ...previous, [caseId]: message }));
      // A failed mutation never invents ownership. Refresh the exact card even
      // when another card was selected while the request was in flight.
      try {
        const authoritative = await fetchCaseDetail(caseId);
        if (isMountedRef.current) {
          setOwnership(previous => ({ ...previous, [caseId]: authoritative }));
          if (selectedCaseIdRef.current === caseId) setCaseDetail(authoritative);
        }
      } catch { /* Keep the previous lease until the next authoritative read. */ }
      await loadCasesRef.current(true);
    } finally {
      ownershipPending.current.delete(caseId);
      if (isMountedRef.current) setOwnershipBusy(previous => { const next = { ...previous }; delete next[caseId]; return next; });
    }
  };
  const isAnalystAuthorized = Boolean(
    currentAnalyst &&
    ['analyst', 'fraud_analyst', 'senior_analyst', 'admin'].includes(currentAnalyst.role?.toLowerCase() || '')
  );
  const canClaim = Boolean(selectedCaseId && !isLockedByMe && !isLockedByOther && !isTerminalCase && isAnalystAuthorized);
  const claimBusy = Boolean(selectedCaseId && ownershipBusy[selectedCaseId] === 'claim');
  const handleSubmitDecision = async (action:'Dismiss'|'Request'|'Approve'|'Agree'|'Disagree'|'Request More Evidence', submittedRationale = rationale) => {
    if (submissionRef.current) return;
    setFailedDecision(null);
    if (submittedRationale.trim().length < 10) {
      setFeedbackError(true);
      setFeedbackMessage(m.rationaleMinimum);

      return;
    }
    if (!currentAnalyst || !isAnalystAuthorized) {
      setFeedbackError(true);
      setFeedbackMessage(m.unauthorized);

      return;
    }
    if (isSubmitting || detailLoading || detailError || !caseDetail || caseDetail.case.id !== selectedCaseId || !isLockedByMe || isTerminalCase) return;
    if (action !== 'Request' && action !== 'Request More Evidence' && !savedWorkspaceJudgment(caseDetail)) return;
    const targetCaseId = selectedCaseId;
    const targetSelectionVersion = selectionVersionRef.current;
    const submission = {};
    submissionRef.current = submission;
    const submissionGeneration = ++submissionGenerationRef.current;
    const isCurrentSubmission = () => submissionGenerationRef.current === submissionGeneration && isMountedRef.current && selectedCaseIdRef.current === targetCaseId && selectionVersionRef.current === targetSelectionVersion;
    setIsSubmitting(true);  setFeedbackMessage(null); setFailedDecision(null); setFeedbackError(false);
    try {
      if (action === 'Request' || action === 'Request More Evidence') await recordCaseAction(targetCaseId,{action_type:'REQUEST_EVIDENCE',analyst_id:currentAnalyst.id,notes:submittedRationale});
      else {
        const adjudicationResult = await adjudicateCase(targetCaseId,{
          outcome:(action === 'Approve' || action === 'Agree') ? 'AGREE' : 'DISAGREE',
          analyst_id:currentAnalyst.id,
          rationale: submittedRationale,
          expected_case_version:caseDetail.case.version,
          ...(latestAgentTurnId ? {agent_turn_id:latestAgentTurnId} : {}),
          ...(savedWorkspaceJudgment(caseDetail)?.id ? { preliminary_judgment_id: savedWorkspaceJudgment(caseDetail)!.id } : {}),
        });
        if (isCurrentSubmission()) setCaseDetail(previous => previous?.case.id === targetCaseId ? { ...previous, adjudication: adjudicationResult } : previous);
      }
      if (!isCurrentSubmission()) return;
      setFeedbackMessage(m.saved); setRationale('');
      // The mutation is committed. Refresh failures must never invite a duplicate POST.
      void loadCases(true);
      if (action === 'Request' || action === 'Request More Evidence') {
        void fetchCaseDetail(targetCaseId).then(updated => {
          if (isCurrentSubmission()) setCaseDetail(updated);
        }).catch(() => { /* The next selection or background sync can refresh detail. */ });
      }
    } catch(error) {
      if (!isCurrentSubmission()) return;
      setFeedbackError(true);
      setFeedbackMessage((error instanceof Error || error instanceof DOMException) && error.name === 'TimeoutError' ? m.requestTimeout : error instanceof Error ? error.message : m.saveError);
      setFailedDecision({ caseId: targetCaseId, selectionVersion: targetSelectionVersion, action, rationale: submittedRationale });
      if (error instanceof Error && error.message.includes('409')) {
        fetchCaseDetail(targetCaseId).then(d => { if (isCurrentSubmission()) setCaseDetail(d); }).catch(() => {});
        void loadCases(true);
      }
    } finally {
      if (submissionRef.current === submission) {
        submissionRef.current = null;
        if (isMountedRef.current) setIsSubmitting(false);
      }
    }
  };
  const handlePreliminaryCommit = async () => {
    if (!preliminaryChoice || !currentAnalyst || !selectedCaseId || preliminarySaving || !isLockedByMe || !isAnalystAuthorized || detailLoading || !sameCaseDetail || isTerminalCase) return;
    const targetCaseId = selectedCaseId;
    const targetSelectionVersion = selectionVersionRef.current;
    setPreliminarySaving(true); setFeedbackMessage(null); setFailedDecision(null); setFeedbackError(false);
    try {
      const judgment = await recordPreliminaryJudgment(targetCaseId, { analyst_id: currentAnalyst.id, judgment: preliminaryChoice, note: preliminaryNote || undefined });
      if (judgment.case_id !== targetCaseId || selectedCaseIdRef.current !== targetCaseId || selectionVersionRef.current !== targetSelectionVersion) return;
      setCaseDetail(prev => prev && prev.case.id === targetCaseId ? { ...prev, preliminary_judgment: judgment } : prev);
    } catch (error) {
      if (selectedCaseIdRef.current !== targetCaseId || selectionVersionRef.current !== targetSelectionVersion) return;
      setFeedbackError(true); setFeedbackMessage(error instanceof Error ? error.message : m.judgmentError);
    } finally { setPreliminarySaving(false); }
  };
  const mapTelemetry = React.useMemo(() => (caseDetail?.telemetry_samples ?? [])
    .filter(sample => coordinateLocation(sample.position?.coordinates) && Number.isFinite(Date.parse(sample.recorded_at ?? sample.occurred_at)))
    .slice().sort((a,b)=>Date.parse(a.recorded_at ?? a.occurred_at)-Date.parse(b.recorded_at ?? b.occurred_at)), [caseDetail?.telemetry_samples]);
  const initialDriverLocation = coordinateLocation(mapTelemetry[0]?.position?.coordinates,'Start');
  const pickupLocation = coordinateLocation(caseDetail?.trip?.pickup?.coordinates,caseDetail?.trip?.pickup_address);
  const destinationLocation = coordinateLocation(caseDetail?.trip?.dropoff?.coordinates,caseDetail?.trip?.dropoff_address)
    ?? coordinateLocation(caseDetail?.destination && [caseDetail.destination.longitude,caseDetail.destination.latitude],caseDetail?.destination?.label);

  const qt = queueText[locale];
  const queueFilters: QueueFilters = { ...facets, search: searchQuery, availability: lockFilter };
  const visibleCases = queueTab === 'active' ? applyFilters(cases, queueFilters) : cases;
  const rowInfo = (item: CaseItem) => {
    const detail = caseDetail?.case.id === item.id ? caseDetail : ownership[item.id];
    const activeLease = detail?.active_lease;
    const alive = Boolean(activeLease && (!activeLease.expires_at || Date.parse(activeLease.expires_at) > clockNow));
    const holder = detail ? (alive ? activeLease?.analyst_id : undefined) : item.lockedBy;
    return {
      mine: Boolean(holder && holder === currentAnalyst?.id),
      other: Boolean(holder && holder !== currentAnalyst?.id),
      archived: ['resolved', 'dismissed', 'auto_dismissed'].includes(detail?.case.status || item.status || ''),
      busy: ownershipBusy[item.id],
    };
  };
  const openFromTable = (id: string) => { selectCase(id); setExpanded(false); };

  if (loading) return <WorkspaceLoading message={m.loadingWorkspace} />;
  if (queueError) return <div className="m-auto p-6 text-center space-y-3"><p role="alert" className="text-sm text-red-700">{queueError}</p><button onClick={()=>{setLoading(true);void handleManualRefresh();}} className="rounded border px-3 py-1 text-sm">{m.retry}</button></div>;
  return (
    <div className="flex-1 flex flex-col lg:flex-row h-full min-h-0 overflow-auto lg:overflow-hidden bg-slate-50 text-slate-900">
      <section aria-label={m.triage} className={`w-full min-w-0 shrink-0 ${queueExpanded ? 'lg:flex-1' : 'lg:w-[22%]'} lg:shrink-0 border-r border-slate-200 flex flex-col ${queueExpanded ? 'lg:max-h-none' : 'max-h-64'} lg:max-h-none lg:h-full min-h-0 bg-white`}>
        <div className="h-10 px-2.5 border-b flex items-center justify-between gap-1 shrink-0 bg-white">
          <div className="flex items-center gap-1">
            <button
              type="button"
              role="tab"
              aria-selected={queueTab === 'active'}
              aria-label={m.activeQueue}
              onClick={() => { setQueueTab('active'); setHistoryOffset(0); }}
              className={`text-xs font-semibold px-2 py-1 rounded transition-colors ${
                queueTab === 'active' ? 'bg-slate-200 text-slate-900 font-bold' : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {m.active} <span className="text-[11px] font-normal text-slate-500">{queueTab === 'active' ? `(${visibleCases.length})` : ''}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={queueTab === 'history'}
              aria-label={m.historyQueue}
              onClick={() => { setQueueTab('history'); setHistoryOffset(0); }}
              className={`text-xs font-semibold px-2 py-1 rounded transition-colors ${
                queueTab === 'history' ? 'bg-slate-200 text-slate-900 font-bold' : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {m.history} <span className="text-[11px] font-normal text-slate-500">{queueTab === 'history' ? `(${historyTotal})` : ''}</span>
            </button>
          </div>
          <div className="flex items-center gap-0.5">
            <button aria-label={m.refresh} onClick={()=>void handleManualRefresh()} className="p-1 rounded hover:bg-slate-100"><span aria-hidden="true" className="material-symbols-outlined text-base">sync</span></button>
            <button
              type="button"
              aria-label={queueExpanded ? qt.collapse : qt.expand}
              aria-expanded={queueExpanded}
              title={queueExpanded ? qt.collapse : qt.expand}
              onClick={() => setExpanded(!queueExpanded)}
              className="rounded px-1.5 py-0.5 text-sm font-bold text-cyan-700 hover:bg-cyan-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-600"
            >{queueExpanded ? '<<' : '>>'}</button>
          </div>
        </div>
        <div className={`p-2 border-b shrink-0 bg-slate-50/50 ${queueExpanded ? 'flex flex-wrap items-start gap-2' : 'space-y-1.5'}`}>
          <div className={`relative flex items-center ${queueExpanded ? 'w-64' : ''}`}>
            <input
              type="text"
              aria-label={m.search}
              placeholder={m.searchPlaceholder}
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); setHistoryOffset(0); }}
              className="h-8 w-full rounded-md border border-slate-300 bg-white pl-8 pr-8 text-xs shadow-none outline-none placeholder:text-slate-400 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
            />
            <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-sm leading-none text-slate-400">
              search
            </span>
            {searchQuery && (
              <button
                type="button"
                aria-label={m.clearSearch}
                onClick={() => { setSearchQuery(""); setHistoryOffset(0); }}
                className="absolute right-1.5 p-0.5 text-slate-400 hover:text-slate-600 rounded"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-sm">close</span>
              </button>
            )}
          </div>
          {queueTab === 'active' ? (
            <select
              aria-label={m.lockFilter}
              value={lockFilter}
              onChange={e => setLockFilter(e.target.value as Availability)}
              className={`h-8 ${queueExpanded ? 'w-48' : 'w-full'} rounded-md border border-slate-300 bg-white px-2.5 text-xs text-slate-700 shadow-none outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100`}
            >
              <option value="available">{m.availableCases}</option>
              <option value="mine">{m.mine}</option>
              <option value="all">{qt.allCases}</option>
            </select>
          ) : (
            <select
              aria-label={m.historyFilter}
              value={historyStatus}
              onChange={e => { setHistoryStatus(e.target.value); setHistoryOffset(0); }}
              className="h-8 w-full rounded-md border border-slate-300 bg-white px-2.5 text-xs text-slate-700 shadow-none outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
            >
              <option value="">{m.allProcessed}</option>
              <option value="resolved">{m.resolved}</option>
              <option value="dismissed">{m.dismissed}</option>
              <option value="auto_dismissed">{m.autoDismissed}</option>
            </select>
          )}
          {queueTab === 'active' && <div className={queueExpanded ? 'min-w-0 flex-1' : ''}>
            <QueueFilterBar filters={queueFilters} onChange={next => setFacets({ statuses: next.statuses, priority: next.priority, category: next.category, assignee: next.assignee, from: next.from, to: next.to })} rows={cases} locale={locale} expanded={queueExpanded} />
          </div>}
        </div>
        {queueExpanded ? (
          <div className="relative flex-1 overflow-auto">
            {!visibleCases.length ? <p className="py-6 text-center text-xs text-slate-500">{searchQuery ? m.noSearch : queueTab === 'history' ? m.noHistory : m.noCases}</p> : (
            <table className="w-full min-w-[56rem] border-collapse text-left text-xs">
              <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>{[qt.id, qt.driver, qt.plate, qt.category, qt.status, qt.priority, qt.assignee, qt.opened, 'SLA', qt.action].map(h => <th key={h} scope="col" className="border-b px-3 py-2 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody>
                {visibleCases.map(item => {
                  const { mine, other, archived, busy } = rowInfo(item);
                  return (
                    <tr key={item.id} onClick={(e) => { if (!(e.target as HTMLElement).closest('button')) openFromTable(item.id); }} className={`cursor-pointer border-b border-slate-100 hover:bg-cyan-50/50 ${item.id === selectedCaseId ? 'bg-cyan-50/70' : ''}`}>
                      <td className="px-3 py-2 font-mono text-[11px]">{item.code}</td>
                      <td className="px-3 py-2">
                        <button type="button" aria-label={`${item.severity} · ${item.code} ${item.driverName} ${item.plate}`} onClick={() => openFromTable(item.id)} className="max-w-[12rem] truncate text-left font-medium hover:underline focus-visible:outline-cyan-700">{item.driverName}</button>
                      </td>
                      <td className="px-3 py-2 text-slate-600">{item.plate}</td>
                      <td className="px-3 py-2 text-slate-600">{item.category || '—'}</td>
                      <td className="px-3 py-2">{item.status ? <span className={`gs-tone pill ${caseStatusTone(item.status)}`}>{qt[item.status] ?? item.status}</span> : '—'}</td>
                      <td className="px-3 py-2"><span className={`gs-tone pill ${item.severity === 'P0' ? 't-red' : item.severity === 'P1' ? 't-amber' : 't-blue'}`}>{item.severity}</span></td>
                      <td className="px-3 py-2 text-slate-600">{item.assignedAnalystName || qt.unassigned}</td>
                      <td className="px-3 py-2 tabular-nums text-slate-600">{item.openedAt ? new Date(item.openedAt).toLocaleString(locale === 'vi' ? 'vi-VN' : 'en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-slate-600">{item.sla}</td>
                      <td className="px-3 py-2">
                        {archived ? <span data-testid="terminal-status-badge">{m.archived}</span> : (
                          <button title={mine ? m.releaseCase : m.claimCase} aria-label={busy === 'claim' ? m.claiming : busy === 'release' ? m.releasing : other ? m.ownedOther : mine ? m.release : m.claim} disabled={Boolean(busy) || other || !isAnalystAuthorized} onClick={() => void updateLock(item.id, mine)} className={`inline-flex h-7 min-w-[4.5rem] items-center justify-center rounded-md px-2 text-[11px] font-semibold text-white disabled:bg-slate-300 disabled:text-slate-700 disabled:opacity-100 ${mine ? 'bg-red-600 hover:bg-red-700' : 'bg-emerald-600 hover:bg-emerald-700'}`}>{busy === 'claim' ? m.claiming : busy === 'release' ? m.releasing : other ? m.ownedOther : mine ? m.release : m.claim}</button>
                        )}
                        {ownershipErrors[item.id] && <p role="alert" className="text-red-800">{ownershipErrors[item.id]}</p>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>)}
          </div>
        ) : (
        <div className="relative overflow-y-auto p-2 space-y-1 flex-1">
          {!visibleCases.length && (
            <p className="py-6 text-center text-xs text-slate-500">
              {searchQuery
                ? m.noSearch
                : queueTab === "history"
                ? m.noHistory
                : m.noCases}
            </p>
          )}
          {visibleCases.map(item => {
            const detail = caseDetail?.case.id === item.id ? caseDetail : ownership[item.id];
            const activeLease = detail?.active_lease;
            const alive = Boolean(activeLease && (!activeLease.expires_at || Date.parse(activeLease.expires_at) > clockNow));
            const holder = detail ? (alive ? activeLease?.analyst_id : undefined) : item.lockedBy;
            const mine = Boolean(holder && holder === currentAnalyst?.id);
            const other = Boolean(holder && holder !== currentAnalyst?.id);
            const archived = ['resolved', 'dismissed', 'auto_dismissed'].includes(detail?.case.status || item.status || '');
            const busy = ownershipBusy[item.id];
            return (
              <article
                key={item.id}
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest('button')) return;
                  selectCase(item.id);
                }}
                className={`relative rounded-md border border-slate-200 border-l-4 p-2 text-xs space-y-1.5 bg-white cursor-pointer ${
                  item.id === selectedCaseId ? 'bg-emerald-50/60 ring-1 ring-emerald-300' : ''
                } ${
                  item.severity === 'P0' ? 'border-l-red-500' : item.severity === 'P1' ? 'border-l-amber-500' : 'border-l-blue-500'
                }`}
              >
                <div className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1 min-w-0">
                    <span className="font-semibold shrink-0">{item.severity} ·</span>
                    <CopyId id={item.id} label={m.caseId} displayId={item.code} />
                  </div>
                  {item.sla !== '—' && <span className="text-slate-500 tabular-nums shrink-0">{item.sla}</span>}
                </div>
                <button
                  type="button"
                  aria-pressed={item.id === selectedCaseId}
                  aria-label={`${item.severity} · ${item.code} ${item.driverName} ${item.plate}`}
                  onClick={() => selectCase(item.id)}
                  className="w-full space-y-1 text-left focus-visible:outline-emerald-700"
                >
                  <div className="flex min-h-5 items-center justify-between gap-2">
                    <span className="truncate font-medium leading-5">{item.driverName}</span>
                    <span className="shrink-0 leading-5 text-slate-500">{item.plate}</span>
                  </div>
                </button>
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-slate-500" title={item.district}>{item.district}</span>
                  {archived ? <span data-testid="terminal-status-badge">{m.archived} · {item.status}</span> : <>
                    <button title={mine ? m.releaseCase : m.claimCase} aria-label={busy === 'claim' ? m.claiming : busy === 'release' ? m.releasing : other ? m.ownedOther : mine ? m.release : m.claim} disabled={Boolean(busy) || other || !isAnalystAuthorized} onClick={() => void updateLock(item.id, mine)} className={`inline-flex h-7 min-w-[4.5rem] items-center justify-center rounded-md px-2 text-[11px] font-semibold text-white disabled:bg-slate-300 disabled:text-slate-700 disabled:opacity-100 ${mine ? 'bg-red-600 hover:bg-red-700' : 'bg-emerald-600 hover:bg-emerald-700'}`}>{busy === 'claim' ? m.claiming : busy === 'release' ? m.releasing : other ? m.ownedOther : mine ? m.release : m.claim}</button>
                  </>}
                </div>
                {ownershipErrors[item.id] && <p role="alert" className="text-red-800">{ownershipErrors[item.id]}</p>}
              </article>
            );
          })}
        </div>
        )}
        {queueTab === 'history' && historyTotal > historyLimit && (
          <div className="flex items-center justify-between px-2 py-1.5 border-t text-xs text-slate-500 bg-slate-50 shrink-0">
            <span>{historyOffset + 1}-{Math.min(historyOffset + historyLimit, historyTotal)} {m.of} {historyTotal}</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label={m.previousPage}
                disabled={historyOffset <= 0}
                onClick={() => setHistoryOffset(prev => Math.max(0, prev - historyLimit))}
                className="px-2 py-0.5 rounded border bg-white disabled:opacity-40 text-xs hover:bg-slate-50"
              >
                {m.prev}
              </button>
              <button
                type="button"
                aria-label={m.nextPage}
                disabled={historyOffset + historyLimit >= historyTotal}
                onClick={() => setHistoryOffset(prev => prev + historyLimit)}
                className="px-2 py-0.5 rounded border bg-white disabled:opacity-40 text-xs hover:bg-slate-50"
              >
                {m.next}
              </button>
            </div>
          </div>
        )}
      </section>
      {queueExpanded ? null : !activeCase ? <div className="flex-1 m-auto p-6 text-center text-sm text-slate-500">{m.selectCase}</div> : <>
      <section aria-label={m.workspace} className="w-full min-w-0 shrink-0 lg:w-[50%] lg:shrink-0 border-r border-slate-200 flex flex-col min-h-[70vh] lg:min-h-0 lg:h-full bg-white">
        {detailLoading && <WorkspaceLoading message={m.loadingCase} />}
        {detailError && <div className="m-auto p-6 text-center space-y-3"><p role="alert" className="text-sm text-red-700">{detailError}</p><button onClick={()=>setDetailRevision(v=>v+1)} className="border rounded px-3 py-1 text-sm">{m.retryCase}</button></div>}
        {caseDetail && <div hidden={detailLoading || Boolean(detailError) || caseDetail.case.id !== selectedCaseId} inert={detailLoading || Boolean(detailError) || caseDetail.case.id !== selectedCaseId} className={`${detailLoading || Boolean(detailError) || caseDetail.case.id !== selectedCaseId ? 'hidden' : 'flex'} flex-col flex-1 min-h-0`}>
        <div className="relative flex-1 min-h-0 overflow-y-auto p-2.5">
          <CenterPanelTabs activeTab={activeCenterTab} onTabChange={setActiveCenterTab} />
          {isLockedByOther && <p role="status" aria-label={m.readOnly} className="my-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{m.readOnly}</p>}
          {feedbackMessage && <div className="my-2 flex items-center gap-2">
            <p role={feedbackError ? 'alert' : 'status'} className={`text-xs ${feedbackError ? 'text-red-700' : 'text-emerald-800'}`}>{feedbackMessage}</p>
            {feedbackError && failedDecision?.caseId === selectedCaseId && failedDecision.selectionVersion === selectionVersionRef.current && <button
              type="button"
              disabled={isSubmitting || !isLockedByMe || !isAnalystAuthorized || detailLoading || Boolean(detailError) || isTerminalCase}
              onClick={() => void handleSubmitDecision(failedDecision.action, failedDecision.rationale)}
              className="rounded border border-red-700 px-2 py-0.5 text-xs text-red-800 hover:bg-red-50 disabled:opacity-50"
            >{m.retry}</button>}
          </div>}
          {caseDetail.guardrails?.is_blocking && <p role="status" className="rounded bg-amber-50 p-2 text-xs text-amber-900">{m.incomplete}</p>}
          {activeCenterTab === 'overview' && (
            <OverviewTab
              caseDetail={caseDetail}
              selectedCaseId={selectedCaseId}
              disputeDossier={disputeDossier}
              mapTelemetry={mapTelemetry}
              onTabChange={setActiveCenterTab}
              onClaim={() => void updateLock(selectedCaseId, false)}
              canClaim={canClaim}
              claimBusy={claimBusy}
            />
          )}
          <div hidden={activeCenterTab !== 'maps'} inert={activeCenterTab !== 'maps'}>
            <MapsTab caseDetail={caseDetail} disputeDossier={disputeDossier} selectedCaseId={caseDetail.case.id} pickupLocation={pickupLocation} initialDriverLocation={initialDriverLocation} destinationLocation={destinationLocation} mapTelemetry={mapTelemetry} isActive={activeCenterTab === 'maps'} />
          </div>
          {activeCenterTab === 'customer' && <ConversationTab caseDetail={caseDetail} disputeDossier={disputeDossier} caseWorkflowTrace={caseWorkflowTrace} activeCaseDriverName={activeCase.driverName} isLockedByOther={!isLockedByMe || isTerminalCase || !isAnalystAuthorized} />}
          {activeCenterTab === 'driver' && <DriverInfoTab key={`driver-${caseDetail.case.id}`} caseDetail={caseDetail} />}
          <FinalizationTab
            key={`finalization-${caseDetail.case.id}`}
            caseDetail={caseDetail}
            workflow={caseWorkflowTrace}
            disputeDossier={disputeDossier}
            isApplyingPrecedent={isApplyingPrecedent}
            onApplyPrecedent={handleApplyPrecedent}
            isActive={activeCenterTab === 'finalization'}
            canWrite={isLockedByMe && isAnalystAuthorized && !isTerminalCase && !detailLoading}
            busy={isSubmitting}
            choice={preliminaryChoice}
            onChoice={setPreliminaryChoice}
            note={preliminaryNote}
            onNote={setPreliminaryNote}
            savingJudgment={preliminarySaving}
            onSaveJudgment={() => void handlePreliminaryCommit()}
            rationale={rationale}
            onRationale={setRationale}
            onDecision={(action, text) => void handleSubmitDecision(action, text)}
            delta={caseDetail.adjudication?.delta ?? preliminaryDelta(savedWorkspaceJudgment(caseDetail)?.judgment, caseDetail.assessment?.category)}
            onClaim={() => void updateLock(selectedCaseId, false)}
            canClaim={canClaim}
            claimBusy={claimBusy}
          />
          {isTerminalCase && <div data-testid="terminal-decision-banner" className="rounded border bg-slate-50 p-3 text-xs"><strong>{m.finalized} · {m.version} {caseDetail.case.version}</strong><p>{m.status}: {caseDetail.case.status}</p>{caseDetail.adjudication && <div className="mt-2 space-y-1"><p>{m.outcome}: {caseDetail.adjudication.outcome || m.unavailable}</p><p>{m.rationaleLabel}: {caseDetail.adjudication.rationale || m.unavailable}</p><p className="flex items-center gap-1">{m.actor}: {caseDetail.adjudication.analyst_id ? <CopyId id={String(caseDetail.adjudication.analyst_id)} label={m.actor} /> : m.unavailable}</p><p>{m.recorded}: {caseDetail.adjudication.approved_at || caseDetail.adjudication.adjudicated_at || m.unavailable}</p></div>}<p>{m.archiveReadOnly}</p></div>}
        </div>
        </div>}
      </section>
      {/* Right Column: AI Copilot & Driver Relay (28% width) */}
      <AnalystCopilotPanel
        className="w-full min-w-0 lg:flex-1 lg:basis-0"
        caseId={selectedCaseId}
        isLockedByMe={isLockedByMe}
        placeholder={chatPlaceholder}
        onSelectCase={selectCase}
        onOpenTrip={() => setActiveCenterTab("maps")}
        activeTab={activeAgentTab}
        onTabChange={setActiveAgentTab}
        onTurnIdChange={setLatestAgentTurnId}
        driverTabContent={
          <DriverRelayTab
            transcript={disputeDossier?.transcript ?? []}
            input={relayInput}
            onInputChange={setRelayInput}
            onSend={() => void handleRelaySend()}
            onRetry={handleRelayRetry}
            sending={relaySending}
            error={relayError}
            closed={relaySessionClosed}
          />
        }
      />
      </>}
    </div>
  );
}
export function WorkspaceLoading({ message }: { message: string }) {
  return (
    <div
      role="status"
      aria-label={message}
      className="flex-1 min-h-48 flex flex-col gap-3 p-4"
      aria-busy="true"
    >
      <div className="flex items-center gap-2 mb-2">
        <Skeleton className="h-3 w-32" />
      </div>
      <Skeleton className="h-4 w-full rounded" />
      <Skeleton className="h-4 w-5/6 rounded" />
      <Skeleton className="h-4 w-3/4 rounded" />
      <Skeleton className="h-4 w-full rounded" />
      <Skeleton className="h-4 w-4/5 rounded" />
      <span className="sr-only">{message}</span>
    </div>
  );
}
