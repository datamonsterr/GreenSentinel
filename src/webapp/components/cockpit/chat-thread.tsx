"use client";

import React from "react";
import { Bot, CarFront, MessageSquareOff, UserRound } from "lucide-react";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";
import { EmptyState } from "./empty-state";
import { cockpitMessages, formatClock } from "./messages";

export interface ChatMessage {
  /** "customer" renders on the right; driver, agent and system turns render on the left. */
  role: string;
  text: string;
  occurred_at: string | null;
}

/** Driver bubbles on the left (car avatar), customer bubbles on the right (person avatar). */
export function ChatThread({ messages, driverLabel, emptyHint, className, ...rest }: {
  messages: ChatMessage[];
  driverLabel: string;
  emptyHint?: string;
  className?: string;
  "data-testid"?: string;
}) {
  const { locale } = useLocale();
  const t = cockpitMessages[locale];
  return (
    <div role="log" aria-live="off" className={cn("min-h-0 space-y-3 overflow-y-auto p-3", className)} {...rest}>
      {messages.length ? messages.map((message, index) => {
        const customer = message.role === "customer";
        const Avatar = customer ? UserRound : message.role === "driver" ? CarFront : Bot;
        const speaker = customer ? t.customer : message.role === "driver" ? driverLabel : message.role === "agent" ? t.agent : t.system;
        const time = formatClock(message.occurred_at, locale);
        return (
          <div key={`${message.role}-${index}`} data-align={customer ? "right" : "left"} className={cn("flex items-end gap-2", customer && "flex-row-reverse")}>
            <span aria-hidden="true" className={cn("inline-flex size-8 shrink-0 items-center justify-center rounded-full", customer ? "bg-sky-50 text-sky-700" : "bg-emerald-50 text-emerald-700")}>
              <Avatar size={16} className="block" />
            </span>
            <div className={cn("flex max-w-[75%] min-w-0 flex-col gap-1", customer ? "items-end" : "items-start")}>
              <p className={cn(
                "whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-[13px] leading-relaxed",
                customer ? "rounded-br-sm bg-sky-50 text-slate-800" : "rounded-bl-sm border border-emerald-100 bg-emerald-50/60 text-slate-800",
              )}>
                {message.text}
              </p>
              <span className="text-[11px] text-slate-500">
                {speaker}
                {time && <> · <time dateTime={message.occurred_at ?? undefined} className="font-mono">{time}</time></>}
              </span>
            </div>
          </div>
        );
      }) : <EmptyState icon={MessageSquareOff} hint={emptyHint ?? t.noMessages} />}
    </div>
  );
}
