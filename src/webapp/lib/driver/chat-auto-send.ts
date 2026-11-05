/**
 * Pure auto-send guard for case threads (Issue #482).
 *
 * The case-detail chat auto-sends "Check details of case #XXXX" exactly once,
 * only when:
 * - history has finished loading, and
 * - the thread is empty (no prior messages), and
 * - no auto-send has happened yet for this case (React StrictMode-safe: the
 *   caller holds the `alreadySent` flag in a ref, not state, so a duplicate
 *   mount/effect run is a no-op).
 */
export interface AutoSendGuardInput {
  historyLoaded: boolean;
  messageCount: number;
  alreadySent: boolean;
}

export function shouldAutoSendCaseCheck(input: AutoSendGuardInput): boolean {
  return input.historyLoaded && input.messageCount === 0 && !input.alreadySent;
}

export function buildAutoSendPrompt(template: string, shortCode: string): string {
  return template.replace("{code}", shortCode);
}
