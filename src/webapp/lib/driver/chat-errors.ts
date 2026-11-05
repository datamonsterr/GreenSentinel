/**
 * Localized chat error resolver for driver chat (F1).
 * Maps network and transport errors to human-friendly, localized next-intl text.
 * Never leaks HTTP status codes or developer English into the UI.
 */

export function parseErrorStatus(err: unknown): number | null {
  if (err && typeof err === "object" && "status" in err && typeof (err as any).status === "number") {
    return (err as any).status;
  }
  const msg = err instanceof Error ? err.message : String(err ?? "");
  const match =
    msg.match(/API Error (\d+)/i) ||
    msg.match(/status (\d+)/i) ||
    msg.match(/\b(400|401|403|404|422|500|502|503|504)\b/);
  return match ? Number(match[1]) : null;
}

export function getLocalizedChatErrorMessage(
  err: unknown,
  t: (key: string) => string
): string {
  const status = parseErrorStatus(err);
  if (status === 404 || status === 403) {
    return t("errorCaseNotFoundOrForbidden");
  }
  if (status === 401) {
    return t("errorSessionExpired");
  }
  return t("errorAssistantUnavailable");
}
