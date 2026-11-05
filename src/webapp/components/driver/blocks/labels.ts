import viMessages from "@/messages/vi.json";
import enMessages from "@/messages/en.json";

export interface BlockLabels {
  // Trip card
  trip: string;
  pickup: string;
  destination: string;
  fareRecorded: string;
  tripDetails: string;

  // Case card
  casePrefix: string;

  // Link
  inAppNavigation: string;

  // Evidence
  evidenceHeader: string;
  evidenceKinds: Record<string, string>;

  // Next steps
  nextStepsHeader: string;

  // Status mapping
  status: Record<string, string>;
}

export const VI_LABELS: BlockLabels = viMessages.driverBlocks as unknown as BlockLabels;

export const EN_LABELS: BlockLabels = enMessages.driverBlocks as unknown as BlockLabels;

export const defaultLabels = VI_LABELS;

export function resolveLabels(
  labels?: Partial<BlockLabels>,
  t?: Partial<BlockLabels>
): BlockLabels {
  const chosen = labels || t;
  if (!chosen) return VI_LABELS;

  return {
    ...VI_LABELS,
    ...chosen,
    evidenceKinds: {
      ...VI_LABELS.evidenceKinds,
      ...(chosen.evidenceKinds || {}),
    },
    status: {
      ...VI_LABELS.status,
      ...(chosen.status || {}),
    },
  };
}

