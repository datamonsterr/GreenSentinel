import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Base Skeleton primitive — animated shimmer block
// ---------------------------------------------------------------------------
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded bg-slate-200/80",
        className,
      )}
      role="presentation"
      {...props}
    />
  );
}

// ---------------------------------------------------------------------------
// CockpitQueueSkeleton — mimics the triage queue side-panel
// ---------------------------------------------------------------------------
export function CockpitQueueSkeleton({ asSubpanel }: { asSubpanel?: boolean } = {}) {
  return (
    <div
      {...(!asSubpanel ? { role: "status", "aria-label": "Loading triage queue" } : { "aria-hidden": true })}
      className={
        asSubpanel
          ? "w-full lg:w-[22%] lg:shrink-0 border-r border-slate-200 flex flex-col max-h-64 lg:max-h-none lg:h-full min-h-0 bg-white"
          : "w-full flex-1 flex flex-col h-full min-h-0 bg-white"
      }
    >
      {!asSubpanel && <span className="sr-only">Loading triage queue...</span>}
      {/* header bar */}
      <div className="h-10 px-3 border-b flex items-center justify-between gap-2 shrink-0">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-6 w-6 rounded" />
      </div>
      {/* filter select */}
      <Skeleton className="m-2 h-7 rounded" />
      {/* case cards */}
      <div className="overflow-auto p-2 space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="rounded border-l-4 border-slate-200 p-2 space-y-1.5 bg-slate-50"
          >
            <div className="flex justify-between">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-10" />
            </div>
            <div className="flex justify-between gap-2">
              <Skeleton className="h-3 w-28" />
              <Skeleton className="h-3 w-14" />
            </div>
            <div className="flex justify-between">
              <Skeleton className="h-2.5 w-16" />
              <Skeleton className="h-2.5 w-12" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CockpitDetailSkeleton — mimics the centre case-workspace panel
// ---------------------------------------------------------------------------
export function CockpitDetailSkeleton({ asSubpanel }: { asSubpanel?: boolean } = {}) {
  return (
    <div
      {...(!asSubpanel ? { role: "status", "aria-label": "Loading case details" } : { "aria-hidden": true })}
      className={
        asSubpanel
          ? "w-full lg:w-[50%] lg:shrink-0 border-r border-slate-200 flex flex-col lg:h-full min-h-0"
          : "w-full flex-1 flex flex-col h-full min-h-0"
      }
    >
      {!asSubpanel && <span className="sr-only">Loading case details...</span>}
      <div className="flex-1 min-h-0 overflow-auto p-2.5 space-y-2.5">
        {/* Case header card */}
        <div className="bg-white border border-slate-200/90 rounded-lg p-3 shadow-xs space-y-2.5">
          <div className="flex items-center gap-3 pb-2.5 border-b border-slate-100">
            {/* Avatar */}
            <Skeleton className="w-11 h-11 rounded-full shrink-0" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-36" />
              <div className="flex gap-1.5">
                <Skeleton className="h-4 w-12 rounded" />
                <Skeleton className="h-4 w-16 rounded" />
                <Skeleton className="h-4 w-14 rounded" />
              </div>
            </div>
            {/* Claim button */}
            <Skeleton className="h-7 w-24 rounded shrink-0" />
          </div>
          {/* Trip row */}
          <div className="flex items-center justify-between gap-2">
            <Skeleton className="h-3 w-48" />
            <div className="flex gap-1.5">
              <Skeleton className="h-5 w-16 rounded" />
              <Skeleton className="h-5 w-14 rounded" />
              <Skeleton className="h-5 w-20 rounded" />
            </div>
          </div>
        </div>

        {/* Map placeholder */}
        <Skeleton className="w-full h-52 rounded-lg" />

        {/* Conversation card */}
        <div className="bg-white border rounded p-2.5 space-y-2">
          <Skeleton className="h-3 w-40" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="p-2 rounded bg-slate-50 space-y-1">
              <div className="flex justify-between">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-2.5 w-10" />
              </div>
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-3/4" />
            </div>
          ))}
        </div>
      </div>

      {/* Decision bar */}
      <div className="border-t bg-white p-2.5 shrink-0 space-y-2">
        <Skeleton className="h-16 w-full rounded" />
        <div className="flex justify-end">
          <Skeleton className="h-8 w-8 rounded" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CockpitChatSkeleton — mimics the right-side agent chat panel
// ---------------------------------------------------------------------------
export function CockpitChatSkeleton({ asSubpanel }: { asSubpanel?: boolean } = {}) {
  return (
    <div
      {...(!asSubpanel ? { role: "status", "aria-label": "Loading agent chat" } : { "aria-hidden": true })}
      className={
        asSubpanel
          ? "w-full lg:w-[28%] lg:shrink-0 flex flex-col h-full min-h-0 bg-white select-none overflow-hidden border-l border-slate-200"
          : "w-full flex-1 flex flex-col h-full min-h-0 bg-white select-none overflow-hidden"
      }
    >
      {!asSubpanel && <span className="sr-only">Loading agent chat...</span>}
      {/* Header */}
      <div className="h-10 px-3 border-b border-slate-200 flex items-center gap-2 bg-slate-50/70 shrink-0">
        <Skeleton className="w-5 h-5 rounded" />
        <Skeleton className="h-3 w-12" />
        <Skeleton className="h-5 w-16 rounded" />
      </div>

      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2.5 space-y-2.5">
        {/* assistant bubble */}
        <div className="rounded border border-slate-200 bg-slate-50 p-2 space-y-1.5">
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-1/2" />
        </div>
        {/* user bubble */}
        <div className="flex flex-col items-end space-y-0.5">
          <Skeleton className="h-7 w-40 rounded-lg" />
        </div>
        {/* assistant bubble */}
        <div className="rounded border border-slate-200 bg-slate-50 p-2 space-y-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-2/3" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      </div>

      {/* Input bar */}
      <div className="p-2 border-t border-slate-200 bg-white shrink-0">
        <Skeleton className="h-8 w-full rounded" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CockpitWorkspaceSkeleton — full 3-column cockpit skeleton
// ---------------------------------------------------------------------------
export function CockpitWorkspaceSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading cockpit workspace"
      aria-busy="true"
      className="flex-1 flex flex-col lg:flex-row h-full min-h-0 overflow-auto lg:overflow-hidden bg-slate-50 text-slate-900"
    >
      <span className="sr-only">Loading cockpit workspace...</span>
      <CockpitQueueSkeleton asSubpanel />
      <CockpitDetailSkeleton asSubpanel />
      <CockpitChatSkeleton asSubpanel />
    </div>
  );
}

// ---------------------------------------------------------------------------
// AnalyticsDashboardSkeleton — mimics the analytics overview page
// ---------------------------------------------------------------------------
export function AnalyticsDashboardSkeleton() {
  return (
    <section
      role="status"
      aria-label="Loading analytics dashboard"
      className="p-4 overflow-auto space-y-4"
      aria-busy="true"
    >
      <span className="sr-only">Loading analytics dashboard...</span>
      <div className="flex justify-between items-center">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-7 w-20 rounded" />
      </div>
      <Skeleton className="h-3 w-80" />
      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {["P0", "P1", "P2"].map((p) => (
          <div key={p} className="bg-white border rounded p-3 space-y-2">
            <Skeleton className="h-3 w-8" />
            <Skeleton className="h-7 w-12" />
          </div>
        ))}
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------------------
// AnalystProfileSkeleton — mimics the analyst profile page
// ---------------------------------------------------------------------------
export function AnalystProfileSkeleton() {
  return (
    <section
      role="status"
      aria-label="Loading analyst profile"
      className="p-4 overflow-auto space-y-4"
      aria-busy="true"
    >
      <span className="sr-only">Loading analyst profile...</span>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-3 w-36" />
      <ul className="divide-y border rounded bg-white">
        {Array.from({ length: 4 }).map((_, i) => (
          <li key={i} className="p-3 flex justify-between gap-3">
            <Skeleton className="h-3 w-48" />
            <Skeleton className="h-3 w-16" />
          </li>
        ))}
      </ul>
      <Skeleton className="h-7 w-28 rounded" />
    </section>
  );
}

// ---------------------------------------------------------------------------
// WorkspaceInitSkeleton — top-level init skeleton (auth + API boot phase)
// Used instead of bare WorkspaceLoading spinner when the entire shell loads
// ---------------------------------------------------------------------------
export function WorkspaceInitSkeleton({ message }: { message: string }) {
  return (
    <div
      role="status"
      aria-label={message}
      className="flex-1 flex flex-col h-full min-h-0 overflow-hidden bg-slate-50"
      aria-busy="true"
    >
      {/* Sub-header bar skeleton */}
      <div className="h-10 w-full bg-white border-b border-slate-200 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2">
          <Skeleton className="w-7 h-7 rounded" />
          <Skeleton className="w-6 h-6 rounded-full" />
        </div>
        <Skeleton className="h-7 flex-1 max-w-lg mx-3 rounded" />
        <Skeleton className="w-7 h-7 rounded-full" />
      </div>

      {/* Cockpit skeleton for main content */}
      <CockpitWorkspaceSkeleton />

      {/* SR-only label */}
      <span className="sr-only">{message}</span>
    </div>
  );
}
