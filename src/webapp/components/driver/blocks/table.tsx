"use client";

import React from "react";
import type { TableBlock } from "@/types/driver-blocks";
import { type BlockLabels } from "./labels";

export interface TableBlockProps extends Omit<TableBlock, "type"> {
  type?: "table";
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function TableBlockComponent({ columns, rows, className = "" }: TableBlockProps) {
  return (
    <div
      className={`overflow-hidden rounded-2xl border border-outline-variant/80 dark:border-slate-800 bg-surface-container-lowest dark:bg-slate-900/90 shadow-sm ${className}`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          {columns && columns.length > 0 && (
            <thead className="bg-surface-container-high/40 dark:bg-slate-800/80 border-b border-outline-variant/60 dark:border-slate-800">
              <tr>
                {columns.map((col, idx) => (
                  <th
                    key={idx}
                    className="py-2.5 px-3.5 text-xs font-semibold text-on-surface-variant dark:text-slate-400 uppercase tracking-wider"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody className="divide-y divide-outline-variant/40 dark:divide-slate-800">
            {rows.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className="hover:bg-surface-container-low/50 dark:hover:bg-slate-800/40 transition-colors"
              >
                {row.map((cell, cellIdx) => (
                  <td
                    key={cellIdx}
                    className="py-2.5 px-3.5 text-on-surface dark:text-slate-200 text-xs sm:text-sm font-medium"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
