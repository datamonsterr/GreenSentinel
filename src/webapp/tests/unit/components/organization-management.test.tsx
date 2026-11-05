import React, { StrictMode } from "react";
import { render, screen, within, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserEvent } from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { OrganizationManagement } from "@/components/organization/organization-management";

const auth = vi.hoisted(() => ({ orgId: "org-a" }));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({
    getToken: async () => "test-token",
    isLoaded: true,
    orgId: auth.orgId,
  }),
  OrganizationSwitcher: () => <div data-testid="mock-org-switcher">OrganizationSwitcher</div>,
  UserButton: () => <div data-testid="mock-user-button">UserButton</div>,
}));

type Member = { id: string; display_name: string; roles: string[]; status: string };
type Invitation = { id: string; email: string; role: string; status: string };

type Call = { url: string; path: string; method: string; body: string | null };

const MEMBERS_A: Member[] = [
  { id: "usr_marcus", display_name: "Marcus Vance", roles: ["admin"], status: "active" },
  { id: "usr_elena", display_name: "Elena Rostova", roles: ["analyst"], status: "active" },
  { id: "usr_carlos", display_name: "Carlos Mendez", roles: ["driver"], status: "active" },
];

const INVITES: Invitation[] = [
  { id: "inv_pending", email: "sarah.chen@example.com", role: "analyst", status: "pending" },
  { id: "inv_revoked", email: "alex.t@example.com", role: "driver", status: "revoked" },
];

const DEFAULT_MEMBERS = (members: Member[] = MEMBERS_A) => members;

interface Harness {
  calls: Call[];
  users: () => Call[];
  invitations: () => Call[];
  posts: () => Call[];
}

let usersQueue: Array<() => Response | Promise<Response>>;
let invitesQueue: Array<() => Response | Promise<Response>>;
let postHandler: (body: string) => Response | Promise<Response>;
let patchHandlers: Record<string, (body: string) => Response | Promise<Response>>;
let actionHandlers: Record<string, () => Response | Promise<Response>>;
let harness: Harness;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(): Harness {
  const calls: Call[] = [];
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const path = new URL(url).pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? init.body : null;
    calls.push({ url, path, method, body });

    if (path === "/api/v1/account/users" && method === "GET") {
      const next = usersQueue.shift();
      return next ? next() : json(DEFAULT_MEMBERS());
    }
    if (path === "/api/v1/admin/invitations" && method === "GET") {
      const next = invitesQueue.shift();
      return next ? next() : json({ items: [], total: 0 });
    }
    if (path === "/api/v1/admin/invitations" && method === "POST") {
      return postHandler(body ?? "{}");
    }
    const roleMatch = path.match(/^\/api\/v1\/account\/users\/([^/]+)\/role$/);
    if (roleMatch && method === "PATCH") {
      const handler = patchHandlers[roleMatch[1]];
      return handler ? handler(body ?? "{}") : json({}, 404);
    }
    const actionMatch = path.match(/^\/api\/v1\/admin\/invitations\/([^/]+)\/(resend|revoke)$/);
    if (actionMatch && method === "POST") {
      const handler = actionHandlers[`${actionMatch[1]}:${actionMatch[2]}`];
      return handler ? handler() : json({}, 404);
    }
    return json({ detail: "unexpected" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return {
    calls,
    users: () => calls.filter((c) => c.path === "/api/v1/account/users" && c.method === "GET"),
    invitations: () => calls.filter((c) => c.path === "/api/v1/admin/invitations" && c.method === "GET"),
    posts: () => calls.filter((c) => c.path === "/api/v1/admin/invitations" && c.method === "POST"),
  };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_E2E_TEST = "false";
  auth.orgId = "org-a";
  usersQueue = [];
  invitesQueue = [];
  postHandler = () => json({}, 201);
  patchHandlers = {};
  actionHandlers = {};
  harness = installFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function openInviteDialog(user: UserEvent): Promise<HTMLElement> {
  const trigger = screen.getByRole("button", { name: "Invite user" });
  await user.click(trigger);
  return screen.findByRole("dialog");
}

async function chooseOption(user: UserEvent, scope: HTMLElement, label: string, optionName: string) {
  // Open the Radix Select from the keyboard: this mirrors a real keyboard user,
  // keeps the control free of form submission, and avoids cross-test pointer
  // pollution from the portalled listbox in jsdom.
  const trigger = within(scope).getByLabelText(label);
  trigger.focus();
  await user.keyboard("{Enter}");
  const option = await screen.findByRole("option", { name: optionName });
  await user.click(option);
}

function membersRegion(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Members" });
  const section = heading.closest("section");
  if (!section) throw new Error("Members section not found");
  return section as HTMLElement;
}

describe("OrganizationManagement", () => {
  it("loads both rosters through StrictMode effect replay", async () => {
    invitesQueue = [() => json({ items: INVITES, total: 2 }), () => json({ items: INVITES, total: 2 })];
    render(<StrictMode><OrganizationManagement /></StrictMode>);
    expect(await screen.findByText("Elena Rostova")).toBeInTheDocument();
    expect(await screen.findByText("sarah.chen@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading members" })).not.toBeInTheDocument();
  });

  it.each([403, 500])("does not claim an empty organization when lists fail with %i", async (status) => {
    usersQueue = [() => json({}, status)];
    invitesQueue = [() => json({}, status)];
    render(<OrganizationManagement />);
    expect(await screen.findByText("Members unavailable")).toBeInTheDocument();
    expect(await screen.findByText("Invitations unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No members yet")).not.toBeInTheDocument();
    expect(screen.queryByText("No invitations yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Showing 0 members")).not.toBeInTheDocument();
    expect(screen.queryAllByText(/^0 (members|invites)$/)).toHaveLength(0);
  });

  it("waits for successful loads before showing roster counts", () => {
    usersQueue = [() => new Promise(() => {})];
    invitesQueue = [() => new Promise(() => {})];
    render(<OrganizationManagement />);
    expect(screen.getByRole("status", { name: "Loading members" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading invitations" })).toBeInTheDocument();
    expect(screen.queryAllByText(/^0 (members|invites)$/)).toHaveLength(0);
    expect(screen.queryAllByText(/^Showing 0 (members|invitations)$/)).toHaveLength(0);
  });

  it("hides previous rows and counts when the next members page fails", async () => {
    usersQueue = [
      () => json(Array.from({ length: 50 }, (_, i) => ({ ...MEMBERS_A[0], id: `old-${i}`, display_name: `Old member ${i}` }))),
      () => json({}, 500),
    ];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Old member 0");
    await user.click(screen.getByRole("button", { name: "Next members page" }));
    expect(await screen.findByText("Members unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Old member 0")).not.toBeInTheDocument();
    expect(screen.queryByText(/Showing 51/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous members page" })).toBeEnabled();
  });

  it("returns from an empty member next page without repeatedly offering that page", async () => {
    const page = Array.from({ length: 50 }, (_, i) => ({ ...MEMBERS_A[0], id: `member-${i}`, display_name: `Member ${i}` }));
    usersQueue = [() => json(page), () => json([]), () => json(page)];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Member 0");
    await user.click(screen.getByRole("button", { name: "Next members page" }));
    expect(await screen.findByText("Member 0")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading members" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next members page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous members page" })).toBeDisabled();
  });

  it("returns from an empty invitation page without offering it again after the previous page settles", async () => {
    const page = Array.from({ length: 50 }, (_, i) => ({ ...INVITES[0], id: `invite-${i}`, email: `person${i}@example.com` }));
    invitesQueue = [
      () => json({ items: page, total: 51 }),
      () => json({ items: [], total: 51 }),
      () => json({ items: page, total: 51 }),
    ];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("person0@example.com");
    await user.click(screen.getByRole("button", { name: "Next invitations page" }));
    expect(await screen.findByText("person0@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading invitations" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next invitations page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous invitations page" })).toBeDisabled();
  });

  it("counts only visible filtered members and resets filters", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");
    const region = membersRegion();
    await user.type(within(region).getByLabelText("Search members"), "Elena");
    expect(within(region).getByText("Showing 1 of 3 members on this page")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Reset member filters" }));
    expect(within(region).getByText("Showing 3 of 3 members on this page")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Member" }));
    expect(within(region).getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual(["Carlos Mendez", "Elena Rostova", "Marcus Vance"]);
  });

  it("resend reports a record update without claiming email delivery", async () => {
    invitesQueue = [() => json({ items: INVITES, total: 2 }), () => json({ items: INVITES, total: 2 })];
    actionHandlers["inv_pending:resend"] = () => json({ id: "inv_pending", status: "pending" });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const row = (await screen.findByText("sarah.chen@example.com")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Resend" }));
    expect(await screen.findByText("Invitation record refreshed. No email was sent.")).toBeInTheDocument();
    expect(screen.queryByText("Invitation re-sent.")).not.toBeInTheDocument();
  });

  it.each(["resend", "revoke"] as const)("refreshes the current invitation page after a delayed %s completes", async (action) => {
    let resolveAction!: (response: Response) => void;
    const firstPage = Array.from({ length: 50 }, (_, i) => ({ ...INVITES[0], id: `invite-${i}`, email: `person${i}@example.com` }));
    const secondPage = [{ ...INVITES[0], id: "page-two", email: "page-two@example.com" }];
    invitesQueue = [
      () => json({ items: firstPage, total: 51 }),
      () => json({ items: secondPage, total: 51 }),
      () => json({ items: secondPage, total: 51 }),
    ];
    actionHandlers[`invite-0:${action}`] = () => new Promise((resolve) => { resolveAction = resolve; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const row = (await screen.findByText("person0@example.com")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: action === "resend" ? "Resend" : "Revoke" }));
    await user.click(screen.getByRole("button", { name: "Next invitations page" }));
    await screen.findByText("page-two@example.com");
    await act(async () => resolveAction(json({ id: "invite-0", status: action === "revoke" ? "revoked" : "pending" })));
    expect(await screen.findByText("page-two@example.com")).toBeInTheDocument();
    expect(harness.invitations()).toHaveLength(3);
    expect(harness.invitations()[2].url).toContain("offset=50");
    expect(screen.getByText("Showing 1 of 1 invite on this page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous invitations page" })).toBeEnabled();
  });

  it("refreshes the current invitation page after a delayed invite completes", async () => {
    let resolvePost!: (response: Response) => void;
    const firstPage = Array.from({ length: 50 }, (_, i) => ({ ...INVITES[0], id: `invite-${i}`, email: `person${i}@example.com` }));
    const secondPage = [{ ...INVITES[0], id: "page-two", email: "page-two@example.com" }];
    invitesQueue = [
      () => json({ items: firstPage, total: 51 }),
      () => json({ items: secondPage, total: 51 }),
      () => json({ items: secondPage, total: 51 }),
    ];
    postHandler = () => new Promise((resolve) => { resolvePost = resolve; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("person0@example.com");
    const dialog = await openInviteDialog(user);
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("new@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Invite user" }));
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Next invitations page" }));
    await screen.findByText("page-two@example.com");
    await act(async () => resolvePost(json({ id: "new-invite" }, 201)));
    expect(await screen.findByText("page-two@example.com")).toBeInTheDocument();
    expect(harness.invitations()).toHaveLength(3);
    expect(harness.invitations()[2].url).toContain("offset=50");
  });

  it("ignores aborted invitation JSON after a newer refresh of the current page settles", async () => {
    let resolveFirstAction!: (response: Response) => void;
    let resolveSecondAction!: (response: Response) => void;
    let resolveOldJson!: (body: unknown) => void;
    const oldResponse = json({});
    const decodeOldJson = vi.spyOn(oldResponse, "json").mockImplementation(
      () => new Promise((resolve) => { resolveOldJson = resolve; })
    );
    const firstPage = Array.from({ length: 50 }, (_, i) => ({ ...INVITES[0], id: `invite-${i}`, email: `person${i}@example.com` }));
    const secondPage = [{ ...INVITES[0], id: "page-two", email: "page-two@example.com" }];
    const refreshedPage = [{ ...secondPage[0], email: "refreshed-page-two@example.com" }];
    invitesQueue = [
      () => json({ items: firstPage, total: 51 }),
      () => json({ items: secondPage, total: 51 }),
      () => oldResponse,
      () => json({ items: refreshedPage, total: 51 }),
    ];
    actionHandlers["invite-0:resend"] = () => new Promise((resolve) => { resolveFirstAction = resolve; });
    actionHandlers["invite-1:resend"] = () => new Promise((resolve) => { resolveSecondAction = resolve; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const firstRow = (await screen.findByText("person0@example.com")).closest("tr")!;
    const secondRow = screen.getByText("person1@example.com").closest("tr")!;
    await user.click(within(firstRow).getByRole("button", { name: "Resend" }));
    await user.click(within(secondRow).getByRole("button", { name: "Resend" }));
    await user.click(screen.getByRole("button", { name: "Next invitations page" }));
    await screen.findByText("page-two@example.com");
    await act(async () => resolveFirstAction(json({})));
    await waitFor(() => expect(decodeOldJson).toHaveBeenCalled());
    await act(async () => resolveSecondAction(json({})));
    await screen.findByText("refreshed-page-two@example.com");
    await act(async () => resolveOldJson({ items: firstPage, total: 100 }));
    expect(screen.getByText("refreshed-page-two@example.com")).toBeInTheDocument();
    expect(screen.queryByText("person0@example.com")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next invitations page" })).toBeDisabled();
  });

  it("ignores old member JSON decoded after an organization switch", async () => {
    let resolveOldJson!: (body: unknown) => void;
    const oldResponse = json({});
    const decodeOldJson = vi.spyOn(oldResponse, "json").mockImplementation(
      () => new Promise((resolve) => { resolveOldJson = resolve; })
    );
    usersQueue = [() => oldResponse, () => json([MEMBERS_A[0]])];
    const { rerender } = render(<OrganizationManagement />);
    await waitFor(() => expect(decodeOldJson).toHaveBeenCalled());
    auth.orgId = "org-b";
    rerender(<OrganizationManagement />);
    await screen.findByText("Marcus Vance");
    await act(async () => resolveOldJson([MEMBERS_A[1]]));
    expect(screen.getByText("Marcus Vance")).toBeInTheDocument();
    expect(screen.queryByText("Elena Rostova")).not.toBeInTheDocument();
  });

  it("keeps invitation actions pending and translates unavailable configuration", async () => {
    let resolveAction!: (response: Response) => void;
    invitesQueue = [() => json({ items: INVITES, total: 2 })];
    actionHandlers["inv_pending:resend"] = () => new Promise((resolve) => { resolveAction = resolve; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const row = (await screen.findByText("sarah.chen@example.com")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Resend" }));
    expect(within(row).getByRole("button", { name: "Resend" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Revoke" })).toBeDisabled();
    await act(async () => resolveAction(json({ detail: "CLERK_SECRET_KEY not set" }, 501)));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invitations are temporarily unavailable. Ask an administrator to enable them.");
    expect(screen.queryByText(/CLERK_SECRET_KEY/)).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Resend" })).toBeEnabled();
  });

  it("hides an already loaded old roster, closes the dialog, and resets filters on organization switch", async () => {
    const user = userEvent.setup();
    usersQueue = [() => json(MEMBERS_A), () => new Promise(() => {})];
    const { rerender } = render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");
    await user.type(screen.getByLabelText("Search members"), "Elena");
    await openInviteDialog(user);
    auth.orgId = "org-b";
    rerender(<OrganizationManagement />);
    expect(screen.queryByText("Elena Rostova")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Search members")).toHaveValue("");
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading invitations" })).not.toBeInTheDocument());
  });

  it("opens a named dialog, focuses email, and returns focus on Escape", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const trigger = screen.getByRole("button", { name: "Invite user" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: /invite user to organization/i });
    const email = within(dialog).getByLabelText("Email address");
    await waitFor(() => expect(email).toHaveFocus());

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("defaults to Analyst and sends the canonical payload once from Enter", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    expect(within(dialog).getByLabelText("Role")).toHaveTextContent("Analyst");
    expect(within(dialog).getByText("Choose the access this person needs.")).toBeInTheDocument();

    await chooseOption(user, dialog, "Role", "Driver");
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("new.person@example.com");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(harness.posts()).toHaveLength(1));
    expect(JSON.parse(harness.posts()[0].body ?? "{}")).toEqual({
      email: "new.person@example.com",
      role: "driver",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/Invitation added/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite user" })).toHaveFocus();
  });

  it("requires the invitation role in the native form control", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const dialog = await openInviteDialog(user);
    const nativeRole = dialog.querySelector("select");
    expect(nativeRole).toBeRequired();
    expect(nativeRole).toHaveValue("analyst");
    expect(within(dialog).getByLabelText("Role")).toHaveAttribute("aria-required", "true");
  });

  it("submits identically from the submit button click", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("  click@example.com  ");
    await user.click(within(dialog).getByRole("button", { name: "Invite user" }));

    await waitFor(() => expect(harness.posts()).toHaveLength(1));
    expect(JSON.parse(harness.posts()[0].body ?? "{}")).toEqual({ email: "click@example.com", role: "analyst" });
  });

  it("rejects an invalid email without sending a request", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("not-an-email");
    const form = dialog.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() => expect(within(dialog).getByRole("alert")).toBeInTheDocument());
    expect(harness.posts()).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("blocks duplicate submissions while the first is pending", async () => {
    let resolvePost: (r: Response) => void = () => {};
    postHandler = () => new Promise<Response>((resolve) => { resolvePost = resolve; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("dup@example.com");
    const form = dialog.querySelector("form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(harness.posts()).toHaveLength(1));

    resolvePost(json({ id: "inv_new" }, 201));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(harness.posts()).toHaveLength(1);
  });

  it.each(
    (["Cancel", "Escape"] as const).flatMap((closeMethod) =>
      (["success", "server error", "network error"] as const).map((result) => ({ closeMethod, result }))
    )
  )("preserves a reopened invitation draft after an earlier $result settled following $closeMethod", async ({ closeMethod, result }) => {
    let resolvePost!: (response: Response) => void;
    let rejectPost!: (error: Error) => void;
    postHandler = () => new Promise((resolve, reject) => { resolvePost = resolve; rejectPost = reject; });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const firstDialog = await openInviteDialog(user);
    await user.click(within(firstDialog).getByLabelText("Email address"));
    await user.paste("first-session@example.com");
    await user.click(within(firstDialog).getByRole("button", { name: "Invite user" }));
    await waitFor(() => expect(harness.posts()).toHaveLength(1));
    if (closeMethod === "Cancel") await user.click(within(firstDialog).getByRole("button", { name: "Cancel" }));
    else await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const secondDialog = await openInviteDialog(user);
    await user.click(within(secondDialog).getByLabelText("Email address"));
    await user.paste("second-session@example.com");
    await chooseOption(user, secondDialog, "Role", "Driver");
    expect(within(secondDialog).getByRole("button", { name: "Inviting..." })).toBeDisabled();
    await act(async () => {
      if (result === "network error") rejectPost(new Error("connection lost"));
      else resolvePost(result === "success" ? json({}, 201) : json({ detail: "First invitation denied." }, 403));
    });

    expect(secondDialog).toBeInTheDocument();
    expect(within(secondDialog).getByLabelText("Email address")).toHaveValue("second-session@example.com");
    expect(within(secondDialog).getByLabelText("Role")).toHaveTextContent("Driver");
    expect(within(secondDialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(secondDialog).getByRole("button", { name: "Invite user" })).toBeEnabled();
    postHandler = () => json({}, 201);
    await user.click(within(secondDialog).getByRole("button", { name: "Invite user" }));
    await waitFor(() => expect(harness.posts()).toHaveLength(2));
    expect(JSON.parse(harness.posts()[1].body ?? "{}")).toEqual({ email: "second-session@example.com", role: "driver" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("ignores an earlier invitation error decoded after a new dialog session opens", async () => {
    let resolveErrorJson!: (body: unknown) => void;
    const response = json({}, 403);
    const decodeError = vi.spyOn(response, "json").mockImplementation(
      () => new Promise((resolve) => { resolveErrorJson = resolve; })
    );
    postHandler = () => response;
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    const firstDialog = await openInviteDialog(user);
    await user.click(within(firstDialog).getByLabelText("Email address"));
    await user.paste("first-session@example.com");
    await user.click(within(firstDialog).getByRole("button", { name: "Invite user" }));
    await waitFor(() => expect(decodeError).toHaveBeenCalled());
    await user.click(within(firstDialog).getByRole("button", { name: "Cancel" }));
    const secondDialog = await openInviteDialog(user);
    await user.click(within(secondDialog).getByLabelText("Email address"));
    await user.paste("second-session@example.com");
    await act(async () => resolveErrorJson({ detail: "First invitation denied." }));
    expect(within(secondDialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(secondDialog).getByLabelText("Email address")).toHaveValue("second-session@example.com");
    expect(within(secondDialog).getByRole("button", { name: "Invite user" })).toBeEnabled();
  });

  it("keeps the entered values and announces a server error", async () => {
    postHandler = () => json({ detail: "Invite denied: Admin role required." }, 403);
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    await chooseOption(user, dialog, "Role", "Admin");
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("keep@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Invite user" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(/Invite denied: Admin role required\./);
    expect(within(dialog).getByLabelText("Email address")).toHaveValue("keep@example.com");
    expect(within(dialog).getByLabelText("Role")).toHaveTextContent("Admin");
    expect(screen.queryByText(/Invitation added/i)).not.toBeInTheDocument();
  });

  it("keeps the entered values on a network failure", async () => {
    postHandler = () => Promise.reject(new Error("network down"));
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    const dialog = await openInviteDialog(user);
    await user.click(within(dialog).getByLabelText("Email address"));
    await user.paste("offline@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Invite user" }));

    await waitFor(() => expect(within(dialog).getByRole("alert")).toBeInTheDocument());
    expect(within(dialog).getByLabelText("Email address")).toHaveValue("offline@example.com");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText(/Invitation added/i)).not.toBeInTheDocument();
  });

  it("composes member search, role filter, and sorting with aria-sort", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");

    const region = membersRegion();
    expect(within(region).getAllByRole("row").length).toBe(4);

    await user.type(within(region).getByLabelText("Search members"), "e");
    // Marcus, Elena, Carlos all contain "e"; narrow with the role filter.
    await chooseOption(user, region, "Filter members by role", "Analyst");
    await waitFor(() => expect(within(region).getByText("Elena Rostova")).toBeInTheDocument());
    expect(within(region).queryByText("Marcus Vance")).not.toBeInTheDocument();
    expect(within(region).queryByText("Carlos Mendez")).not.toBeInTheDocument();

    await user.click(within(region).getByRole("button", { name: "Member" }));
    const header = within(region).getByRole("columnheader", { name: "Member" });
    expect(header).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(region).getByRole("button", { name: "Member" }));
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("shows reset guidance for a filtered empty result, distinct from an empty organization", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");

    const region = membersRegion();
    await user.type(within(region).getByLabelText("Search members"), "zzzz-no-match");
    expect(await within(region).findByText(/no members match your filter/i)).toBeInTheDocument();
    expect(within(region).getByText(/try a different name, role, or status/i)).toBeInTheDocument();
  });

  it("disables pagination at page boundaries and pages invitations using the returned total", async () => {
    usersQueue = [() => json([MEMBERS_A[0]])];
    const firstInvitePage = Array.from({ length: 50 }, (_, i) => ({
      id: `inv_${i}`,
      email: `invite${i}@example.com`,
      role: "analyst",
      status: "pending",
    }));
    const secondInvitePage = Array.from({ length: 25 }, (_, i) => ({
      id: `inv_${50 + i}`,
      email: `invite${50 + i}@example.com`,
      role: "driver",
      status: "pending",
    }));
    invitesQueue = [
      () => json({ items: firstInvitePage, total: 75 }),
      () => json({ items: secondInvitePage, total: 75 }),
    ];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Marcus Vance");

    const membersPrev = screen.getByRole("button", { name: /previous members page/i });
    const membersNext = screen.getByRole("button", { name: /next members page/i });
    expect(membersPrev).toBeDisabled();
    expect(membersNext).toBeDisabled();

    const invitesNext = screen.getByRole("button", { name: /next invitations page/i });
    const invitesPrev = screen.getByRole("button", { name: /previous invitations page/i });
    expect(invitesPrev).toBeDisabled();
    expect(invitesNext).toBeEnabled();

    await user.click(invitesNext);
    await waitFor(() => expect(harness.invitations().length).toBeGreaterThanOrEqual(2));
    expect(harness.invitations()[1].url).toContain("offset=50");
    await waitFor(() => expect(screen.getByRole("button", { name: /next invitations page/i })).toBeDisabled());
    expect(screen.getByRole("button", { name: /previous invitations page/i })).toBeEnabled();
  });

  it("recognizes fraud_analyst as Analyst for presentation and filtering", async () => {
    usersQueue = [() => json([{ id: "usr_fa", display_name: "Priya Nair", roles: ["fraud_analyst"], status: "active" }])];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Priya Nair");

    const region = membersRegion();
    expect(within(region).getAllByText("Analyst").length).toBeGreaterThan(0);

    await chooseOption(user, region, "Filter members by role", "Analyst");
    await waitFor(() => expect(within(region).getByText("Priya Nair")).toBeInTheDocument());
    expect(screen.queryByText("No analysts on this page.")).not.toBeInTheDocument();
  });

  it("shows the no-analyst warning only after a successful non-empty member load", async () => {
    usersQueue = [() => json([{ ...MEMBERS_A[0], roles: ["admin"] }])];
    render(<OrganizationManagement />);
    await screen.findByText("Marcus Vance");
    expect(screen.getByText("No analysts on this page.")).toBeInTheDocument();
    expect(screen.getByText(/Invite an analyst to help review cases/i)).toBeInTheDocument();
  });

  it.each([
    { roles: [], placeholder: "Unassigned" },
    { roles: ["custom_role"], placeholder: "Unknown role" },
  ])("does not invent an Analyst selection for $placeholder member roles", async ({ roles, placeholder }) => {
    usersQueue = [() => json([{ ...MEMBERS_A[1], roles }])];
    render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");
    const role = screen.getByRole("combobox", { name: "Change role for Elena Rostova" });
    expect(role).toHaveTextContent(placeholder);
    expect(role).not.toHaveTextContent("Analyst");
    expect(harness.calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("preserves the previous role and surfaces the error when a role update is denied", async () => {
    patchHandlers = {
      usr_elena: () => json({ detail: "Cannot demote the last admin in the organization" }, 403),
    };
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Elena Rostova");

    const region = membersRegion();
    const select = within(region).getByLabelText("Change role for Elena Rostova");
    expect(select).toHaveTextContent("Analyst");

    await chooseOption(user, region, "Change role for Elena Rostova", "Admin");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/cannot demote the last admin/i));
    await waitFor(() =>
      expect(within(region).getByLabelText("Change role for Elena Rostova")).toHaveTextContent("Analyst")
    );
  });

  it("updates the role from the authoritative response", async () => {
    patchHandlers = {
      usr_carlos: () => json({ id: "usr_carlos", display_name: "Carlos Mendez", roles: ["analyst"], status: "active" }),
    };
    usersQueue = [
      () => json(DEFAULT_MEMBERS()),
      () => json([
        DEFAULT_MEMBERS()[0],
        DEFAULT_MEMBERS()[1],
        { id: "usr_carlos", display_name: "Carlos Mendez", roles: ["analyst"], status: "active" },
      ]),
    ];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Carlos Mendez");

    const region = membersRegion();
    await chooseOption(user, region, "Change role for Carlos Mendez", "Analyst");
    await waitFor(() =>
      expect(within(region).getByLabelText("Change role for Carlos Mendez")).toHaveTextContent("Analyst")
    );
    expect(harness.calls.some((c) => c.method === "PATCH" && c.path.endsWith("/usr_carlos/role"))).toBe(true);
  });

  it("preserves explicitly empty grants returned by a successful role update", async () => {
    patchHandlers.usr_carlos = () => json({ id: "usr_carlos", roles: [] });
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Carlos Mendez");
    await chooseOption(user, membersRegion(), "Change role for Carlos Mendez", "Analyst");
    await screen.findByText("Role updated.");
    expect(screen.getByLabelText("Change role for Carlos Mendez")).toHaveTextContent("Unassigned");
    expect(screen.getByLabelText("Change role for Carlos Mendez")).not.toHaveTextContent("Analyst");
  });

  it("keeps resend/revoke as existing endpoints, disabled for non-pending rows", async () => {
    invitesQueue = [() => json({ items: INVITES, total: INVITES.length })];
    actionHandlers = {
      "inv_pending:revoke": () => json({ id: "inv_pending", status: "revoked" }),
      "inv_pending:resend": () => json({ id: "inv_pending", status: "pending" }),
    };
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("sarah.chen@example.com");

    const revokedRow = screen.getByText("alex.t@example.com").closest("tr") as HTMLElement;
    expect(within(revokedRow).getByRole("button", { name: "Resend" })).toBeDisabled();
    expect(within(revokedRow).getByRole("button", { name: "Revoke" })).toBeDisabled();

    const pendingRow = screen.getByText("sarah.chen@example.com").closest("tr") as HTMLElement;
    await user.click(within(pendingRow).getByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(harness.calls.some((c) => c.path === "/api/v1/admin/invitations/inv_pending/revoke")).toBe(true)
    );
  });

  it("does not render bootstrap/link controls or call their endpoints or account settings", async () => {
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("Members");

    expect(screen.queryByText(/population bootstrap/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/link driver/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/driver-id/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/principal-id/i)).not.toBeInTheDocument();

    expect(harness.calls.every((c) => !c.url.includes("/bootstrap"))).toBe(true);
    expect(harness.calls.every((c) => !c.url.includes("/link"))).toBe(true);
    expect(harness.calls.every((c) => !c.url.includes("/account/settings"))).toBe(true);

    void user;
  });

  it("hides the previous roster immediately and ignores a late response after an organization change", async () => {
    let resolveA: (r: Response) => void = () => {};
    let resolveB: (r: Response) => void = () => {};
    usersQueue = [
      () => new Promise<Response>((resolve) => { resolveA = resolve; }),
      () => new Promise<Response>((resolve) => { resolveB = resolve; }),
    ];
    invitesQueue = [() => json({ items: [], total: 0 }), () => json({ items: [], total: 0 })];

    const { rerender } = render(<OrganizationManagement />);
    await waitFor(() => expect(harness.users().length).toBe(1));

    auth.orgId = "org-b";
    rerender(<OrganizationManagement />);
    await waitFor(() => expect(harness.users().length).toBe(2));
    // While the new organization loads, no previous row may be visible.
    expect(screen.queryByText("Elena Rostova")).not.toBeInTheDocument();

    resolveB(json([{ id: "usr_marcus", display_name: "Marcus Vance", roles: ["admin"], status: "active" }]));
    await screen.findByText("Marcus Vance");

    // A late response for the previous organization must be ignored.
    resolveA(json([{ id: "usr_elena", display_name: "Elena Rostova", roles: ["analyst"], status: "active" }]));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Elena Rostova")).not.toBeInTheDocument();
    expect(screen.getByText("Marcus Vance")).toBeInTheDocument();
  });

  it("renders the auth bypass indicator without Clerk provider in E2E mode", async () => {
    process.env.NEXT_PUBLIC_E2E_TEST = "true";
    render(<OrganizationManagement />);
    expect(await screen.findByTestId("e2e-auth-indicator")).toBeInTheDocument();
  });

  it("counts only visible filtered invitations and resets invitation filters", async () => {
    invitesQueue = [() => json({ items: INVITES, total: 2 })];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("sarah.chen@example.com");

    const section = screen.getByRole("heading", { name: "Invitations" }).closest("section")!;
    // Both invites visible by default: showing 2 of 2
    expect(within(section).getByText("Showing 2 of 2 invites on this page")).toBeInTheDocument();

    // Filter by role=analyst: only sarah.chen (analyst) matches
    await chooseOption(user, section as HTMLElement, "Filter invitations by role", "Analyst");
    await waitFor(() => expect(within(section).getByText("Showing 1 of 2 invites on this page")).toBeInTheDocument());
    expect(within(section).getByText("sarah.chen@example.com")).toBeInTheDocument();
    expect(within(section).queryByText("alex.t@example.com")).not.toBeInTheDocument();

    // Reset filters: both invites visible again
    await user.click(within(section as HTMLElement).getByRole("button", { name: "Reset invitation filters" }));
    await waitFor(() => expect(within(section).getByText("Showing 2 of 2 invites on this page")).toBeInTheDocument());
    expect(within(section).getByText("alex.t@example.com")).toBeInTheDocument();
  });

  it("sorts invitations by email with aria-sort and filters by status", async () => {
    invitesQueue = [() => json({ items: INVITES, total: 2 })];
    const user = userEvent.setup();
    render(<OrganizationManagement />);
    await screen.findByText("sarah.chen@example.com");

    const section = screen.getByRole("heading", { name: "Invitations" }).closest("section")!;

    // Sort ascending by email: alex.t should come before sarah.chen
    await user.click(within(section as HTMLElement).getByRole("button", { name: "Email" }));
    const header = within(section).getByRole("columnheader", { name: "Email" });
    expect(header).toHaveAttribute("aria-sort", "ascending");
    const rowsAsc = within(section).getAllByRole("row").slice(1);
    expect(rowsAsc[0]).toHaveTextContent("alex.t@example.com");

    // Sort descending
    await user.click(within(section as HTMLElement).getByRole("button", { name: "Email" }));
    expect(header).toHaveAttribute("aria-sort", "descending");
    const rowsDesc = within(section).getAllByRole("row").slice(1);
    expect(rowsDesc[0]).toHaveTextContent("sarah.chen@example.com");

    // Filter by status=pending: only sarah.chen (pending) matches
    await chooseOption(user, section as HTMLElement, "Filter invitations by status", "Pending");
    await waitFor(() => expect(within(section).queryByText("alex.t@example.com")).not.toBeInTheDocument());
    expect(within(section).getByText("Showing 1 of 2 invites on this page")).toBeInTheDocument();
  });
});
