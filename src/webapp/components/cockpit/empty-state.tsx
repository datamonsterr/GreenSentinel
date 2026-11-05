"use client";

import React from "react";
import { Inbox, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/locale";
import { IconTile } from "./icon-tile";
import { cockpitMessages } from "./messages";

/** Designed "No data yet" block: never "Unavailable" or "undefined". */
export function EmptyState({ icon = Inbox, title, hint, compact = false, className }: {
  icon?: LucideIcon;
  title?: string;
  hint?: string;
  compact?: boolean;
  className?: string;
}) {
  const { locale } = useLocale();
  return (
    <div role="status" className={cn("flex flex-col items-center justify-center gap-2 text-center", compact ? "py-3" : "py-8", className)}>
      <IconTile icon={icon} size={compact ? "sm" : "lg"} />
      <p className="text-sm font-semibold text-slate-800">{title ?? cockpitMessages[locale].noData}</p>
      {hint && <p className="max-w-sm text-xs leading-relaxed text-slate-500">{hint}</p>}
    </div>
  );
}
