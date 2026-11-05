/**
 * Non-reversible short DOM anchor for a trip id (Issue #538 blocker #6/#7).
 *
 * Never render the raw trip UUID in the DOM (attribute or text). This
 * produces a short, collision-tolerant anchor used only to scroll/highlight
 * a trip row when navigating from a `trip://` chat block; it is not an
 * identifier shown to the user and carries no case/trip semantics on its
 * own.
 */
export function tripDomId(tripId: string): string {
  const clean = String(tripId).replace(/[^a-zA-Z0-9]/g, "");
  return clean.slice(-8) || "unknown";
}
