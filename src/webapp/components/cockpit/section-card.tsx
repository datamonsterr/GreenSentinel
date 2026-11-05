import React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconTile, type Tone } from "./icon-tile";

export function SectionCard({ icon, tone = "neutral", title, subtitle, right, children, className, bodyClassName, headingLevel = 2, ...rest }: {
  icon: LucideIcon;
  tone?: Tone;
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  headingLevel?: 2 | 3;
} & Omit<React.HTMLAttributes<HTMLElement>, "title">) {
  const Heading = `h${headingLevel}` as const;
  return (
    <section aria-label={title} className={cn("flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white shadow-xs", className)} {...rest}>
      <header className="flex min-w-0 items-center gap-3 border-b border-slate-100 p-3">
        <IconTile icon={icon} tone={tone} />
        <div className="min-w-0 flex-1">
          <Heading className="truncate text-sm font-semibold text-slate-900">{title}</Heading>
          {subtitle && <p className="truncate text-xs text-slate-500">{subtitle}</p>}
        </div>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </header>
      {children !== undefined && <div className={cn("min-w-0 p-3", bodyClassName)}>{children}</div>}
    </section>
  );
}
