export type EvidenceKind = "weather" | "traffic" | "telemetry" | "policy";

export interface CaseCardBlock {
  type: "case_card";
  case_id: string;
  title: string;
  status_key: string;
}

export interface TripCardBlock {
  type: "trip_card";
  trip_id: string;
  pickup: string;
  destination: string;
  fare_vnd?: number;
}

export interface TableBlock {
  type: "table";
  columns: string[];
  rows: (string | number)[][];
}

export interface ClickableListItem {
  label: string;
  href: string;
}

export interface ClickableListBlock {
  type: "list";
  items: ClickableListItem[];
}

export interface LinkBlock {
  type: "link";
  label: string;
  url: string;
}

export interface StatusPillBlock {
  type: "status_pill";
  status_key: string;
}

export interface EvidenceItem {
  kind: EvidenceKind;
  summary: string;
  source?: string;
}

export interface EvidenceBlock {
  type: "evidence";
  items: EvidenceItem[];
}

export interface NextStepsItem {
  label: string;
  prompt: string;
}

export interface NextStepsBlock {
  type: "next_steps";
  items: NextStepsItem[];
}

export interface ConfirmationChecklistItem {
  key: string;
  ok: boolean;
  label?: string;
}

export interface ConfirmationBlock {
  type: "confirmation";
  action: "acknowledge" | "submit_statement";
  checklist: ConfirmationChecklistItem[];
  summary: string;
}

export type DriverChatBlock =
  | CaseCardBlock
  | TripCardBlock
  | TableBlock
  | ClickableListBlock
  | LinkBlock
  | StatusPillBlock
  | EvidenceBlock
  | NextStepsBlock
  | ConfirmationBlock;

export interface DriverAnswerPayload {
  markdown?: string;
  blocks?: DriverChatBlock[];
}
