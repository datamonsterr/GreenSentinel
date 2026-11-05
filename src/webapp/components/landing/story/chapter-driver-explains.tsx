"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { renderChatContent } from "@/components/ui/chat-widgets";
import { DRIVER_CHAT_SCRIPT, QUICK_REPLY_CHIPS, ChatStep } from "../fixtures";

interface ChapterDriverExplainsProps {
  reducedMotion: boolean;
}

export function ChapterDriverExplains({
  reducedMotion,
}: ChapterDriverExplainsProps) {
  // If reducedMotion is true, immediately display all scripted messages
  const [messages, setMessages] = useState<ChatStep[]>(() =>
    reducedMotion ? [...DRIVER_CHAT_SCRIPT] : []
  );
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const [started, setStarted] = useState<boolean>(reducedMotion);
  const timeoutsRef = useRef<NodeJS.Timeout[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const clearAllTimeouts = () => {
    timeoutsRef.current.forEach(clearTimeout);
    timeoutsRef.current = [];
  };

  const startAutoplay = () => {
    clearAllTimeouts();
    setMessages([]);
    setIsTyping(true);

    if (reducedMotion) {
      setMessages([...DRIVER_CHAT_SCRIPT]);
      setIsTyping(false);
      setStarted(true);
      return;
    }

    // Step 1: Typing -> Bubble 1 (Assistant)
    const t1 = setTimeout(() => {
      setIsTyping(false);
      setMessages([DRIVER_CHAT_SCRIPT[0]]);

      // Step 2: Bubble 2 (Driver reply)
      const t2 = setTimeout(() => {
        setMessages((prev) => [...prev, DRIVER_CHAT_SCRIPT[1]]);
        setIsTyping(true);

        // Step 3: Typing -> Bubble 3 (Traffic Corroboration widget)
        const t3 = setTimeout(() => {
          setIsTyping(false);
          setMessages((prev) => [...prev, DRIVER_CHAT_SCRIPT[2]]);
          setStarted(true);
        }, 900);
        timeoutsRef.current.push(t3);
      }, 700);
      timeoutsRef.current.push(t2);
    }, 600);

    timeoutsRef.current.push(t1);
  };

  useEffect(() => {
    if (reducedMotion) return;

    // IntersectionObserver to trigger autoplay when entered view
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      startAutoplay();
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started) {
          startAutoplay();
        }
      },
      { threshold: 0.25 }
    );
    observer.observe(el);

    return () => {
      observer.disconnect();
      clearAllTimeouts();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reducedMotion]);

  // Click quick reply chip: appends the selected reply into chat
  const handleChipClick = (chipText: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: "driver",
        text: chipText,
      },
      {
        id: `ack-${Date.now()}`,
        role: "assistant",
        text: `Statement recorded: "${chipText}". Forwarded to the analyst queue for confirmation.`,
      },
    ]);
  };

  const handleReplay = () => {
    setStarted(false);
    startAutoplay();
  };

  return (
    <section
      id="driver-explains"
      aria-labelledby="heading-driver-explains"
      className="scroll-mt-20 py-12 border-b border-outline-variant/60"
      ref={containerRef}
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center max-w-6xl mx-auto px-4">
        {/* Narrative Left */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center gap-1.5 text-primary font-mono text-xs">
            <span className="px-1.5 py-0.5 rounded bg-surface-container font-semibold">
              03
            </span>
            <span className="font-semibold uppercase tracking-wider">
              Driver explains
            </span>
          </div>

          <h2
            id="heading-driver-explains"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-on-surface"
          >
            Driver explains
          </h2>

          <p className="text-base text-secondary leading-relaxed">
            Drivers explain delays before any penalty. The support assistant listens in chat.
          </p>

          <div className="pt-2 flex flex-col gap-2">
            <p className="text-xs text-secondary font-mono">
              <span className="font-semibold text-primary">Next:</span> Analyst decides
            </p>
            <div>
              <Link
                href="/driver"
                className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline cursor-pointer"
              >
                <span>Open Driver Portal</span>
                <span className="material-symbols-outlined !text-[14px]" aria-hidden="true">
                  arrow_forward
                </span>
              </Link>
            </div>
          </div>
        </div>

        {/* UI Frame Right: Driver Support Chat Look */}
        <div className="lg:col-span-7">
          <Card className="p-4 shadow-sm space-y-3">
            {/* Chat Header */}
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                  <span className="material-symbols-outlined !text-[16px]" aria-hidden="true">
                    smart_toy
                  </span>
                </div>
                <div>
                  <div className="text-xs font-bold text-on-surface">
                    Driver Care Support
                  </div>
                  <div className="text-[10px] text-secondary font-mono">
                    Driver: Phạm Văn Bình (#DRV-8492)
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={handleReplay}
                  aria-label="Replay conversation"
                  className="h-6 text-[11px] px-2 gap-1 cursor-pointer"
                >
                  <span className="material-symbols-outlined !text-[12px]" aria-hidden="true">
                    replay
                  </span>
                  Replay
                </Button>
                <Badge variant="secondary" className="text-[10px]">
                  Sample data
                </Badge>
              </div>
            </div>

            {/* Chat Stream Window */}
            <div
              className="bg-surface rounded border border-outline-variant/60 p-3 min-h-[260px] max-h-[360px] overflow-y-auto space-y-2.5 text-xs"
              role="log"
              aria-label="Driver support chat transcript"
              aria-live="polite"
            >
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex gap-2 ${
                    msg.role === "driver" ? "justify-end" : "justify-start"
                  }`}
                >
                  {msg.role === "assistant" && (
                    <div className="w-5 h-5 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                      <span className="material-symbols-outlined !text-[12px]" aria-hidden="true">
                        smart_toy
                      </span>
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] rounded px-3 py-2 leading-relaxed ${
                      msg.role === "driver"
                        ? "bg-primary text-on-primary font-medium"
                        : "bg-surface-container-lowest border border-outline-variant/60 text-on-surface shadow-2xs"
                    }`}
                  >
                    {msg.hasTrafficWidget
                      ? renderChatContent(msg.text)
                      : msg.text}
                  </div>
                </div>
              ))}

              {/* Typing indicator */}
              {isTyping && (
                <div className="flex items-center gap-1.5 text-secondary pl-7">
                  <span className="text-[10px] font-mono">Assistant is typing</span>
                  <div className="flex gap-1" aria-label="Typing dots">
                    <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" />
                    <span
                      className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce"
                      style={{ animationDelay: "150ms" }}
                    />
                    <span
                      className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce"
                      style={{ animationDelay: "300ms" }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Quick reply chips */}
            <div className="pt-2 border-t border-outline-variant/60">
              <span className="text-[10px] font-mono text-secondary block mb-1.5">
                Quick reply chips:
              </span>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Driver quick replies">
                {QUICK_REPLY_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => handleChipClick(chip)}
                    className="px-2.5 py-1 rounded-full text-xs bg-surface-container border border-outline-variant text-on-surface hover:border-primary hover:bg-surface-container-high transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>

            {/* Footer link */}
            <div className="flex items-center justify-between pt-1 text-xs">
              <span className="text-secondary text-[11px]">
                Driver statements link directly to the review cockpit
              </span>
              <Link
                href="/driver"
                className="font-medium text-primary hover:underline flex items-center gap-1"
              >
                <span>Open Driver Care</span>
                <span className="material-symbols-outlined !text-[13px]" aria-hidden="true">
                  open_in_new
                </span>
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </section>
  );
}
