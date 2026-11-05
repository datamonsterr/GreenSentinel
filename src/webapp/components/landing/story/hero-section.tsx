"use client";

import React from "react";
import Link from "next/link";

export function HeroSection() {
  return (
    <section aria-labelledby="hero-heading" className="pt-16 pb-12 max-w-5xl mx-auto px-4 text-center">
      {/* Live status pill */}
      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface-container border border-outline-variant text-xs">
        <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
        <span className="text-[10px] font-bold text-primary uppercase tracking-wider">
          Live trip check
        </span>
        <span className="text-secondary font-mono text-[11px]">Sample data preview</span>
      </div>

      <h1
        id="hero-heading"
        className="mt-4 text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-on-surface"
      >
        Catch ride fraud. Treat drivers fairly.
      </h1>

      <p className="mt-4 max-w-2xl mx-auto text-base text-secondary leading-relaxed">
        Protect every ride. Give drivers a fair hearing.
      </p>

      {/* CTA cluster */}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/workplace"
          className="inline-flex min-h-[44px] items-center gap-1.5 px-5 py-2 rounded bg-primary text-on-primary text-sm font-semibold hover:bg-primary-container active:scale-[0.99] transition-all shadow-xs"
        >
          <span>Try live demo</span>
          <span className="material-symbols-outlined !text-[16px]" aria-hidden="true">
            arrow_forward
          </span>
        </Link>

        <Link
          href="/sign-up"
          className="inline-flex min-h-[44px] items-center px-5 py-2 rounded border border-outline-variant bg-surface-container-lowest text-on-surface text-sm font-semibold hover:bg-surface-container transition-colors"
        >
          Create organization
        </Link>

        <a
          href="#features"
          className="inline-flex min-h-[44px] items-center px-4 py-2 text-sm font-semibold text-secondary hover:text-on-surface transition-colors"
        >
          See all features
        </a>
      </div>

      {/* Proof strip - clean and honest */}
      <div className="mt-8 pt-4 border-t border-outline-variant/60 flex flex-wrap justify-center items-center gap-x-6 gap-y-2 text-xs text-secondary">
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
            fingerprint
          </span>
          <span>People review flagged cases</span>
        </div>
        <span className="hidden sm:inline text-outline-variant">•</span>
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
            forum
          </span>
          <span>Instant dispute hearing for drivers</span>
        </div>
        <span className="hidden sm:inline text-outline-variant">•</span>
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
            verified
          </span>
          <span>Sample data in all previews</span>
        </div>
      </div>
    </section>
  );
}
