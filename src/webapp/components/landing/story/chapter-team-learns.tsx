"use client";

import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

export function ChapterTeamLearns() {
  return (
    <section
      id="team-learns"
      aria-labelledby="heading-team-learns"
      className="scroll-mt-20 py-12 space-y-12"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-6xl mx-auto px-4">
        {/* Narrative Left */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center gap-1.5 text-primary font-mono text-xs">
            <span className="px-1.5 py-0.5 rounded bg-surface-container font-semibold">
              05
            </span>
            <span className="font-semibold uppercase tracking-wider">
              Team learns
            </span>
          </div>

          <h2
            id="heading-team-learns"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface"
          >
            Team learns
          </h2>

          <p className="text-base text-secondary leading-relaxed">
            Resolved cases train future detection so honest drivers never face repeated flags.
          </p>

          <div className="pt-2">
            <p className="text-xs text-secondary font-mono">
              <span className="font-semibold text-primary">Outcome:</span> Continuous feedback loop
            </p>
          </div>
        </div>

        {/* UI Frame Right: Learning Loop Graphic */}
        <div className="lg:col-span-7">
          <Card className="p-4 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
                  sync
                </span>
                <span className="text-xs font-bold text-on-surface">
                  Continuous Feedback Loop
                </span>
              </div>
              <Badge variant="secondary" className="text-[10px]">
                Sample data
              </Badge>
            </div>

            {/* Loop graphic nodes */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 relative">
              {/* Node 1 */}
              <div className="p-3 rounded border border-outline-variant/60 bg-surface space-y-1 relative">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-secondary">01 VERDICT</span>
                  <span className="material-symbols-outlined !text-[14px] text-primary" aria-hidden="true">
                    gavel
                  </span>
                </div>
                <div className="font-bold text-xs text-on-surface">
                  Case Resolved
                </div>
                <p className="text-[11px] text-secondary">
                  Analyst verifies genuine marathon detour and clears driver.
                </p>
              </div>

              {/* Node 2 */}
              <div className="p-3 rounded border border-outline-variant/60 bg-surface space-y-1 relative">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-secondary">02 KNOWLEDGE</span>
                  <span className="material-symbols-outlined !text-[14px] text-primary" aria-hidden="true">
                    memory
                  </span>
                </div>
                <div className="font-bold text-xs text-on-surface">
                  Rule Updated
                </div>
                <p className="text-[11px] text-secondary">
                  Detour noted for nearby drivers.
                </p>
              </div>

              {/* Node 3 */}
              <div className="p-3 rounded border border-outline-variant/60 bg-surface space-y-1 relative">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-secondary">03 DETECTION</span>
                  <span className="material-symbols-outlined !text-[14px] text-primary" aria-hidden="true">
                    check_circle
                  </span>
                </div>
                <div className="font-bold text-xs text-on-surface">
                  Better Screening
                </div>
                <p className="text-[11px] text-secondary">
                  Future trips through same corridor cleared without false alarms.
                </p>
              </div>
            </div>

            {/* Loop indicator bar */}
            <div className="p-2.5 rounded bg-surface-container-low border border-outline-variant/60 flex flex-wrap items-center justify-between gap-2 text-[11px]">
              <span className="text-secondary flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-primary" />
                Rules update from resolved cases.
              </span>
              <span className="font-mono text-primary font-semibold">
                Feedback loop complete
              </span>
            </div>
          </Card>
        </div>
      </div>

      {/* Final CTA Band */}
      <div className="max-w-6xl mx-auto px-4">
        <div className="rounded-xl border border-primary/30 bg-surface-container-low p-8 sm:p-12 text-center space-y-4 shadow-sm">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-container-lowest border border-outline-variant/60 text-xs text-primary font-semibold">
            <span className="material-symbols-outlined !text-[14px]" aria-hidden="true">
              shield
            </span>
            <span>Ready to try it?</span>
          </div>

          <h3 className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface">
            Ready to protect your fleet with fair fraud defense?
          </h3>

          <p className="max-w-xl mx-auto text-sm text-secondary leading-relaxed">
            Try the live demo now or explore with sample data.
          </p>

          <div className="pt-2 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/workplace"
              className="inline-flex min-h-[44px] items-center gap-1.5 px-6 py-2 rounded bg-primary text-on-primary text-sm font-semibold hover:bg-primary-container active:scale-[0.99] transition-all shadow-xs"
            >
              <span>Try live demo</span>
              <span className="material-symbols-outlined !text-[16px]" aria-hidden="true">
                arrow_forward
              </span>
            </Link>

            <Link
              href="/sign-up"
              className="inline-flex min-h-[44px] items-center px-6 py-2 rounded border border-outline-variant bg-surface-container-lowest text-on-surface text-sm font-semibold hover:bg-surface-container transition-colors"
            >
              Create organization
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
