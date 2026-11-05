"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DEMO_CASES, DemoCaseData } from "../fixtures";

interface ChapterAnalystDecidesProps {
  reducedMotion: boolean;
}

type CenterTabKey = "overview" | "conversation" | "driver" | "workflow";

export function ChapterAnalystDecides({
  reducedMotion,
}: ChapterAnalystDecidesProps) {
  // If reduced motion: start in final state (Case 2 selected, rationale full, stamp "Driver cleared")
  const [selectedCaseIndex, setSelectedCaseIndex] = useState<number>(() =>
    reducedMotion ? 1 : 0
  );
  const [activeTab, setActiveTab] = useState<CenterTabKey>("overview");
  const [stampedDecision, setStampedDecision] = useState<string | null>(() =>
    reducedMotion ? "Driver cleared" : null
  );
  const [typedRationale, setTypedRationale] = useState<string>(() =>
    reducedMotion ? (DEMO_CASES[1]?.forensicBrief.summary_text ?? "") : ""
  );

  const sectionRef = useRef<HTMLElement>(null);
  const timersRef = useRef<Array<ReturnType<typeof setTimeout> | ReturnType<typeof setInterval>>>([]);
  const autoplayStoppedRef = useRef<boolean>(reducedMotion);
  const isStartedRef = useRef<boolean>(reducedMotion);

  const clearAllTimers = () => {
    timersRef.current.forEach((t) => {
      clearTimeout(t as unknown as number);
      clearInterval(t as unknown as number);
    });
    timersRef.current = [];
  };

  const stopAutoplay = () => {
    autoplayStoppedRef.current = true;
    clearAllTimers();
  };

  useEffect(() => {
    if (reducedMotion) return;

    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      return;
    }

    const typeText = (fullText: string, onDone: () => void) => {
      setTypedRationale("");
      let charIndex = 0;
      const interval = setInterval(() => {
        if (autoplayStoppedRef.current) {
          clearInterval(interval);
          return;
        }
        charIndex += 2;
        if (charIndex >= fullText.length) {
          clearInterval(interval);
          setTypedRationale(fullText);
          onDone();
        } else {
          setTypedRationale(fullText.slice(0, charIndex));
        }
      }, 12);
      timersRef.current.push(interval);
    };

    const startAutoplay = () => {
      if (autoplayStoppedRef.current) return;
      clearAllTimers();

      // Step 1: Select Case 1
      setSelectedCaseIndex(0);
      setStampedDecision(null);

      const case1Text = DEMO_CASES[0]?.forensicBrief.summary_text ?? "";
      typeText(case1Text, () => {
        // After Case 1 typing finishes -> show stamp "Penalty confirmed"
        const t1 = setTimeout(() => {
          if (autoplayStoppedRef.current) return;
          setStampedDecision("Penalty confirmed");

          // After stamp appears -> pause, then advance to Case 2
          const t2 = setTimeout(() => {
            if (autoplayStoppedRef.current) return;
            setSelectedCaseIndex(1);
            setStampedDecision(null);

            const case2Text = DEMO_CASES[1]?.forensicBrief.summary_text ?? "";
            typeText(case2Text, () => {
              const t3 = setTimeout(() => {
                if (autoplayStoppedRef.current) return;
                setStampedDecision("Driver cleared");
              }, 300);
              timersRef.current.push(t3);
            });
          }, 700);
          timersRef.current.push(t2);
        }, 300);
        timersRef.current.push(t1);
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !isStartedRef.current) {
          isStartedRef.current = true;
          observer.disconnect();
          startAutoplay();
        }
      },
      { threshold: 0.2 }
    );

    observer.observe(el);

    return () => {
      observer.disconnect();
      clearAllTimers();
    };
  }, [reducedMotion]);

  const handleSelectCase = (idx: number) => {
    stopAutoplay();
    setSelectedCaseIndex(idx);
    setStampedDecision(null);
    setTypedRationale(DEMO_CASES[idx]?.forensicBrief.summary_text ?? "");
  };

  const handleAction = (actionName: string) => {
    stopAutoplay();
    const current = DEMO_CASES[selectedCaseIndex] ?? DEMO_CASES[0];
    setTypedRationale(current.forensicBrief.summary_text);

    if (actionName === "Approve" || actionName === "Dismiss") {
      setStampedDecision("Driver cleared");
    } else if (actionName === "Reject" || actionName === "Suspend 24h") {
      setStampedDecision(actionName === "Suspend 24h" ? "Penalty confirmed: Suspend 24h" : "Penalty confirmed");
    } else if (actionName === "Request evidence") {
      setStampedDecision("Evidence requested");
    } else if (actionName === "Warn") {
      setStampedDecision("Penalty confirmed: Warning issued");
    } else if (actionName === "Fine") {
      setStampedDecision("Penalty confirmed: Fine issued");
    } else if (actionName === "Escalate") {
      setStampedDecision("Case escalated");
    } else {
      setStampedDecision(`${actionName} applied`);
    }
  };

  const currentCase: DemoCaseData = DEMO_CASES[selectedCaseIndex] ?? DEMO_CASES[0];
  const displayedRationale =
    typedRationale.length > 0 ? typedRationale : currentCase.forensicBrief.summary_text;

  return (
    <section
      id="analyst-decides"
      ref={sectionRef}
      aria-labelledby="heading-analyst-decides"
      className="scroll-mt-20 py-12 border-b border-outline-variant/60"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-6xl mx-auto px-4">
        {/* Narrative Left */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center gap-1.5 text-primary font-mono text-xs">
            <span className="px-1.5 py-0.5 rounded bg-surface-container font-semibold">
              04
            </span>
            <span className="font-semibold uppercase tracking-wider">
              Analyst decides
            </span>
          </div>

          <h2
            id="heading-analyst-decides"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface"
          >
            Analyst decides
          </h2>

          <p className="text-base text-secondary leading-relaxed">
            Analysts review the full story with maps, statements, and clear evidence.
          </p>

          <div className="pt-2 flex flex-col gap-2">
            <p className="text-xs text-secondary font-mono">
              <span className="font-semibold text-primary">Next:</span> Team learns
            </p>
            <div>
              <Link
                href="/workplace"
                className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline cursor-pointer"
              >
                <span>Open Workplace</span>
                <span className="material-symbols-outlined !text-[14px]" aria-hidden="true">
                  arrow_forward
                </span>
              </Link>
            </div>
          </div>
        </div>

        {/* UI Frame Right: Workplace Cockpit Frame */}
        <div className="lg:col-span-8">
          <Card className="p-3 shadow-sm space-y-2 bg-slate-50/50 border border-slate-300">
            {/* Top Toolbar matching real Workplace */}
            <div className="flex items-center justify-between border-b border-slate-200 pb-2 px-1">
              <div className="flex items-center gap-2">
                <div className="w-5 h-5 rounded bg-emerald-600 flex items-center justify-center text-white">
                  <span className="material-symbols-outlined !text-[13px] text-white" aria-hidden="true">
                    shield
                  </span>
                </div>
                <span className="text-xs font-bold text-slate-800">
                  Triage Queue · Fraud Analyst Workplace
                </span>
                <span className="text-[10px] font-mono text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.2 rounded font-semibold">
                  2 cases active
                </span>
              </div>
              <Badge variant="secondary" className="text-[10px]">
                Sample data
              </Badge>
            </div>

            {/* Workplace Tri-Pane Composition */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-2 text-xs">
              {/* Left Column (3 cols): Triage Queue */}
              <div className="md:col-span-3 border border-slate-200 rounded p-1.5 bg-white space-y-1.5">
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 px-1 pb-1 border-b border-slate-200">
                  <span className="uppercase font-bold text-slate-700">Triage Queue</span>
                  <span>{DEMO_CASES.length} cases</span>
                </div>

                <div className="space-y-1.5" role="tablist" aria-label="Case Queue">
                  {DEMO_CASES.map((item, idx) => {
                    const isSelected = selectedCaseIndex === idx;
                    const isP0 = item.priority === "P0";
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="tab"
                        aria-selected={isSelected}
                        onClick={() => handleSelectCase(idx)}
                        className={`w-full text-left p-1.5 rounded border-l-4 border transition-colors cursor-pointer text-xs space-y-1 focus-visible:outline-2 focus-visible:outline-primary ${
                          isP0 ? "border-l-red-500" : "border-l-blue-500"
                        } ${
                          isSelected
                            ? "bg-emerald-50 ring-1 ring-emerald-300 border-emerald-300"
                            : "bg-white border-slate-200 hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1">
                            <span
                              className={`text-[9px] px-1 py-0.2 rounded font-mono font-bold uppercase ${
                                isP0
                                  ? "bg-red-100 text-red-700"
                                  : "bg-blue-100 text-blue-700"
                              }`}
                            >
                              {item.priority}
                            </span>
                            <span className="font-mono font-bold text-slate-900 text-[11px]">
                              {item.code}
                            </span>
                          </div>
                          <span className="text-[10px] font-mono text-slate-500">
                            {idx === 0 ? "08:16" : "08:45"}
                          </span>
                        </div>
                        <div className="flex justify-between gap-1 text-[11px]">
                          <span className="font-medium text-slate-800 truncate">
                            {item.driverName}
                          </span>
                          <span className="text-slate-500 font-mono text-[10px] shrink-0">
                            {item.plate}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-slate-500 pt-0.5 border-t border-slate-100">
                          <span className="truncate">{item.pickup.split(" ")[0]}</span>
                          <span className="font-mono text-[9px] px-1 rounded bg-slate-100 text-slate-700">
                            {item.stallDurationS > 0 ? `Stall ${item.stallDurationS}s` : "corridor ok"}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Center Column (5 cols): Case Center Workspace */}
              <div className="md:col-span-5 border border-slate-200 rounded p-2 bg-white flex flex-col justify-between space-y-2 min-w-0">
                <div className="space-y-2">
                  {/* Center Header with case id, red "P0 CRITICAL" chip and driver row */}
                  <div role="group" aria-label="Case header" className="border-b border-slate-200 pb-2 space-y-1.5">
                    <div className="flex items-center justify-between gap-1">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-bold text-sm text-slate-900">
                          {currentCase.code}
                        </span>
                        {currentCase.priority === "P0" ? (
                          <span className="px-1.5 py-0.5 rounded font-mono font-bold text-[9px] uppercase tracking-wider bg-red-600 text-white">
                            P0 CRITICAL
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded font-mono font-bold text-[9px] uppercase tracking-wider bg-blue-100 text-blue-800">
                            P2 NORMAL
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] font-mono text-slate-500">
                        SLA: 00:28 / 00:45s
                      </span>
                    </div>

                    {/* Driver Row */}
                    <div className="flex items-center gap-2">
                      <div className="relative w-8 h-8 rounded-full bg-slate-100 border border-slate-300 flex items-center justify-center font-bold text-xs text-slate-700 shrink-0">
                        {currentCase.driverName.split(" ").map((n) => n[0]).slice(0, 2).join("")}
                        <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500 border border-white" />
                      </div>
                      <div className="min-w-0 flex-1 leading-tight">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-slate-900 text-xs truncate">
                            {currentCase.driverName}
                          </span>
                          <span className="font-mono text-[10px] px-1 py-0.2 rounded bg-slate-100 text-slate-700 border border-slate-200">
                            {currentCase.plate}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 text-[10px] text-slate-500 mt-0.5">
                          <span className="text-amber-600 font-semibold">★ 4.85</span>
                          <span>·</span>
                          <span>94.2% Nhận</span>
                          <span>·</span>
                          <span>{currentCase.pickup.split(" ")[0]} → {currentCase.dropoff.split(" ")[0]}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Center Tabs with full labels */}
                  <nav
                    role="tablist"
                    aria-label="Center Panel Views"
                    className="flex items-center gap-1 p-0.5 bg-slate-100 rounded border border-slate-200 w-full min-w-0 overflow-x-auto"
                  >
                    {[
                      { id: "overview" as const, label: "Overview", icon: "dashboard" },
                      { id: "conversation" as const, label: "Conversation", icon: "forum" },
                      { id: "driver" as const, label: "Driver", icon: "badge" },
                      { id: "workflow" as const, label: "Workflow", icon: "account_tree" },
                    ].map((tab) => {
                      const isActive = activeTab === tab.id;
                      return (
                        <button
                          key={tab.id}
                          type="button"
                          role="tab"
                          aria-selected={isActive}
                          onClick={() => setActiveTab(tab.id)}
                          className={`flex-1 shrink-0 flex items-center justify-center gap-1 py-1 px-1.5 rounded text-[11px] font-medium transition-colors whitespace-nowrap cursor-pointer ${
                            isActive
                              ? "bg-white text-emerald-950 font-bold shadow-xs border border-slate-200"
                              : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/60 border border-transparent"
                          }`}
                        >
                          <span className={`material-symbols-outlined !text-[13px] shrink-0 ${isActive ? "text-emerald-700" : "text-slate-400"}`} aria-hidden="true">
                            {tab.icon}
                          </span>
                          <span>{tab.label}</span>
                        </button>
                      );
                    })}
                  </nav>

                  {/* Telemetry / Map View */}
                  <div className="relative h-20 bg-slate-50 rounded border border-slate-200 overflow-hidden">
                    <svg viewBox="0 0 240 80" className="w-full h-full">
                      <path d="M 0 40 L 240 40 M 120 0 L 120 80" stroke="#e2e8f0" strokeWidth="1" strokeDasharray="3 3" />
                      <path
                        d={
                          currentCase.priority === "P0"
                            ? "M 20 60 C 60 60, 90 75, 140 65 C 180 35, 200 25, 220 20"
                            : "M 20 60 C 80 50, 160 35, 220 20"
                        }
                        fill="none"
                        stroke={currentCase.priority === "P0" ? "#dc2626" : "#059669"}
                        strokeWidth="2.5"
                      />
                      <circle cx="20" cy="60" r="3" fill="#059669" />
                      <circle cx="220" cy="20" r="3" fill="#0284c7" />
                    </svg>
                    <div className="absolute bottom-1 left-1.5 bg-white/90 border border-slate-200 text-[9px] px-1 rounded font-mono text-slate-600">
                      {currentCase.priority === "P0" ? "Detour + 210s stall" : "Normal corridor flow"}
                    </div>
                  </div>
                </div>

                {/* Bottom Action Bar: Dismiss, Request evidence, Warn, Fine, Suspend 24h, Escalate */}
                <div className="space-y-1.5 pt-2 border-t border-slate-200">
                  <div className="text-[10px] font-mono text-slate-500 font-bold uppercase">
                    Actions
                  </div>
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      onClick={() => handleAction("Dismiss")}
                      className="px-2 py-0.5 rounded border border-slate-300 bg-white hover:bg-slate-50 text-[10px] text-slate-700 font-medium cursor-pointer"
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAction("Request evidence")}
                      className="px-2 py-0.5 rounded border border-slate-300 bg-white hover:bg-slate-50 text-[10px] text-slate-700 font-medium cursor-pointer"
                    >
                      Request evidence
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAction("Warn")}
                      className="px-2 py-0.5 rounded border border-slate-300 bg-white hover:bg-slate-50 text-[10px] text-slate-700 font-medium cursor-pointer"
                    >
                      Warn
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAction("Fine")}
                      className="px-2 py-0.5 rounded border border-slate-300 bg-white hover:bg-slate-50 text-[10px] text-slate-700 font-medium cursor-pointer"
                    >
                      Fine
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAction("Suspend 24h")}
                      className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-[10px] flex items-center gap-0.5 cursor-pointer"
                    >
                      <span className="material-symbols-outlined !text-[11px]">check</span>
                      Suspend 24h
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAction("Escalate")}
                      className="px-2 py-0.5 rounded border border-amber-400 bg-amber-50 hover:bg-amber-100 text-amber-800 text-[10px] font-medium cursor-pointer"
                    >
                      Escalate
                    </button>
                  </div>

                  {/* Approve / Reject primary decision buttons */}
                  <div className="flex gap-1.5 pt-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="emerald"
                      onClick={() => handleAction("Approve")}
                      className="flex-1 text-xs h-6.5 cursor-pointer"
                    >
                      Approve
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={() => handleAction("Reject")}
                      className="flex-1 text-xs h-6.5 cursor-pointer"
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              </div>

              {/* Right Column (4 cols): AI Policy Copilot Panel */}
              <div className="md:col-span-4 border border-slate-200 rounded p-2 bg-slate-50 flex flex-col justify-between space-y-2">
                <div className="space-y-2">
                  {/* Copilot Header */}
                  <div className="flex items-center justify-between pb-1.5 border-b border-slate-200">
                    <div className="flex items-center gap-1.5">
                      <div className="w-5 h-5 rounded bg-emerald-600 flex items-center justify-center text-white">
                        <span className="material-symbols-outlined !text-[13px]">smart_toy</span>
                      </div>
                      <span className="font-bold text-xs text-slate-800">
                        AI Policy Copilot
                      </span>
                    </div>
                    <div className="flex items-center gap-1 font-mono text-[9px]">
                      <span className="px-1 py-0.2 rounded bg-white border border-slate-200 text-slate-600">
                        {currentCase.code}
                      </span>
                      <span className="px-1 py-0.2 rounded bg-emerald-100 text-emerald-800 font-bold">
                        92% sure
                      </span>
                    </div>
                  </div>

                  {/* Forensic Summary Card */}
                  <div className="rounded border border-emerald-200 bg-emerald-50/50 p-2 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-[10px] text-emerald-950 flex items-center gap-1">
                        <span className="material-symbols-outlined !text-[12px] text-emerald-700">analytics</span>
                        AI Forensic Summary
                      </span>
                      <span className="text-[9px] font-mono px-1 py-0.2 rounded bg-emerald-200/80 text-emerald-900 font-semibold">
                        AI summary
                      </span>
                    </div>
                    <p className="text-[10.5px] text-slate-700 leading-snug">
                      {currentCase.forensicBrief.summary_text}
                    </p>
                    <button
                      type="button"
                      onClick={() => handleAction("Approve")}
                      className="mt-1 w-full text-center py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-[10px] transition-colors cursor-pointer"
                    >
                      Apply Recommendation
                    </button>
                  </div>

                  {/* Decision Rationale Box */}
                  <div className="space-y-1">
                    <label
                      htmlFor="decision-rationale"
                      className="text-[10px] font-bold text-slate-700 uppercase tracking-wide block"
                    >
                      Decision Rationale
                    </label>
                    <textarea
                      id="decision-rationale"
                      aria-label="Decision rationale"
                      readOnly
                      rows={4}
                      value={displayedRationale}
                      className="w-full text-xs p-2 bg-white border border-slate-300 rounded text-slate-900 leading-relaxed overflow-y-auto min-h-[80px] resize-none focus:outline-emerald-600 shadow-2xs"
                    />
                  </div>

                  {/* Stamped Decision Chip / Box */}
                  {stampedDecision && (
                    <div
                      aria-live="polite"
                      className={`p-1.5 rounded font-bold text-xs text-center border shadow-xs transition-all ${
                        stampedDecision.toLowerCase().includes("cleared") ||
                        stampedDecision.toLowerCase().includes("approved") ||
                        stampedDecision.toLowerCase().includes("dismissed")
                          ? "bg-emerald-50 border-emerald-300 text-emerald-800"
                          : "bg-red-50 border-red-300 text-red-800"
                      }`}
                    >
                      {stampedDecision}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Bottom link & notes */}
            <div className="flex items-center justify-between pt-1 border-t border-slate-200 text-xs">
              <span className="text-slate-600 text-[11px]">
                Review evidence, match past cases, and log decisions.
              </span>
              <Link
                href="/workplace"
                className="font-medium text-primary hover:underline flex items-center gap-1"
              >
                <span>Open Workplace</span>
                <span className="material-symbols-outlined !text-[13px]" aria-hidden="true">
                  open_in_new
                </span>
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </section>
  );
}
