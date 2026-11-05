"use client";

import React from "react";
import { History } from "lucide-react";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";
import { formatDuration, segmentDurations, type TimelineEvent } from "@/lib/cockpit-signals";
import { toneDot, toneText } from "./icon-tile";
import { EmptyState } from "./empty-state";
import { cockpitMessages, formatClock } from "./messages";

/** Vertical status timeline; each segment takes its status color and shows time spent until the next status. */
export function EventTimeline({ events, className }: { events: TimelineEvent[]; className?: string }) {
  const { locale } = useLocale();
  const t = cockpitMessages[locale];
  if (!events.length) return <div className={cn("min-h-0 overflow-y-auto p-3", className)}><EmptyState icon={History} hint={t.noEvents} /></div>;
  const durations = segmentDurations(events);
  return (
    <ol className={cn("min-h-0 overflow-y-auto p-3", className)}>
      {events.map((event, index) => {
        const last = index === events.length - 1;
        const time = formatClock(event.timestamp, locale);
        const duration = durations[index];
        return (
          <li key={event.id} data-highlight={event.highlight ? "true" : undefined} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && <span aria-hidden="true" className={cn("absolute left-[7px] top-4 bottom-0 w-0.5 rounded-full opacity-60", toneDot[event.tone])} />}
            <span aria-hidden="true" className={cn("relative mt-0.5 size-4 shrink-0 rounded-full ring-4 ring-white", toneDot[event.tone])} />
            <div className={cn("min-w-0 flex-1 rounded-md", event.highlight && event.tone === "danger" && "-mx-1 -mt-1 bg-red-50 px-1 pt-1 pb-1")}>
              <div className="flex min-w-0 items-start justify-between gap-2">
                <p className={cn("min-w-0 break-words text-[13px] font-semibold leading-snug", event.highlight ? toneText[event.tone] : "text-slate-900")}>{event.label}</p>
                {duration !== null && (
                  <span title={t.duration} className="shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-slate-600">
                    {formatDuration(duration)}
                  </span>
                )}
              </div>
              {time && <time dateTime={event.timestamp ?? undefined} className="font-mono text-[11px] text-slate-500">{time}</time>}
              {event.detail && <p className="mt-0.5 break-words text-xs leading-snug text-slate-600">{event.detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
