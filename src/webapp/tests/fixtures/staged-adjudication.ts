import type { PreliminaryJudgment } from "@/types/schemas";

/** Existing conclusion-formatting tests exercise the already-committed stage. */
export function committedJudgment(caseId: string, analystId: string): PreliminaryJudgment {
  return {
    id: `judgment-${caseId}`, case_id: caseId, analyst_id: analystId,
    judgment: "Nghi ngờ vi phạm", note: null, created_at: "2026-10-14T01:00:00Z",
  };
}
