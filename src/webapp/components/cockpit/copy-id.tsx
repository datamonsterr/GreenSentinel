"use client";

import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyId({ id, label, displayId }: { id: string; label: string; displayId?: string }) {
  const [copied, setCopied] = useState(false);
  const text = displayId ?? id;
  const short = text.length > 18 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text;
  const copy = async () => {
    let successful = false;
    try {
      await navigator.clipboard.writeText(id);
      successful = true;
    } catch {
      const area = document.createElement("textarea");
      try {
        area.value = id;
        area.setAttribute("readonly", "");
        document.body.appendChild(area);
        area.select();
        successful = document.execCommand("copy");
      } catch {
        successful = false;
      } finally {
        area.remove();
      }
    }
    if (!successful) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  const showsHash = !text.startsWith("#");
  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      onClick={(event) => { event.stopPropagation(); void copy(); }}
      title={id}
      aria-label={`${label}: ${id}`}
      className="inline-flex min-w-0 max-w-36 shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] leading-4 text-slate-700 hover:bg-emerald-50 focus-visible:outline-emerald-600"
    >
      {showsHash && <span aria-hidden="true" className="shrink-0 text-slate-400">#</span>}
      <span className="truncate">{short}</span>
      <Icon aria-hidden="true" size={12} className="block shrink-0 text-slate-400" />
      <span className="sr-only">{copied ? "✓" : ""}</span>
    </button>
  );
}
