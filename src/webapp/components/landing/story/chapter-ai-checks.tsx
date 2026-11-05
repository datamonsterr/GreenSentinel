"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface ChapterAIChecksProps {
  reducedMotion: boolean;
}

export function ChapterAIChecks({ reducedMotion }: ChapterAIChecksProps) {
  const [case1Progress, setCase1Progress] = useState(() => (reducedMotion ? 100 : 0));
  const [case2Progress, setCase2Progress] = useState(() => (reducedMotion ? 100 : 0));
  const [case1Status, setCase1Status] = useState<"idle" | "checking" | "done">(() =>
    reducedMotion ? "done" : "idle"
  );
  const [case2Status, setCase2Status] = useState<"idle" | "checking" | "done">(() =>
    reducedMotion ? "done" : "idle"
  );

  const sectionRef = useRef<HTMLElement>(null);
  const timersRef = useRef<Array<ReturnType<typeof setInterval> | ReturnType<typeof setTimeout>>>([]);
  const case1IntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const case2IntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef<boolean>(reducedMotion);

  const clearAllTimers = () => {
    timersRef.current.forEach((t) => {
      clearInterval(t as unknown as number);
      clearTimeout(t as unknown as number);
    });
    timersRef.current = [];
    if (case1IntervalRef.current) {
      clearInterval(case1IntervalRef.current);
      case1IntervalRef.current = null;
    }
    if (case2IntervalRef.current) {
      clearInterval(case2IntervalRef.current);
      case2IntervalRef.current = null;
    }
  };

  const runCase2 = () => {
    if (case2IntervalRef.current) {
      clearInterval(case2IntervalRef.current);
    }
    setCase2Progress(0);
    setCase2Status("checking");

    let p = 0;
    const interval = setInterval(() => {
      p += 4;
      if (p >= 100) {
        clearInterval(interval);
        case2IntervalRef.current = null;
        setCase2Progress(100);
        setCase2Status("done");
      } else {
        setCase2Progress(p);
      }
    }, 100);

    case2IntervalRef.current = interval;
    timersRef.current.push(interval);
  };

  const runCase1 = (onDone?: () => void) => {
    if (case1IntervalRef.current) {
      clearInterval(case1IntervalRef.current);
    }
    setCase1Progress(0);
    setCase1Status("checking");

    let p = 0;
    const interval = setInterval(() => {
      p += 4;
      if (p >= 100) {
        clearInterval(interval);
        case1IntervalRef.current = null;
        setCase1Progress(100);
        setCase1Status("done");
        if (onDone) {
          const t = setTimeout(onDone, 600);
          timersRef.current.push(t);
        }
      } else {
        setCase1Progress(p);
      }
    }, 100);

    case1IntervalRef.current = interval;
    timersRef.current.push(interval);
  };

  useEffect(() => {
    if (reducedMotion) return;

    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !startedRef.current) {
          startedRef.current = true;
          observer.disconnect();
          runCase1(() => {
            runCase2();
          });
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

  const replayCase1 = () => {
    runCase1();
  };

  const replayCase2 = () => {
    runCase2();
  };

  return (
    <section
      id="ai-checks"
      ref={sectionRef}
      aria-labelledby="heading-ai-checks"
      className="scroll-mt-20 py-12 border-b border-outline-variant/60"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-6xl mx-auto px-4">
        {/* Narrative Left */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center gap-1.5 text-primary font-mono text-xs">
            <span className="px-1.5 py-0.5 rounded bg-surface-container font-semibold">
              02
            </span>
            <span className="font-semibold uppercase tracking-wider">
              AI checks
            </span>
          </div>

          <h2
            id="heading-ai-checks"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface"
          >
            AI checks every trip
          </h2>

          <p className="text-base text-secondary leading-relaxed">
            Smart models screen every ride. Clear trips pass instantly, while detours get flagged.
          </p>

          <div className="pt-2 flex flex-col gap-2">
            <p className="text-xs text-secondary font-mono">
              <span className="font-semibold text-primary">Next:</span> Driver explains
            </p>
            <div>
              <Link
                href="/test"
                className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline cursor-pointer"
              >
                <span>Open Test Console</span>
                <span className="material-symbols-outlined !text-[14px]" aria-hidden="true">
                  arrow_forward
                </span>
              </Link>
            </div>
          </div>
        </div>

        {/* UI Frame Right: Test Console Look */}
        <div className="lg:col-span-7">
          <Card className="p-4 shadow-sm space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
                  rule
                </span>
                <span className="text-xs font-bold text-on-surface">
                  Test Console · Trip Screening
                </span>
              </div>
              <Badge variant="secondary" className="text-[10px]">
                Sample data
              </Badge>
            </div>

            {/* Cases list */}
            <div className="space-y-3" role="region" aria-label="Trip Evaluation Cases">
              {/* Case 1: Detour Trip */}
              <button
                type="button"
                onClick={replayCase1}
                aria-label="Replay Detour trip screening"
                className="w-full text-left p-3 rounded-lg border border-error/30 bg-error-container/10 hover:bg-error-container/20 transition-colors space-y-2 cursor-pointer focus-visible:outline-2 focus-visible:outline-primary"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-on-surface">
                        Trip #94021 · Detour trip
                      </span>
                      {case1Status === "done" ? (
                        <Badge variant="destructive" className="text-[10px]">
                          Fraud case opened
                        </Badge>
                      ) : case1Status === "checking" ? (
                        <span className="text-[10px] text-secondary font-mono">
                          Checking…
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-on-surface mt-1">
                      Route deviation + 210s idle stall at Bà Triệu
                    </p>
                  </div>
                  <span className="text-[11px] font-mono text-error font-semibold shrink-0">
                    High risk
                  </span>
                </div>

                {/* Progress bar */}
                <div className="space-y-1">
                  <div className="h-1.5 w-full bg-outline-variant/40 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-error transition-all duration-150"
                      style={{ width: `${case1Progress}%` }}
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between text-[10px] text-secondary font-mono pt-1">
                  <span>Click to replay check</span>
                  <span className="text-error font-semibold">Sent to analyst</span>
                </div>
              </button>

              {/* Case 2: Normal Trip */}
              <button
                type="button"
                onClick={replayCase2}
                aria-label="Replay Normal trip screening"
                className="w-full text-left p-3 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/10 transition-colors space-y-2 cursor-pointer focus-visible:outline-2 focus-visible:outline-primary"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-on-surface">
                        Trip #94022 · Normal trip
                      </span>
                      {case2Status === "done" ? (
                        <Badge variant="emeraldSoft" className="text-[10px]">
                          No issue
                        </Badge>
                      ) : case2Status === "checking" ? (
                        <span className="text-[10px] text-secondary font-mono">
                          Checking…
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-secondary mt-1">
                      GPS matches route · Normal speed
                    </p>
                  </div>
                  <span className="text-[11px] font-mono text-primary font-semibold shrink-0">
                    Cleared
                  </span>
                </div>

                {/* Progress bar */}
                <div className="space-y-1">
                  <div className="h-1.5 w-full bg-outline-variant/40 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary transition-all duration-150"
                      style={{ width: `${case2Progress}%` }}
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between text-[10px] text-secondary font-mono pt-1">
                  <span>Click to replay check</span>
                  <span className="text-primary font-semibold">Safe • Closed</span>
                </div>
              </button>
            </div>

            {/* Footer action */}
            <div className="flex items-center justify-between pt-2 border-t border-outline-variant/60 text-xs">
              <span className="text-secondary text-[11px]">
                2 sample trips checked
              </span>
              <Link
                href="/test"
                className="font-medium text-primary hover:underline flex items-center gap-1"
              >
                <span>Open Test Console</span>
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
