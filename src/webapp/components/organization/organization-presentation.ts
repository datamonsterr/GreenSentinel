/**
 * Pure presentation helpers for the organization management page.
 *
 * These functions only shape the existing API records for display, filtering,
 * and sorting. They never perform requests and never alter authoritative data.
 * `fraud_analyst` is recognised as Analyst for presentation without touching
 * server grants.
 */

export type Member = {
  id: string;
  display_name: string;
  roles: string[];
  status: string;
};

export type Invitation = {
  id: string;
  email: string;
  role: string;
  status: string;
};

export type CanonicalRole = "admin" | "analyst" | "driver";

export const PAGE_SIZE = 50;

export const ROLE_OPTIONS: ReadonlyArray<{ value: CanonicalRole; label: string }> = [
  { value: "admin", label: "Admin" },
  { value: "analyst", label: "Analyst" },
  { value: "driver", label: "Driver" },
];

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  analyst: "Analyst",
  fraud_analyst: "Analyst",
  driver: "Driver",
};

const ROLE_RANK: Record<string, number> = { admin: 0, analyst: 1, driver: 2 };

/** Normalise an API role to one of the three supported canonical roles. */
export function normalizeRole(role: string | null | undefined): string {
  const value = (role ?? "").trim().toLowerCase();
  return value === "fraud_analyst" ? "analyst" : value;
}

export function roleLabel(role: string | null | undefined): string {
  const normalized = normalizeRole(role);
  return ROLE_LABELS[normalized] ?? ROLE_LABELS[(role ?? "").trim().toLowerCase()] ?? "Member";
}

/** Distinct display labels for every role a member holds. */
export function memberRoleLabels(roles: string[] | null | undefined): string[] {
  const labels: string[] = [];
  for (const role of roles ?? []) {
    const label = roleLabel(role);
    if (!labels.includes(label)) labels.push(label);
  }
  return labels.length > 0 ? labels : ["Member"];
}

/** Choose the single role shown in the inline role selector. */
export function primaryRole(roles: string[] | null | undefined): CanonicalRole | undefined {
  const normalized = (roles ?? []).map(normalizeRole);
  const ranked = normalized
    .filter((role): role is CanonicalRole => role === "admin" || role === "analyst" || role === "driver")
    .sort((a, b) => ROLE_RANK[a] - ROLE_RANK[b]);
  return ranked[0];
}

export function isAnalyst(member: Member): boolean {
  return (member.roles ?? []).some((role) => normalizeRole(role) === "analyst");
}

export function isValidEmail(value: string): boolean {
  const email = value.trim();
  if (email.length < 3 || email.length > 320) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export type MemberFilters = { query: string; role: string; status: string };
export type InvitationFilters = { query: string; role: string; status: string };

export function filterMembers(members: Member[], filters: MemberFilters): Member[] {
  const query = filters.query.trim().toLowerCase();
  const role = normalizeRole(filters.role);
  return members.filter((member) => {
    const matchesQuery = !query || member.display_name.toLowerCase().includes(query);
    const matchesRole = !role || (member.roles ?? []).some((r) => normalizeRole(r) === role);
    const matchesStatus = !filters.status || member.status === filters.status;
    return matchesQuery && matchesRole && matchesStatus;
  });
}

export type MemberSortField = "display_name" | "roles" | "status";
export type InvitationSortField = "email" | "role" | "status";
export type SortDirection = "asc" | "desc";

export function sortMembers(members: Member[], field: MemberSortField, direction: SortDirection): Member[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...members].sort((a, b) => factor * compare(String(valueForMember(a, field)), String(valueForMember(b, field))));
}

function valueForMember(member: Member, field: MemberSortField): string {
  if (field === "roles") return memberRoleLabels(member.roles).join(", ");
  return member[field] ?? "";
}

export function filterInvitations(invitations: Invitation[], filters: InvitationFilters): Invitation[] {
  const query = filters.query.trim().toLowerCase();
  const role = normalizeRole(filters.role);
  return invitations.filter((invitation) => {
    const matchesQuery = !query || invitation.email.toLowerCase().includes(query);
    const matchesRole = !role || normalizeRole(invitation.role) === role;
    const matchesStatus = !filters.status || invitation.status === filters.status;
    return matchesQuery && matchesRole && matchesStatus;
  });
}

export function sortInvitations(
  invitations: Invitation[],
  field: InvitationSortField,
  direction: SortDirection
): Invitation[] {
  const factor = direction === "asc" ? 1 : -1;
  return [...invitations].sort(
    (a, b) => factor * compare(String(a[field] ?? ""), String(b[field] ?? ""))
  );
}

function compare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
}

export function invitationIsPending(invitation: Invitation): boolean {
  return invitation.status === "pending";
}

/** A re-send is only meaningful for an invitation that is still pending. */
export function canResendInvitation(invitation: Invitation): boolean {
  return invitationIsPending(invitation);
}

/** A revoke is only meaningful for an invitation that is not already revoked. */
export function canRevokeInvitation(invitation: Invitation): boolean {
  return invitationIsPending(invitation);
}
