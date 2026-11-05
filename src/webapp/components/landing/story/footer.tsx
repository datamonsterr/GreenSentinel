"use client";

import React from "react";
import Link from "next/link";

export function LandingFooter() {
  return (
    <footer className="w-full border-t border-outline-variant bg-surface-container-lowest py-8 px-4 sm:px-6">
      <div className="mx-auto max-w-6xl flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-secondary">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
            shield
          </span>
          <span className="font-bold text-on-surface">GreenSentinel</span>
          <span>© 2026. Real-time mobility integrity platform.</span>
        </div>

        <div className="flex items-center gap-4">
          <Link href="/workplace" className="hover:text-primary transition-colors">
            Workplace
          </Link>
          <Link href="/driver" className="hover:text-primary transition-colors">
            Driver Care
          </Link>
          <Link href="/test" className="hover:text-primary transition-colors">
            Test Console
          </Link>
          <Link href="/sign-in" className="hover:text-primary transition-colors">
            Sign in
          </Link>
          <Link href="/sign-up" className="hover:text-primary transition-colors">
            Sign up
          </Link>
        </div>
      </div>
    </footer>
  );
}
