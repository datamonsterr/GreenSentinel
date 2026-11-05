import type { CaseDetailResponse, DriverMotivationAssessment, PreliminaryJudgment } from '@/types/schemas';
export type WorkspaceDatum<T> = { state: 'available'; value: T; source: string } | { state: 'unavailable'; followup: number };
export function savedWorkspaceJudgment(detail: CaseDetailResponse): PreliminaryJudgment | null {
  const judgment = detail.preliminary_judgment ?? detail.adjudication?.preliminary_judgment;
  return judgment?.id && judgment.case_id === detail.case.id ? judgment : null;
}
export function workspaceMotivation(detail: CaseDetailResponse): WorkspaceDatum<DriverMotivationAssessment> {
  const assessment = detail.forensic_brief?.motivation_assessment;
  return assessment?.natural_vietnamese_narrative && savedWorkspaceJudgment(detail)
    ? { state: 'available', value: assessment, source: 'forensic_brief.motivation_assessment' }
    : { state: 'unavailable', followup: 364 };
}
export const workspaceWillingness: WorkspaceDatum<string> = { state: 'unavailable', followup: 364 };
export function firstTelemetryPosition(detail: CaseDetailResponse): [number, number] | null {
  const valid = (detail.telemetry_samples ?? []).filter(sample => {
    const coordinates = sample.position?.coordinates;
    return Array.isArray(coordinates) && coordinates.length >= 2 && Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1]) && Math.abs(coordinates[0]) <= 180 && Math.abs(coordinates[1]) <= 90 && Number.isFinite(Date.parse(sample.recorded_at ?? sample.occurred_at));
  }).sort((a, b) => Date.parse(a.recorded_at ?? a.occurred_at) - Date.parse(b.recorded_at ?? b.occurred_at));
  return valid[0] ? valid[0].position.coordinates.slice(0, 2) as [number, number] : null;
}
