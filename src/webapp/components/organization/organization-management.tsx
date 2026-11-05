"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { OrganizationSwitcher, UserButton, useAuth } from "@clerk/nextjs";
import {
  ArrowUpDown,
  CircleAlert,
  Inbox,
  Mail,
  RotateCcw,
  Search,
  TriangleAlert,
  UserRoundPlus,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { resolveBackendUrl } from "@/lib/route-authorization";
import { isolatedGisBuild } from "@/lib/isolated-gis-build";
import {
  canResendInvitation,
  canRevokeInvitation,
  filterInvitations,
  filterMembers,
  isAnalyst,
  isValidEmail,
  memberRoleLabels,
  PAGE_SIZE,
  primaryRole,
  roleLabel,
  ROLE_OPTIONS,
  sortInvitations,
  sortMembers,
  type Invitation,
  type InvitationSortField,
  type Member,
  type MemberSortField,
  type SortDirection,
} from "./organization-presentation";

const ACCESS_DENIED = "Access denied: admin access is required to manage the organization.";

type AuthState = {
  getToken: () => Promise<string | null>;
  isLoaded: boolean;
  orgId?: string | null;
};

/**
 * Stable, module-scoped auth stub for GIS/E2E prerender builds that omit
 * ClerkProvider. One shared object avoids a fresh `getToken` reference on every
 * render, which previously caused repeated reloads.
 */
const BYPASS_AUTH: AuthState = {
  getToken: async () => null,
  isLoaded: true,
  orgId: "e2e-organization",
};

function backend(): string {
  if (typeof window !== "undefined") return resolveBackendUrl(window.location.host);
  return "";
}

async function authed(path: string, token: string | null, init?: RequestInit): Promise<Response> {
  return fetch(`${backend()}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token ?? ""}`,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });
}

async function readDetail(response: Response): Promise<string | null> {
  const body = await response.json().catch(() => null);
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
  return typeof detail === "string" && detail.trim().length > 0 ? detail : null;
}

export function OrganizationManagement() {
  const e2eAuthBypass =
    (process.env.NODE_ENV !== "production" || isolatedGisBuild()) &&
    process.env.NEXT_PUBLIC_E2E_TEST === "true";
  // GIS/E2E prerender builds omit ClerkProvider; bypass auth hooks only there so
  // static prerender does not throw. Production behaviour is unchanged.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const auth: AuthState = e2eAuthBypass ? BYPASS_AUTH : useAuth();
  const { isLoaded, orgId } = auth;

  if (!isLoaded) {
    return (
      <div role="status" aria-label="Loading organization" className="flex-1 min-h-0 overflow-y-auto bg-[#f6f8f7]">
        <span className="sr-only">Loading organization...</span>
      </div>
    );
  }

  // Remounting on organization change guarantees the previous roster and notices
  // disappear immediately and that late responses from the old organization are
  // ignored by the unmounted instance.
  return (
    <OrganizationRoster
      key={orgId ?? "no-organization"}
      getToken={auth.getToken}
      e2eAuthBypass={e2eAuthBypass}
    />
  );
}

type RosterProps = {
  getToken: () => Promise<string | null>;
  e2eAuthBypass: boolean;
};

function OrganizationRoster({ getToken, e2eAuthBypass }: RosterProps) {
  const getTokenRef = useRef(getToken);
  // Keep the ref current after each render so async callbacks always use the
  // latest token without needing to close over getToken (avoids stale closures).
  // Updated in an effect to satisfy react-hooks/refs — the ref is only ever
  // read inside async callbacks, never during render itself.
  useEffect(() => {
    getTokenRef.current = getToken;
  });

  const [members, setMembers] = useState<Member[]>([]);
  const [membersLoading, setMembersLoading] = useState(true);
  const [membersError, setMembersError] = useState("");
  const [membersOffset, setMembersOffset] = useState(0);
  const [membersHasNext, setMembersHasNext] = useState(false);

  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [invitationsLoading, setInvitationsLoading] = useState(true);
  const [invitationsError, setInvitationsError] = useState("");
  const [invitationsOffset, setInvitationsOffset] = useState(0);
  const [invitationsHaveNext, setInvitationsHaveNext] = useState(false);

  const [pageError, setPageError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());

  const [dialogOpen, setDialogOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [inviteError, setInviteError] = useState("");
  const [invitePending, setInvitePending] = useState(false);
  const inviteSubmittingRef = useRef(false);
  const inviteSessionRef = useRef(0);
  const emailRef = useRef<HTMLInputElement>(null);

  const [memberQuery, setMemberQuery] = useState("");
  const [memberRoleFilter, setMemberRoleFilter] = useState("all");
  const [memberStatusFilter, setMemberStatusFilter] = useState("all");
  const [memberSort, setMemberSort] = useState<{ field: MemberSortField; direction: SortDirection } | null>(null);

  const [inviteQuery, setInviteQuery] = useState("");
  const [inviteRoleFilter, setInviteRoleFilter] = useState("all");
  const [inviteStatusFilter, setInviteStatusFilter] = useState("all");
  const [inviteSort, setInviteSort] = useState<{ field: InvitationSortField; direction: SortDirection } | null>(null);

  const membersAbortRef = useRef<AbortController | null>(null);
  const invitesAbortRef = useRef<AbortController | null>(null);
  const membersEndOffsetRef = useRef<number | null>(null);
  const invitationsEndOffsetRef = useRef<number | null>(null);
  const invitationsOffsetRef = useRef(0);
  // isMountedRef is reset to true on each setup so StrictMode double-invoke
  // does not permanently suppress the second mount's fetch responses.
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      membersAbortRef.current?.abort();
      invitesAbortRef.current?.abort();
    };
  }, []);

  const setRowPending = useCallback((id: string, pending: boolean) => {
    setPendingIds((prev) => {
      const next = new Set(prev);
      if (pending) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const loadMembers = useCallback(async (offset: number) => {
    membersAbortRef.current?.abort();
    const controller = new AbortController();
    membersAbortRef.current = controller;
    setMembersLoading(true);
    setMembersError("");
    setMembers([]);
    setMembersHasNext(false);
    try {
      const token = await getTokenRef.current();
      const res = await authed(`/api/v1/account/users?limit=${PAGE_SIZE}&offset=${offset}`, token, {
        signal: controller.signal,
      });
      if (!isMountedRef.current || controller.signal.aborted) return;
      if (res.status === 403) {
        setPageError(ACCESS_DENIED);
        setMembersError("Access denied. Admin access is required.");
        return;
      }
      if (!res.ok) {
        setMembersError("Could not load members. Try again.");
        return;
      }
      const data = (await res.json()) as Member[];
      if (!isMountedRef.current || controller.signal.aborted) return;
      if (offset > 0 && data.length === 0) {
        membersEndOffsetRef.current = Math.min(membersEndOffsetRef.current ?? offset, offset);
        setMembersOffset(Math.max(0, offset - PAGE_SIZE));
        return;
      }
      setMembers(data);
      setMembersHasNext(
        data.length === PAGE_SIZE &&
          (membersEndOffsetRef.current === null || offset + PAGE_SIZE < membersEndOffsetRef.current)
      );
    } catch {
      if (!isMountedRef.current || controller.signal.aborted) return;
      setMembersError("Could not load members. Check your connection and try again.");
    } finally {
      if (isMountedRef.current && !controller.signal.aborted) setMembersLoading(false);
    }
  }, []);

  const loadInvitations = useCallback(async (offset: number) => {
    invitesAbortRef.current?.abort();
    const controller = new AbortController();
    invitesAbortRef.current = controller;
    setInvitationsLoading(true);
    setInvitationsError("");
    setInvitations([]);
    setInvitationsHaveNext(false);
    try {
      const token = await getTokenRef.current();
      const res = await authed(`/api/v1/admin/invitations?limit=${PAGE_SIZE}&offset=${offset}`, token, {
        signal: controller.signal,
      });
      if (!isMountedRef.current || controller.signal.aborted) return;
      if (res.status === 403) {
        setPageError(ACCESS_DENIED);
        setInvitationsError("Access denied. Admin access is required.");
        return;
      }
      if (!res.ok) {
        setInvitationsError("Could not load invitations. Try again.");
        return;
      }
      const body = (await res.json()) as { items?: Invitation[]; total?: number };
      if (!isMountedRef.current || controller.signal.aborted) return;
      const items = Array.isArray(body.items) ? body.items : [];
      const total = typeof body.total === "number" ? body.total : null;
      if (offset > 0 && (items.length === 0 || (total !== null && offset >= total))) {
        // Avoid offering an empty trailing page.
        invitationsEndOffsetRef.current = Math.min(invitationsEndOffsetRef.current ?? offset, offset);
        setInvitationsOffset(Math.max(0, offset - PAGE_SIZE));
        return;
      }
      setInvitations(items);
      setInvitationsHaveNext(
        total !== null && offset + items.length < total &&
          (invitationsEndOffsetRef.current === null || offset + PAGE_SIZE < invitationsEndOffsetRef.current)
      );
    } catch {
      if (!isMountedRef.current || controller.signal.aborted) return;
      setInvitationsError("Could not load invitations. Check your connection and try again.");
    } finally {
      if (isMountedRef.current && !controller.signal.aborted) setInvitationsLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadMembers(membersOffset);
  }, [loadMembers, membersOffset]);

  useEffect(() => {
    invitationsOffsetRef.current = invitationsOffset;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadInvitations(invitationsOffset);
  }, [loadInvitations, invitationsOffset]);

  const handleDialogOpenChange = useCallback((open: boolean) => {
    setDialogOpen(open);
    if (open) {
      inviteSessionRef.current += 1;
    } else {
      setEmail("");
      setRole("analyst");
      setInviteError("");
    }
  }, []);

  const submitInvite = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (inviteSubmittingRef.current) return;
      const trimmed = email.trim();
      if (!isValidEmail(trimmed)) {
        setInviteError("Enter a valid email address.");
        emailRef.current?.focus();
        return;
      }
      inviteSubmittingRef.current = true;
      setInvitePending(true);
      setInviteError("");
      const requestSession = inviteSessionRef.current;
      const isStaleSession = () => requestSession !== inviteSessionRef.current;
      try {
        const token = await getTokenRef.current();
        const res = await authed("/api/v1/admin/invitations", token, {
          method: "POST",
          body: JSON.stringify({ email: trimmed, role }),
        });
        if (!isMountedRef.current || isStaleSession()) return;
        if (res.status === 403) {
          const detail = await readDetail(res);
          if (!isMountedRef.current || isStaleSession()) return;
          setInviteError(detail ?? "Invite denied: admin access is required.");
          return;
        }
        if (res.status === 501) {
          setInviteError("Invitations are temporarily unavailable. Ask an administrator to enable them.");
          return;
        }
        if (!res.ok) {
          const detail = await readDetail(res);
          if (!isMountedRef.current || isStaleSession()) return;
          setInviteError(detail ?? "Could not add the invitation. Try again.");
          return;
        }
        handleDialogOpenChange(false);
        setNotice("Invitation added.");
        invitationsEndOffsetRef.current = null;
        void loadInvitations(invitationsOffsetRef.current);
      } catch {
        if (!isMountedRef.current || isStaleSession()) return;
        setInviteError("Could not add the invitation. Check your connection and try again.");
      } finally {
        inviteSubmittingRef.current = false;
        if (isMountedRef.current) setInvitePending(false);
      }
    },
    [email, role, handleDialogOpenChange, loadInvitations]
  );

  const updateRole = useCallback(
    async (id: string, next: string) => {
      setPageError("");
      setRowPending(id, true);
      try {
        const token = await getTokenRef.current();
        const res = await authed(`/api/v1/account/users/${id}/role`, token, {
          method: "PATCH",
          body: JSON.stringify({ role: next }),
        });
        if (!isMountedRef.current) return;
        if (!res.ok) {
          setPageError((await readDetail(res)) ?? "Could not update the role. Try again.");
          return;
        }
        const updated = (await res.json()) as Partial<Member>;
        if (!isMountedRef.current) return;
        setMembers((prev) =>
          prev.map((member) =>
            member.id === id
              ? {
                  ...member,
                  roles: Array.isArray(updated.roles) ? updated.roles : [next],
                }
              : member
          )
        );
        setNotice("Role updated.");
      } catch {
        if (!isMountedRef.current) return;
        setPageError("Could not update the role. Check your connection and try again.");
      } finally {
        if (isMountedRef.current) setRowPending(id, false);
      }
    },
    [setRowPending]
  );

  const runInvitationAction = useCallback(
    async (id: string, action: "resend" | "revoke") => {
      setPageError("");
      setRowPending(id, true);
      try {
        const token = await getTokenRef.current();
        const res = await authed(`/api/v1/admin/invitations/${id}/${action}`, token, { method: "POST" });
        if (!isMountedRef.current) return;
        if (res.status === 501) {
          setPageError("Invitations are temporarily unavailable. Ask an administrator to enable them.");
          return;
        }
        if (!res.ok) {
          setPageError((await readDetail(res)) ?? `Could not ${action} the invitation. Try again.`);
          return;
        }
        setNotice(
          action === "resend"
            ? "Invitation record refreshed. No email was sent."
            : "Invitation revoked."
        );
        void loadInvitations(invitationsOffsetRef.current);
      } catch {
        if (!isMountedRef.current) return;
        setPageError(`Could not ${action} the invitation. Check your connection and try again.`);
      } finally {
        if (isMountedRef.current) setRowPending(id, false);
      }
    },
    [loadInvitations, setRowPending]
  );

  const visibleMembers = useMemo(() => {
    const filtered = filterMembers(members, {
      query: memberQuery,
      role: memberRoleFilter === "all" ? "" : memberRoleFilter,
      status: memberStatusFilter === "all" ? "" : memberStatusFilter,
    });
    return memberSort ? sortMembers(filtered, memberSort.field, memberSort.direction) : filtered;
  }, [members, memberQuery, memberRoleFilter, memberStatusFilter, memberSort]);

  const visibleInvitations = useMemo(() => {
    const filtered = filterInvitations(invitations, {
      query: inviteQuery,
      role: inviteRoleFilter === "all" ? "" : inviteRoleFilter,
      status: inviteStatusFilter === "all" ? "" : inviteStatusFilter,
    });
    return inviteSort ? sortInvitations(filtered, inviteSort.field, inviteSort.direction) : filtered;
  }, [invitations, inviteQuery, inviteRoleFilter, inviteStatusFilter, inviteSort]);

  const membersHaveAnalyst = members.some(isAnalyst);

  function toggleMemberSort(field: MemberSortField) {
    setMemberSort((prev) => {
      if (!prev || prev.field !== field) return { field, direction: "asc" };
      return { field, direction: prev.direction === "asc" ? "desc" : "asc" };
    });
  }

  function toggleInvitationSort(field: InvitationSortField) {
    setInviteSort((prev) => {
      if (!prev || prev.field !== field) return { field, direction: "asc" };
      return { field, direction: prev.direction === "asc" ? "desc" : "asc" };
    });
  }

  function resetMemberFilters() {
    setMemberQuery("");
    setMemberRoleFilter("all");
    setMemberStatusFilter("all");
  }

  function resetInviteFilters() {
    setInviteQuery("");
    setInviteRoleFilter("all");
    setInviteStatusFilter("all");
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-[#f6f8f7] text-[#17231d]">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-6 py-7 max-md:gap-4 max-md:px-3 max-md:py-4">
        <header className="flex flex-wrap items-start justify-between gap-4 max-md:flex-col">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-[#17231d]">Organization</h1>
            <p className="mt-0.5 text-[13px] text-[#49564f]">Manage members, roles, and invitations.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3 max-md:w-full max-md:justify-between">
            {!e2eAuthBypass ? (
              <>
                <OrganizationSwitcher hidePersonal />
                <UserButton />
              </>
            ) : (
              <div
                data-testid="e2e-auth-indicator"
                className="rounded border border-[#e0e5e2] bg-white px-2 py-1 font-mono text-xs text-[#49564f]"
              >
                E2E (no Clerk)
              </div>
            )}
            <Dialog open={dialogOpen} onOpenChange={handleDialogOpenChange}>
              <DialogTrigger asChild>
                <Button
                  type="button"
                  className="h-9 gap-2 rounded-md bg-[#006948] px-4 text-[13px] font-semibold text-white shadow-sm hover:bg-[#00553a]"
                >
                  <UserRoundPlus className="h-4 w-4" aria-hidden="true" />
                  Invite user
                </Button>
              </DialogTrigger>
              <DialogContent
                className="max-w-[480px] gap-0 rounded-xl border-[#e0e5e2] p-0"
                onOpenAutoFocus={(event) => {
                  event.preventDefault();
                  emailRef.current?.focus();
                }}
              >
                <DialogHeader className="flex-row items-center gap-2.5 space-y-0 px-6 py-4 pr-12">
                  <UserRoundPlus className="h-[18px] w-[18px] shrink-0 text-[#006948]" aria-hidden="true" />
                  <DialogTitle className="min-w-0 text-base font-bold">Invite user to organization</DialogTitle>
                </DialogHeader>
                <DialogDescription className="sr-only">
                  Invite a person to this organization by email address and role.
                </DialogDescription>
                <form onSubmit={submitInvite}>
                  <div className="flex flex-col gap-4 px-6 py-5">
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="invite-email" className="text-xs font-semibold text-[#17231d]">
                        Email address
                      </label>
                      <Input
                        id="invite-email"
                        ref={emailRef}
                        type="email"
                        autoComplete="email"
                        required
                        placeholder="name@example.com"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        className="h-9 rounded-md border-[#e0e5e2] bg-white text-[13px] max-md:text-base"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="invite-role" className="text-xs font-semibold text-[#17231d]">
                        Role
                      </label>
                      <Select value={role} onValueChange={setRole} required>
                        <SelectTrigger
                          id="invite-role"
                          aria-required="true"
                          aria-describedby="invite-role-hint"
                          className="h-9 rounded-md border-[#e0e5e2] bg-white text-[13px] max-md:text-base"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p id="invite-role-hint" className="text-[11px] text-[#617068]">
                        Choose the access this person needs.
                      </p>
                    </div>
                    {inviteError && (
                      <p
                        role="alert"
                        className="flex items-start gap-2 rounded-md border border-[#fecaca] bg-[#fef2f2] px-3 py-2 text-[13px] text-[#991b1b]"
                      >
                        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                        <span>{inviteError}</span>
                      </p>
                    )}
                  </div>
                  <DialogFooter className="rounded-b-xl bg-[#fafbfa] px-6 py-3.5">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-md border-[#e0e5e2] bg-white text-[13px] font-medium text-[#49564f]"
                      onClick={() => handleDialogOpenChange(false)}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      disabled={invitePending}
                      className="h-9 gap-2 rounded-md bg-[#006948] px-4 text-[13px] font-semibold text-white shadow-sm hover:bg-[#00553a]"
                    >
                      {invitePending ? "Inviting..." : "Invite user"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </header>

        {members.length > 0 && !membersHaveAnalyst && !membersLoading && (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-[#fcd34d] bg-[#fffbeb] px-4 py-3 text-[13px] text-[#92400e]"
          >
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>
              <strong>No analysts on this page.</strong> Invite an analyst to help review cases.
            </p>
          </div>
        )}

        {pageError && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-[#fecaca] bg-[#fef2f2] px-4 py-3 text-[13px] text-[#991b1b]"
          >
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>{pageError}</p>
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-[#a7f3d0] bg-[#ecfdf5] px-4 py-3 text-[13px] text-[#065f46]"
          >
            <span>{notice}</span>
          </div>
        )}

        <section
          aria-labelledby="members-heading"
          className="flex flex-col overflow-hidden rounded-xl border border-[#e0e5e2] bg-white shadow-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e0e5e2] px-5 py-4">
            <div className="flex items-center gap-2.5">
              <Users className="h-4 w-4 text-[#49564f]" aria-hidden="true" />
              <h2 id="members-heading" className="text-[15px] font-semibold text-[#17231d]">
                Members
              </h2>
              {!membersLoading && !membersError && (
                <span className="rounded-full border border-[#e0e5e2] bg-[#f0f3f1] px-2 py-0.5 text-[11px] font-semibold text-[#49564f]">
                  {visibleMembers.length} {visibleMembers.length === 1 ? "member" : "members"}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e0e5e2] bg-[#fafbfa] px-5 py-3">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 max-md:flex-col max-md:items-stretch">
              <div className="relative min-w-[180px] flex-1 sm:max-w-[320px]">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7b8880]"
                  aria-hidden="true"
                />
                <Input
                  aria-label="Search members"
                  placeholder="Search members..."
                  value={memberQuery}
                  onChange={(event) => setMemberQuery(event.target.value)}
                  className="h-8 rounded-md border-[#e0e5e2] bg-white pl-8 text-xs max-md:text-base"
                />
              </div>
              <Select value={memberRoleFilter} onValueChange={setMemberRoleFilter}>
                <SelectTrigger
                  aria-label="Filter members by role"
                  className="h-8 w-auto min-w-[130px] rounded-md border-[#e0e5e2] bg-white text-xs max-md:w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All roles</SelectItem>
                  {ROLE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={memberStatusFilter} onValueChange={setMemberStatusFilter}>
                <SelectTrigger
                  aria-label="Filter members by status"
                  className="h-8 w-auto min-w-[130px] rounded-md border-[#e0e5e2] bg-white text-xs max-md:w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              variant="outline"
              aria-label="Reset member filters"
              onClick={resetMemberFilters}
              className="h-8 gap-1.5 rounded-md border-[#e0e5e2] bg-white text-xs font-medium text-[#49564f]"
            >
              <RotateCcw className="h-3 w-3" aria-hidden="true" />
              Reset
            </Button>
          </div>

          <p className="border-b border-[#e0e5e2] bg-[#f0f3f1] px-5 py-1.5 text-[11px] text-[#49564f]">
            Search and filters apply to this page.
          </p>

          <div
            role="region"
            tabIndex={0}
            aria-label="Members table; scroll horizontally for more columns"
            className="min-h-[120px] overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#006948]"
          >
            {membersLoading ? (
              <div role="status" aria-label="Loading members" className="flex flex-col gap-3 p-4">
                <span className="sr-only">Loading members...</span>
                <div className="h-9 w-full animate-pulse rounded bg-[#f0f3f1]" />
                <div className="h-9 w-full animate-pulse rounded bg-[#f0f3f1]" />
                <div className="h-9 w-full animate-pulse rounded bg-[#f0f3f1]" />
              </div>
            ) : (
              <>
                <Table aria-label="Organization members" className="min-w-[540px]">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <SortableHead
                        label="Member"
                        active={memberSort?.field === "display_name"}
                        direction={memberSort?.direction ?? "asc"}
                        onToggle={() => toggleMemberSort("display_name")}
                      />
                      <SortableHead
                        label="Role"
                        active={memberSort?.field === "roles"}
                        direction={memberSort?.direction ?? "asc"}
                        onToggle={() => toggleMemberSort("roles")}
                      />
                      <SortableHead
                        label="Status"
                        active={memberSort?.field === "status"}
                        direction={memberSort?.direction ?? "asc"}
                        onToggle={() => toggleMemberSort("status")}
                      />
                      <TableHead className="text-right">Change role</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleMembers.map((member) => (
                      <TableRow key={member.id}>
                        <TableCell className="font-semibold text-[#17231d]">{member.display_name}</TableCell>
                        <TableCell>
                          <span className="flex flex-wrap gap-1.5">
                            {memberRoleLabels(member.roles).map((label) => (
                              <Badge
                                key={label}
                                variant="outline"
                                className="rounded-md border-[#e0e5e2] bg-[#f0f3f1] px-2 py-0.5 text-[11px] font-semibold text-[#49564f]"
                              >
                                {label}
                              </Badge>
                            ))}
                          </span>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={member.status} />
                        </TableCell>
                        <TableCell className="text-right">
                          <Select
                            value={primaryRole(member.roles) ?? ""}
                            onValueChange={(value) => void updateRole(member.id, value)}
                            disabled={pendingIds.has(member.id)}
                          >
                            <SelectTrigger
                              aria-label={`Change role for ${member.display_name}`}
                              className="ml-auto h-8 w-auto min-w-[120px] rounded-md border-[#e0e5e2] bg-white text-xs"
                            >
                              <SelectValue placeholder={member.roles?.length ? "Unknown role" : "Unassigned"} />
                            </SelectTrigger>
                            <SelectContent>
                              {ROLE_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {visibleMembers.length === 0 &&
                  (membersError ? (
                    <EmptyState
                      icon={<CircleAlert className="h-9 w-9" aria-hidden="true" />}
                      title="Members unavailable"
                      description={membersError}
                    />
                  ) : members.length === 0 ? (
                    <EmptyState
                      icon={<Users className="h-9 w-9" aria-hidden="true" />}
                      title="No members yet"
                      description="Invite a user to give them access to this organization."
                    />
                  ) : (
                    <EmptyState
                      icon={<Search className="h-9 w-9" aria-hidden="true" />}
                      title="No members match your filter"
                      description="Try a different name, role, or status."
                    />
                  ))}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e0e5e2] bg-[#fafbfa] px-5 py-3 text-xs text-[#49564f]">
            <span>
              {membersLoading || membersError
                ? null
                : members.length > 0
                  ? `Showing ${visibleMembers.length} of ${members.length} ${members.length === 1 ? "member" : "members"} on this page`
                  : "Showing 0 members"}
            </span>
            <span className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                aria-label="Previous members page"
                disabled={membersOffset === 0 || membersLoading}
                onClick={() => setMembersOffset(Math.max(0, membersOffset - PAGE_SIZE))}
                className="h-8 rounded-md border-[#e0e5e2] bg-white text-xs"
              >
                Prev
              </Button>
              <Button
                type="button"
                variant="outline"
                aria-label="Next members page"
                disabled={!membersHasNext || membersLoading}
                onClick={() => setMembersOffset(membersOffset + PAGE_SIZE)}
                className="h-8 rounded-md border-[#e0e5e2] bg-white text-xs"
              >
                Next
              </Button>
            </span>
          </div>
        </section>

        <section
          aria-labelledby="invitations-heading"
          className="flex flex-col overflow-hidden rounded-xl border border-[#e0e5e2] bg-white shadow-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e0e5e2] px-5 py-4">
            <div className="flex items-center gap-2.5">
              <Mail className="h-4 w-4 text-[#49564f]" aria-hidden="true" />
              <h2 id="invitations-heading" className="text-[15px] font-semibold text-[#17231d]">
                Invitations
              </h2>
              {!invitationsLoading && !invitationsError && (
                <span className="rounded-full border border-[#e0e5e2] bg-[#f0f3f1] px-2 py-0.5 text-[11px] font-semibold text-[#49564f]">
                  {visibleInvitations.length} {visibleInvitations.length === 1 ? "invite" : "invites"}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e0e5e2] bg-[#fafbfa] px-5 py-3">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 max-md:flex-col max-md:items-stretch">
              <div className="relative min-w-[180px] flex-1 sm:max-w-[320px]">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#7b8880]"
                  aria-hidden="true"
                />
                <Input
                  aria-label="Search invitations"
                  placeholder="Search invitations..."
                  value={inviteQuery}
                  onChange={(event) => setInviteQuery(event.target.value)}
                  className="h-8 rounded-md border-[#e0e5e2] bg-white pl-8 text-xs max-md:text-base"
                />
              </div>
              <Select value={inviteRoleFilter} onValueChange={setInviteRoleFilter}>
                <SelectTrigger
                  aria-label="Filter invitations by role"
                  className="h-8 w-auto min-w-[130px] rounded-md border-[#e0e5e2] bg-white text-xs max-md:w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All roles</SelectItem>
                  {ROLE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={inviteStatusFilter} onValueChange={setInviteStatusFilter}>
                <SelectTrigger
                  aria-label="Filter invitations by status"
                  className="h-8 w-auto min-w-[130px] rounded-md border-[#e0e5e2] bg-white text-xs max-md:w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="revoked">Revoked</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              variant="outline"
              aria-label="Reset invitation filters"
              onClick={resetInviteFilters}
              className="h-8 gap-1.5 rounded-md border-[#e0e5e2] bg-white text-xs font-medium text-[#49564f]"
            >
              <RotateCcw className="h-3 w-3" aria-hidden="true" />
              Reset
            </Button>
          </div>

          <p className="border-b border-[#e0e5e2] bg-[#f0f3f1] px-5 py-1.5 text-[11px] text-[#49564f]">
            Search and filters apply to this page.
          </p>

          <div
            role="region"
            tabIndex={0}
            aria-label="Invitations table; scroll horizontally for more columns"
            className="min-h-[120px] overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#006948]"
          >
            {invitationsLoading ? (
              <div role="status" aria-label="Loading invitations" className="flex flex-col gap-3 p-4">
                <span className="sr-only">Loading invitations...</span>
                <div className="h-9 w-full animate-pulse rounded bg-[#f0f3f1]" />
                <div className="h-9 w-full animate-pulse rounded bg-[#f0f3f1]" />
              </div>
            ) : (
              <>
                <Table aria-label="Organization invitations" className="min-w-[540px]">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <SortableHead
                        label="Email"
                        active={inviteSort?.field === "email"}
                        direction={inviteSort?.direction ?? "asc"}
                        onToggle={() => toggleInvitationSort("email")}
                      />
                      <SortableHead
                        label="Role"
                        active={inviteSort?.field === "role"}
                        direction={inviteSort?.direction ?? "asc"}
                        onToggle={() => toggleInvitationSort("role")}
                      />
                      <SortableHead
                        label="Status"
                        active={inviteSort?.field === "status"}
                        direction={inviteSort?.direction ?? "asc"}
                        onToggle={() => toggleInvitationSort("status")}
                      />
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleInvitations.map((invitation) => {
                      const pending = pendingIds.has(invitation.id);
                      return (
                        <TableRow key={invitation.id}>
                          <TableCell className="font-medium text-[#17231d]">{invitation.email}</TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className="rounded-md border-[#e0e5e2] bg-[#f0f3f1] px-2 py-0.5 text-[11px] font-semibold text-[#49564f]"
                            >
                              {roleLabel(invitation.role)}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={invitation.status} />
                          </TableCell>
                          <TableCell className="text-right">
                            <span className="flex items-center justify-end gap-1.5">
                              <Button
                                type="button"
                                variant="outline"
                                disabled={!canResendInvitation(invitation) || pending}
                                onClick={() => void runInvitationAction(invitation.id, "resend")}
                                className="h-7 rounded-md border-[#e0e5e2] bg-white px-2.5 text-[11px] font-medium text-[#49564f]"
                              >
                                Resend
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                disabled={!canRevokeInvitation(invitation) || pending}
                                onClick={() => void runInvitationAction(invitation.id, "revoke")}
                                className="h-7 rounded-md border-[#e0e5e2] bg-white px-2.5 text-[11px] font-medium text-[#991b1b]"
                              >
                                Revoke
                              </Button>
                            </span>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                {visibleInvitations.length === 0 &&
                  (invitationsError ? (
                    <EmptyState
                      icon={<CircleAlert className="h-9 w-9" aria-hidden="true" />}
                      title="Invitations unavailable"
                      description={invitationsError}
                    />
                  ) : invitations.length === 0 ? (
                    <EmptyState
                      icon={<Mail className="h-9 w-9" aria-hidden="true" />}
                      title="No invitations yet"
                      description="Use Invite user to add someone to this organization."
                    />
                  ) : (
                    <EmptyState
                      icon={<Inbox className="h-9 w-9" aria-hidden="true" />}
                      title="No invitations match your filter"
                      description="Try different filters or invite a user."
                    />
                  ))}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e0e5e2] bg-[#fafbfa] px-5 py-3 text-xs text-[#49564f]">
            <span>
              {invitationsLoading || invitationsError
                ? null
                : invitations.length > 0
                  ? `Showing ${visibleInvitations.length} of ${invitations.length} ${invitations.length === 1 ? "invite" : "invites"} on this page`
                  : "Showing 0 invitations"}
            </span>
            <span className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                aria-label="Previous invitations page"
                disabled={invitationsOffset === 0 || invitationsLoading}
                onClick={() => setInvitationsOffset(Math.max(0, invitationsOffset - PAGE_SIZE))}
                className="h-8 rounded-md border-[#e0e5e2] bg-white text-xs"
              >
                Prev
              </Button>
              <Button
                type="button"
                variant="outline"
                aria-label="Next invitations page"
                disabled={!invitationsHaveNext || invitationsLoading}
                onClick={() => setInvitationsOffset(invitationsOffset + PAGE_SIZE)}
                className="h-8 rounded-md border-[#e0e5e2] bg-white text-xs"
              >
                Next
              </Button>
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}

function SortableHead({
  label,
  active,
  direction,
  onToggle,
}: {
  label: string;
  active: boolean;
  direction: SortDirection;
  onToggle: () => void;
}) {
  return (
    <TableHead aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <Button
        type="button"
        variant="ghost"
        onClick={onToggle}
        className="h-auto gap-1.5 p-0 text-xs font-semibold text-[#49564f] hover:bg-transparent hover:text-[#17231d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#006948]"
      >
        {label}
        <ArrowUpDown className="h-3 w-3" aria-hidden="true" />
      </Button>
    </TableHead>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const styles =
    normalized === "active"
      ? "border-[#a7f3d0] bg-[#ecfdf5] text-[#065f46]"
      : normalized === "pending"
        ? "border-[#fcd34d] bg-[#fffbeb] text-[#92400e]"
        : "border-[#e0e5e2] bg-[#f0f3f1] text-[#617068]";
  const dot =
    normalized === "active" ? "bg-[#10b981]" : normalized === "pending" ? "bg-[#f59e0b]" : "bg-[#7b8880]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${styles}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {normalized}
    </span>
  );
}

function EmptyState({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-6 py-12 text-center">
      <span className="mb-2 text-[#7b8880]">{icon}</span>
      <p className="text-sm font-semibold text-[#17231d]">{title}</p>
      <p className="max-w-[380px] text-[13px] text-[#617068]">{description}</p>
    </div>
  );
}

export default OrganizationManagement;
