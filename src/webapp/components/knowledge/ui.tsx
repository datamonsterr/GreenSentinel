"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { statusTone, type Tone } from "@/lib/status-tone";
import { parseApiError, type FormulaIssue } from "@/lib/knowledge-client";

export const btn = {
  primary: "inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3.5 text-[13px] font-bold text-white transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50",
  secondary: "inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-gs-line-2 bg-white px-3.5 text-[13px] font-semibold text-gs-ink-2 transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50",
  danger: "inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-gs-red/30 bg-gs-red-soft px-3.5 text-[13px] font-bold text-gs-red transition-colors hover:bg-gs-red/10 disabled:cursor-not-allowed disabled:opacity-50",
  ghost: "inline-flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-md px-2 text-[12px] font-semibold text-gs-mute-2 transition-colors hover:bg-surface",
};

export const inputCls =
  "h-9 w-full rounded-lg border border-gs-line-2 bg-white px-3 text-[13px] text-on-surface placeholder:text-gs-mute focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25 disabled:bg-surface disabled:text-gs-mute-2";
export const areaCls =
  "w-full rounded-lg border border-gs-line-2 bg-white px-3 py-2 text-[13px] text-on-surface placeholder:text-gs-mute focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25 disabled:bg-surface disabled:text-gs-mute-2";

export function Chip({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return <span title={title} className={`gs-tone pill ${statusTone(tone)}`}>{children}</span>;
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-gs-line bg-white shadow-xs ${className}`}>{children}</section>;
}

export function SectionTitle({ icon, title, hint, right }: { icon?: string; title: string; hint?: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <span className="material-symbols-outlined mt-0.5 text-[20px] text-primary">{icon}</span>}
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold text-on-surface">{title}</h2>
          {hint && <p className="mt-0.5 text-[12px] text-gs-mute-2">{hint}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-gs-mute">{hint}</span>}
    </label>
  );
}

export function Notice({ kind, children, issues }: { kind: "error" | "ok" | "info"; children?: React.ReactNode; issues?: FormulaIssue[] }) {
  const tone = kind === "error" ? "border-gs-red/30 bg-gs-red-soft text-gs-red"
    : kind === "ok" ? "border-gs-green/30 bg-gs-green-soft text-gs-green-ink" : "border-gs-line-2 bg-gs-cyan-soft text-gs-ink-2";
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border px-3 py-2 text-[12.5px] ${tone}`}>
      {children}
      {issues && issues.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {issues.map((i, n) => (
            <li key={n}><span className="font-mono text-[11px]">{i.path ? `${i.path}: ` : ""}{i.code}</span> {i.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Load data on mount / when deps change; `reload` refetches. Errors are surfaced as strings. */
export function useLoad<T>(fn: () => Promise<T>, deps: React.DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  const run = useCallback(() => {
    setLoading(true);
    fnRef.current().then((d) => { setData(d); setError(null); })
      .catch((e) => setError(parseApiError(e).message))
      .finally(() => setLoading(false));
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
  useEffect(() => { run(); }, deps);
  return { data, error, loading, reload: run, setData };
}

export function fmtDate(iso: string | null | undefined, locale: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(locale === "vi" ? "vi-VN" : "en-GB", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
