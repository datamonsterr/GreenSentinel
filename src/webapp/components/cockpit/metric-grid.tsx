import React from "react";
import { cn } from "@/lib/utils";

/**
 * Column spans (out of 12) for each cell: full rows share width equally and a
 * trailing partial row stretches to fill the line (2 → halves, 1 → full).
 */
export function metricGridSpans(count: number, columns = 3): number[] {
  const full = Math.floor(count / columns) * columns;
  const remainder = count - full;
  return Array.from({ length: count }, (_, index) => 12 / (index < full ? columns : remainder));
}

// Static class names so Tailwind keeps every span.
const spanClass: Record<number, string> = {
  3: "sm:col-span-3",
  4: "sm:col-span-4",
  6: "sm:col-span-6",
  12: "sm:col-span-12",
};

export function MetricGrid({ children, columns = 3, className }: { children: React.ReactNode; columns?: 3 | 4; className?: string }) {
  const items = React.Children.toArray(children).filter(React.isValidElement);
  const spans = metricGridSpans(items.length, columns);
  return (
    <div className={cn("grid grid-cols-1 gap-3 sm:grid-cols-12", className)}>
      {items.map((item, index) => (
        <div key={item.key ?? index} data-span={spans[index]} className={cn("min-w-0", spanClass[spans[index]])}>
          {item}
        </div>
      ))}
    </div>
  );
}
