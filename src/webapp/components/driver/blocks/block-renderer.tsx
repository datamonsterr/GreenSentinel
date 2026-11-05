"use client";

import React from "react";
import type { ConfirmationBlock, DriverChatBlock } from "@/types/driver-blocks";
import { CaseCard } from "./case-card";
import { TripCard } from "./trip-card";
import { TableBlockComponent } from "./table";
import { ClickableList } from "./clickable-list";
import { LinkBlockComponent } from "./link";
import { StatusPill } from "./status-pill";
import { EvidenceBlockComponent } from "./evidence";
import { NextSteps } from "./next-steps";
import { ConfirmationCard } from "./confirmation-card";
import { type BlockLabels } from "./labels";

export interface BlockRendererProps {
  block?: DriverChatBlock;
  blocks?: DriverChatBlock[];
  onNavigate?: (href: string) => void;
  onPrompt?: (prompt: string) => void;
  onConfirm?: (block: ConfirmationBlock) => void;
  onDecline?: (block: ConfirmationBlock) => void;
  pendingConfirm?: boolean;
  statusLabel?: (statusKey: string) => string;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function BlockRenderer({
  block,
  blocks,
  onNavigate,
  onPrompt,
  onConfirm,
  onDecline,
  pendingConfirm,
  statusLabel,
  labels,
  t,
  className = "",
}: BlockRendererProps) {
  if (blocks && Array.isArray(blocks)) {
    return (
      <div className={`space-y-3.5 ${className}`}>
        {blocks.map((b, idx) => (
          <BlockRenderer
            key={idx}
            block={b}
            onNavigate={onNavigate}
            onPrompt={onPrompt}
            onConfirm={onConfirm}
            onDecline={onDecline}
            pendingConfirm={pendingConfirm}
            statusLabel={statusLabel}
            labels={labels}
            t={t}
          />
        ))}
      </div>
    );
  }

  if (!block) return null;

  switch (block.type) {
    case "case_card":
      return (
        <CaseCard
          {...block}
          onNavigate={onNavigate}
          statusLabel={statusLabel}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "trip_card":
      return (
        <TripCard
          {...block}
          onNavigate={onNavigate}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "table":
      return (
        <TableBlockComponent
          {...block}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "list":
      return (
        <ClickableList
          {...block}
          onNavigate={onNavigate}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "link":
      return (
        <LinkBlockComponent
          {...block}
          onNavigate={onNavigate}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "status_pill":
      return (
        <StatusPill
          {...block}
          statusLabel={statusLabel}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "evidence":
      return (
        <EvidenceBlockComponent
          {...block}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "next_steps":
      return (
        <NextSteps
          {...block}
          onPrompt={onPrompt}
          labels={labels}
          t={t}
          className={className}
        />
      );

    case "confirmation":
      return (
        <ConfirmationCard
          action={block.action}
          checklist={block.checklist}
          summary={block.summary}
          onConfirm={() => onConfirm?.(block)}
          onDecline={() => onDecline?.(block)}
          pending={pendingConfirm}
          className={className}
        />
      );

    default:
      return null;
  }
}
