"use client";

import React from "react";
import Link from "next/link";

export function LandingHeader() {
  return (
    <header className="sticky top-0 z-50 w-full h-12 border-b border-outline-variant bg-surface-container-lowest/95 backdrop-blur-xs px-4 sm:px-6">
      <div className="mx-auto flex h-full max-w-6xl items-center justify-between">
        {/* Logo / Brand - Pure vector shield icon per Design.md Rule 2 */}
        <div className="flex items-center gap-2">
          <Link href="/" className="flex items-center gap-1.5 text-primary focus-visible:outline-2 focus-visible:outline-primary">
            <span className="material-symbols-outlined !text-[20px] text-primary" aria-hidden="true">
              shield
            </span>
            <span className="text-sm font-bold tracking-tight text-on-surface">
              GreenSentinel
            </span>
          </Link>
        </div>

        {/* Navigation links */}
        <nav aria-label="Primary" className="hidden md:flex items-center gap-6 text-xs font-medium text-secondary">
          <a href="#trip-ends" className="hover:text-on-surface transition-colors">
            Trip ends
          </a>
          <a href="#ai-checks" className="hover:text-on-surface transition-colors">
            AI checks
          </a>
          <a href="#driver-explains" className="hover:text-on-surface transition-colors">
            Driver care
          </a>
          <a href="#analyst-decides" className="hover:text-on-surface transition-colors">
            Cockpit
          </a>
          <a href="#features" className="hover:text-on-surface transition-colors">
            Features
          </a>
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-3">
          <Link
            href="/sign-in"
            className="text-xs font-semibold text-secondary hover:text-on-surface transition-colors px-2 py-1"
          >
            Sign in
          </Link>
          <Link
            href="/workplace"
            className="inline-flex min-h-[32px] items-center px-3 py-1 rounded bg-primary text-on-primary text-xs font-semibold hover:bg-primary-container transition-colors shadow-2xs"
          >
            Try live demo
          </Link>
        </div>
      </div>
    </header>
  );
}
