"use client";

import React, { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface ChapterTripEndsProps {
  reducedMotion: boolean;
}

export function ChapterTripEnds({ reducedMotion }: ChapterTripEndsProps) {
  const gpsPathRef = useRef<SVGPathElement>(null);

  // SVG route path coordinates
  // Planned: straight diagonal-ish curve
  // Actual detour: loop curving downwards around Ba Trieu
  const plannedPathD = "M 40 180 C 120 170, 220 150, 320 80 L 480 50";
  const actualGpsPathD = "M 40 180 C 130 190, 190 220, 260 210 C 330 200, 390 120, 480 50";

  return (
    <section
      id="trip-ends"
      aria-labelledby="heading-trip-ends"
      className="scroll-mt-20 py-12 border-b border-outline-variant/60"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-6xl mx-auto px-4">
        {/* Narrative Left */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center gap-1.5 text-primary font-mono text-xs">
            <span className="px-1.5 py-0.5 rounded bg-surface-container font-semibold">
              01
            </span>
            <span className="font-semibold uppercase tracking-wider">
              Trip ends
            </span>
          </div>

          <h2
            id="heading-trip-ends"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface"
          >
            Trip ends
          </h2>

          <p className="text-base text-secondary leading-relaxed">
            Every completed ride sends its route. We compare it to the map.
          </p>

          <div className="pt-2">
            <p className="text-xs text-secondary font-mono">
              <span className="font-semibold text-primary">Next:</span> AI checks every trip
            </p>
          </div>
        </div>

        {/* UI Frame Right */}
        <div className="lg:col-span-7">
          <Card className="p-4 shadow-sm">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3 mb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
                  route
                </span>
                <span className="font-mono text-xs font-bold text-on-surface">
                  #TRX-94021
                </span>
                <span className="text-xs text-secondary hidden sm:inline">
                  Hanoi Central → Long Biên Bridge
                </span>
              </div>
              <Badge variant="secondary" className="text-[10px]">
                Sample data
              </Badge>
            </div>

            {/* SVG Map Canvas */}
            <div
              className="relative bg-surface rounded border border-outline-variant/60 h-64 overflow-hidden p-3"
              data-testid="trip-map-card"
            >
              {/* Background grid */}
              <div
                className="absolute inset-0 opacity-15 pointer-events-none"
                style={{
                  backgroundSize: "20px 20px",
                  backgroundImage:
                    "linear-gradient(to right, #6d7a72 1px, transparent 1px), linear-gradient(to bottom, #6d7a72 1px, transparent 1px)",
                }}
              />

              {/* Map SVG lines */}
              <svg
                viewBox="0 0 520 240"
                className="absolute inset-0 w-full h-full"
                xmlns="http://www.w3.org/2000/svg"
              >
                {/* Planned route - blue dashed */}
                <path
                  d={plannedPathD}
                  fill="none"
                  stroke="#0058be"
                  strokeWidth="3"
                  strokeDasharray="6 4"
                />

                {/* Actual GPS path - drawn on scroll or static in reduced motion */}
                <path
                  ref={gpsPathRef}
                  id="gps-actual-path"
                  d={actualGpsPathD}
                  fill="none"
                  stroke="#ba1a1a"
                  strokeWidth="3.5"
                  strokeLinecap="round"
                  style={{
                    strokeDasharray: 600,
                    strokeDashoffset: reducedMotion ? 0 : 0, // GSAP controls this in active motion
                  }}
                />

                {/* Breadcrumbs on detour */}
                <circle cx="160" cy="205" r="4" fill="#ba1a1a" />
                <circle cx="210" cy="215" r="4" fill="#ba1a1a" />
                <circle cx="260" cy="210" r="4" fill="#ba1a1a" />

                {/* Origin Pin */}
                <g transform="translate(40, 180)">
                  <circle r="6" fill="#006948" />
                  <circle r="2.5" fill="#ffffff" />
                </g>

                {/* Destination Pin */}
                <g transform="translate(480, 50)">
                  <circle r="6" fill="#0058be" />
                  <circle r="2.5" fill="#ffffff" />
                </g>
              </svg>

              {/* Map Overlays */}
              <div className="relative z-10 flex flex-col justify-between h-full pointer-events-none text-xs">
                <div className="flex justify-between items-start">
                  <div className="bg-surface-container-lowest/90 border border-outline-variant/60 rounded px-2 py-1 shadow-xs backdrop-blur-xs">
                    <span className="text-[10px] text-secondary block">Origin</span>
                    <span className="font-semibold text-on-surface">Hanoi Central</span>
                  </div>
                  <div className="bg-error-container/90 border border-error/30 rounded px-2 py-1 text-on-error-container font-semibold shadow-xs">
                    Detour detected (+1.4 km)
                  </div>
                </div>

                <div className="flex justify-between items-end">
                  <div className="bg-surface-container-lowest/90 border border-outline-variant/60 rounded px-2 py-1 flex items-center gap-3 text-[11px] shadow-xs">
                    <span className="flex items-center gap-1 text-tertiary font-medium">
                      <span className="w-2 h-0.5 bg-tertiary inline-block" /> Planned corridor
                    </span>
                    <span className="flex items-center gap-1 text-error font-medium">
                      <span className="w-2 h-0.5 bg-error inline-block" /> Actual GPS trace
                    </span>
                  </div>
                  <div className="bg-surface-container-lowest/90 border border-outline-variant/60 rounded px-2 py-1 shadow-xs">
                    <span className="text-[10px] text-secondary block">Destination</span>
                    <span className="font-semibold text-on-surface">Long Biên Bridge</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Readout strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 pt-2">
              <div className="p-2 rounded bg-surface-container-low border border-outline-variant/60">
                <span className="text-secondary text-[10px] block font-mono">Planned</span>
                <span className="font-mono text-xs font-bold text-on-surface">4.8 km</span>
              </div>
              <div className="p-2 rounded bg-surface-container-low border border-outline-variant/60">
                <span className="text-secondary text-[10px] block font-mono">Actual</span>
                <span className="font-mono text-xs font-bold text-error">6.2 km</span>
              </div>
              <div className="p-2 rounded bg-surface-container-low border border-outline-variant/60">
                <span className="text-secondary text-[10px] block font-mono">Detour</span>
                <span className="font-mono text-xs font-bold text-error">+1.4 km</span>
              </div>
              <div className="p-2 rounded bg-surface-container-low border border-outline-variant/60">
                <span className="text-secondary text-[10px] block font-mono">Mean Speed</span>
                <span className="font-mono text-xs font-bold text-on-surface">24 km/h</span>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </section>
  );
}
