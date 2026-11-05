"use client";

import React, { useRef, useState, useEffect } from "react";
import Lenis from "lenis";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import "lenis/dist/lenis.css";

import { LandingHeader } from "./story/header";
import { LandingFooter } from "./story/footer";
import { JourneyRail } from "./story/journey-rail";
import { HeroSection } from "./story/hero-section";
import { ChapterTripEnds } from "./story/chapter-trip-ends";
import { ChapterAIChecks } from "./story/chapter-ai-checks";
import { ChapterDriverExplains } from "./story/chapter-driver-explains";
import { ChapterAnalystDecides } from "./story/chapter-analyst-decides";
import { ChapterTeamLearns } from "./story/chapter-team-learns";
import { FeaturesSection } from "./story/features-section";
import { JOURNEY_STEPS } from "./fixtures";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger, useGSAP);
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(query.matches);
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  return reduced;
}

export function LandingPage() {
  const reducedMotion = usePrefersReducedMotion();
  const rootRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const lenisRef = useRef<Lenis | null>(null);

  const [activeStep, setActiveStep] = useState<number>(0);
  const [scrollProgress, setScrollProgress] = useState<number>(0);
  const [showChevron, setShowChevron] = useState<boolean>(true);

  // Synchronize Lenis with GSAP ScrollTrigger per ui.md standards
  useEffect(() => {
    if (reducedMotion || typeof window === "undefined") return;

    let lenis: Lenis | null = null;
    let tickerCb: ((time: number) => void) | null = null;

    try {
      lenis = new Lenis({
        wrapper: rootRef.current ?? undefined,
        content: contentRef.current ?? undefined,
        autoRaf: false,
      });
      lenisRef.current = lenis;

      lenis.on("scroll", ScrollTrigger.update);
      tickerCb = (time: number) => {
        lenis?.raf(time * 1000);
      };
      gsap.ticker.add(tickerCb);
      gsap.ticker.lagSmoothing(0);
    } catch {
      // Graceful fallback for headless/test environments
    }

    return () => {
      if (tickerCb) gsap.ticker.remove(tickerCb);
      if (lenis) {
        try {
          lenis.destroy();
        } catch {}
        lenisRef.current = null;
      }
    };
  }, [reducedMotion]);

  // Motion animation logic with @gsap/react useGSAP
  useGSAP(
    () => {
      if (reducedMotion || typeof window === "undefined") return;

      try {
        const scrollerEl = rootRef.current ?? undefined;
        const pinDistance = Math.round(
          (typeof window !== "undefined" ? window.innerHeight : 800) * 0.7
        );

        // 1. Create pin triggers BEFORE step/progress triggers per Item 4 & 5
        const chapterIds = [
          "#trip-ends",
          "#ai-checks",
          "#driver-explains",
          "#analyst-decides",
          "#team-learns",
        ];
        chapterIds.forEach((id) => {
          const el = document.querySelector(id);
          if (el) {
            ScrollTrigger.create({
              trigger: el,
              scroller: scrollerEl,
              start: "top 12%",
              end: () => `+=${pinDistance}`,
              pin: true,
              pinSpacing: true,
              refreshPriority: 10,
            });
          }
        });

        // 2. Chapter 1: Draw actual GPS path on scroll with scrub while pinned
        const gpsEl = document.getElementById("gps-actual-path");
        if (gpsEl) {
          gsap.fromTo(
            gpsEl,
            { strokeDashoffset: 600 },
            {
              strokeDashoffset: 0,
              ease: "none",
              scrollTrigger: {
                trigger: "#trip-ends",
                scroller: scrollerEl,
                start: "top 12%",
                end: () => `+=${pinDistance}`,
                scrub: 1,
                refreshPriority: 8,
              },
            }
          );
        }

        // 3. Active rail step sync
        JOURNEY_STEPS.forEach((step, idx) => {
          ScrollTrigger.create({
            trigger: `#${step.id}`,
            scroller: scrollerEl,
            start: "top center",
            end: "bottom center",
            refreshPriority: 1,
            onEnter: () => setActiveStep(idx),
            onEnterBack: () => setActiveStep(idx),
          });
        });

        // 4. Overall scroll progress indicator for left rail
        if (contentRef.current) {
          ScrollTrigger.create({
            trigger: contentRef.current,
            scroller: scrollerEl,
            start: "top top",
            end: "bottom bottom",
            refreshPriority: 1,
            onUpdate: (self) => {
              setScrollProgress(self.progress);
              setShowChevron(self.progress < 0.92);
            },
          });
        }

        ScrollTrigger.refresh();

        return () => {
          ScrollTrigger.getAll().forEach((t) => t.kill());
        };
      } catch {
        // Fallback for non-browser environments
      }
    },
    { scope: rootRef, dependencies: [reducedMotion], revertOnUpdate: true }
  );

  const handleStepClick = (stepId: string, index: number) => {
    setActiveStep(index);
    const target = document.getElementById(stepId);
    if (lenisRef.current && typeof lenisRef.current.scrollTo === "function") {
      try {
        lenisRef.current.scrollTo(target || `#${stepId}`);
        return;
      } catch {}
    }
    target?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    // Self-scrollable root: App shell locks body overflow, so landing scrolls here
    <div
      ref={rootRef}
      className="h-full min-h-screen overflow-y-auto bg-[#f8f9ff] text-[#0b1c30] selection:bg-primary selection:text-on-primary"
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:outline-[#0058be] focus:outline-3"
      >
        Skip to content
      </a>

      {/* Global Landing Header */}
      <LandingHeader />

      {/* Sticky Left Journey Rail */}
      <JourneyRail
        activeStep={activeStep}
        scrollProgress={scrollProgress}
        onStepClick={handleStepClick}
        showChevron={showChevron}
      />

      {/* Main Story Canvas (Offset for left rail on desktop) */}
      <main id="main" ref={contentRef} className="lg:pl-56 min-h-screen">
        {/* 0. Hero */}
        <HeroSection />

        {/* 1. Trip ends */}
        <ChapterTripEnds reducedMotion={reducedMotion} />

        {/* 2. AI checks every trip */}
        <ChapterAIChecks reducedMotion={reducedMotion} />

        {/* 3. Driver explains */}
        <ChapterDriverExplains reducedMotion={reducedMotion} />

        {/* 4. Analyst decides */}
        <ChapterAnalystDecides reducedMotion={reducedMotion} />

        {/* 5. Team learns */}
        <ChapterTeamLearns />

        {/* All Features Section */}
        <FeaturesSection />

        {/* Landing Footer */}
        <LandingFooter />
      </main>
    </div>
  );
}
