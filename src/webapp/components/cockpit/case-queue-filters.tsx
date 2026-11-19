"use client";

import React, { useState } from "react";
import type { Locale } from "@/lib/locale";
import { caseStatusTone } from "@/lib/status-tone";
import {
  EMPTY_FILTERS, QUEUE_STATUSES, activeFilterCount, distinct, queueText, statusCounts,
  type QueueFilters, type QueueRow,
} from "@/lib/case-queue";

const field = "h-8 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100";

interface Props {
  filters: QueueFilters;
  onChange: (next: QueueFilters) => void;
  rows: QueueRow[];
  locale: Locale;
  expanded: boolean;
}

function Facets({ filters, onChange, rows, locale, inline }: Omit<Props, "expanded"> & { inline: boolean }) {
  const t = queueText[locale];
  const set = (p: Partial<QueueFilters>) => onChange({ ...filters, ...p });
  const counts = statusCounts(rows, filters);
  const select = (label: string, key: "priority" | "category" | "assignee", options: string[]) => (
    <select aria-label={label} value={filters[key]} onChange={e => set({ [key]: e.target.value })} className={`${field} ${inline ? "w-36" : "w-full"}`}>
      <option value="">{label}: {t.all}</option>
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
  return (
    <div className={inline ? "flex flex-wrap items-center gap-2" : "space-y-2"}>
      <div role="group" aria-label={t.status} className="flex flex-wrap gap-1">
        {QUEUE_STATUSES.map(s => {
          const on = filters.statuses.includes(s);
          return (
            <button
              key={s}
              type="button"
              aria-pressed={on}
              onClick={() => set({ statuses: on ? filters.statuses.filter(x => x !== s) : [...filters.statuses, s] })}
              className={`gs-tone pill !text-[11px] ${on ? caseStatusTone(s) + " ring-1 ring-current" : "bg-slate-100 text-slate-600"}`}
            >
              {t[s]} <span className="ml-1 tabular-nums">{counts[s] ?? 0}</span>
            </button>
          );
        })}
      </div>
      <div className={inline ? "flex flex-wrap items-center gap-2" : "grid grid-cols-2 gap-2"}>
        {select(t.priority, "priority", ["P0", "P1", "P2"])}
        {select(t.category, "category", distinct(rows.map(r => r.category)))}
        {select(t.assignee, "assignee", distinct(rows.map(r => r.assignedAnalystName)))}
        <label className="flex items-center gap-1 text-[11px] text-slate-500">{t.from}
          <input type="date" aria-label={t.from} value={filters.from} onChange={e => set({ from: e.target.value })} className={field} />
        </label>
        <label className="flex items-center gap-1 text-[11px] text-slate-500">{t.to}
          <input type="date" aria-label={t.to} value={filters.to} onChange={e => set({ to: e.target.value })} className={field} />
        </label>
        {activeFilterCount(filters) > 0 && (
          <button type="button" onClick={() => onChange({ ...EMPTY_FILTERS, search: filters.search, availability: filters.availability })} className="text-[11px] font-semibold text-cyan-700 hover:underline">
            {t.clear}
          </button>
        )}
      </div>
    </div>
  );
}

/** Expanded: inline bar. Collapsed: compact button with active-filter badge opening a popover. */
export function QueueFilterBar(props: Props) {
  const [open, setOpen] = useState(false);
  const t = queueText[props.locale];
  if (props.expanded) return <Facets {...props} inline />;
  const n = activeFilterCount(props.filters);
  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === "Escape") setOpen(false); }}
        className={`${field} inline-flex w-full items-center justify-between gap-1 font-semibold`}
      >
        <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="material-symbols-outlined text-sm">filter_list</span>{t.filters}</span>
        {n > 0 && <span className="gs-tone pill t-cyan !px-1.5 !py-0 !text-[11px]">{n}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label={t.filters} onKeyDown={e => { if (e.key === "Escape") setOpen(false); }} className="absolute left-0 right-0 top-9 z-20 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
          <Facets {...props} inline={false} />
        </div>
      )}
    </div>
  );
}
