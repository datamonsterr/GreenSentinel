"use client";

import React from "react";
import { JOURNEY_STEPS } from "../fixtures";

interface JourneyRailProps {
  activeStep: number;
  scrollProgress: number; // 0 to 1
  onStepClick: (stepId: string, index: number) => void;
  showChevron: boolean;
}

export function JourneyRail({
  activeStep,
  onStepClick,
  showChevron,
}: JourneyRailProps) {
  const isFinalSection = activeStep >= JOURNEY_STEPS.length - 1;
  const shouldShowChevron = showChevron && !isFinalSection;
  const progressPercent = Math.min(
    100,
    Math.max(0, (activeStep / (JOURNEY_STEPS.length - 1)) * 100)
  );

  return (
    <aside
      aria-label="Story Journey Rail"
      className="fixed left-0 top-12 bottom-0 w-56 z-40 hidden lg:flex flex-col justify-between p-3 bg-surface-container-low border-r border-outline-variant select-none"
    >
      <div className="space-y-3">
        <div className="px-2 py-1 border-b border-outline-variant">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-secondary">
              Your journey
            </span>
          </div>
          <p className="text-[10px] font-mono text-secondary">
            5 quick steps
          </p>
        </div>

        {/* Progress rail navigation */}
        <nav aria-label="Journey Steps" className="relative flex flex-col gap-1">
          {/* Vertical scrubbed progress bar background & fill */}
          <div className="absolute left-[17px] top-3 bottom-3 w-0.5 bg-outline-variant/40 z-0">
            <div
              className="w-full bg-primary transition-all duration-200 ease-out"
              style={{ height: `${progressPercent}%` }}
            />
          </div>

          {JOURNEY_STEPS.map((step, idx) => {
            const isActive = activeStep === idx;
            const isPassed = activeStep > idx;
            return (
              <button
                key={step.id}
                type="button"
                id={`rail-btn-${step.id}`}
                aria-current={isActive ? "step" : undefined}
                onClick={() => onStepClick(step.id, idx)}
                className={`flex items-center gap-2 px-2 py-2 text-left text-xs font-mono rounded-r transition-all group cursor-pointer ${
                  isActive
                    ? "text-primary bg-surface-container-lowest border-l-2 border-primary font-bold shadow-xs"
                    : "text-secondary hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span
                  className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono font-bold shrink-0 relative z-10 transition-colors shadow-2xs ${
                    isActive
                      ? "bg-primary text-white ring-2 ring-primary/30"
                      : isPassed
                      ? "bg-primary-fixed text-on-primary-fixed border border-primary-fixed-dim"
                      : "bg-white border border-gs-line-2 text-gs-mute-2"
                  }`}
                >
                  {step.number}
                </span>
                <span className="truncate">{step.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Rail Status / Scroll to Continue */}
      <div className="space-y-2 border-t border-outline-variant pt-2">
        <div className="flex items-center justify-between text-[10px] font-mono text-secondary px-1">
          <span className="flex items-center gap-1">
            <span className="material-symbols-outlined !text-[13px] text-primary">
              verified
            </span>
            Live story
          </span>
          <span className="text-secondary">Step {activeStep + 1} of {JOURNEY_STEPS.length}</span>
        </div>

        <div
          className={`flex items-center justify-center gap-1 text-[11px] text-secondary font-medium transition-opacity duration-300 ${
            shouldShowChevron ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <span>Scroll to continue</span>
          <span
            className="material-symbols-outlined !text-[16px] animate-bounce text-primary font-bold"
            aria-hidden="true"
          >
            expand_more
          </span>
        </div>
      </div>
    </aside>
  );
}
