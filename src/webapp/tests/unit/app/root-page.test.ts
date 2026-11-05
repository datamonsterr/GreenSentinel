// @vitest-environment node
import { expect, test, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({ auth: vi.fn(), redirect: vi.fn(), notFound: vi.fn() }));
const { auth, redirect, notFound } = mocks;
redirect.mockImplementation((path: string): never => {
  throw Object.assign(new Error(`redirect:${path}`), { digest: "NEXT_REDIRECT" });
});
notFound.mockImplementation((): never => {
  throw Object.assign(new Error("not-found"), { digest: "NEXT_HTTP_ERROR_F_NOT_FOUND" });
});

vi.mock("@clerk/nextjs/server", () => ({ auth: mocks.auth }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect, notFound: mocks.notFound }));
vi.mock("next/headers", () => ({ headers: vi.fn(async () => new Headers({ host: "preview.example.com" })) }));
vi.mock("@/components/landing/landing-page", () => ({ LandingPage: () => null }));

const { default: RootPage } = await import("../../../app/page");

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn());
  delete process.env.E2E_TEST;
  delete process.env.NEXT_PUBLIC_E2E_TEST;
  delete process.env.NEXT_PUBLIC_APP_MODE;
});

test.each([
  ["admin", ["admin"], "/organization"],
  ["analyst", ["analyst"], "/workspace"],
  ["driver", ["driver"], "/driver"],
])("redirects %s after settings resolution", async (_name, roles, expected) => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 401 }));
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 404 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ organization_id: "org_1", roles }), { status: 200 }));

  await expect(RootPage()).rejects.toThrow(`redirect:${expected}`);
  expect(notFound).not.toHaveBeenCalled();
});

test("keeps a valid account route redirect outside the catch", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ route: "/organization" }), { status: 200 }));

  await expect(RootPage()).rejects.toThrow("redirect:/organization");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each([
  ["//evil.example", 200],
  ["/bad", 401],
])("fails closed for unsafe or unavailable route response %s (%s)", async (route, status) => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ route }), { status }));

  await expect(RootPage()).rejects.toThrow("not-found");
  expect(redirect).not.toHaveBeenCalled();
});

test("fails closed when the session has no token", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue(null) });

  await expect(RootPage()).rejects.toThrow("not-found");
  expect(fetch).not.toHaveBeenCalled();
});


test("does not override account route denial 401 with settings fallback", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ organization_id: "org_1", roles: ["admin"] }), { status: 200 }));
  await expect(RootPage()).rejects.toThrow("not-found");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("guides unprovisioned users to onboarding on route denial 403", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 403 }));
  await expect(RootPage()).rejects.toThrow("redirect:/onboarding");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(notFound).not.toHaveBeenCalled();
});

test("guides unprovisioned users to onboarding on settings denial 403", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 404 }))
    .mockResolvedValueOnce(new Response("{}", { status: 403 }));
  await expect(RootPage()).rejects.toThrow("redirect:/onboarding");
  expect(notFound).not.toHaveBeenCalled();
});

test("rejects an unexpected internal destination", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ route: "/unrelated" }), { status: 200 }));
  await expect(RootPage()).rejects.toThrow("not-found");
});

test("settings fallback requires an assigned supported role", async () => {
  auth.mockResolvedValue({ userId: "user_1", getToken: vi.fn().mockResolvedValue("token") });
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 404 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ organization_id: "org_1", roles: [] }), { status: 200 }));
  await expect(RootPage()).rejects.toThrow("not-found");
});

test("signed-out root renders the public landing experience", async () => {
  auth.mockResolvedValue({ userId: null });
  const { LandingPage } = await import("../../../components/landing/landing-page");
  const element = await RootPage();
  expect(element?.type).toBe(LandingPage);
  expect(redirect).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

test("auth failure falls back to landing instead of 500 (Refs #181)", async () => {
  auth.mockRejectedValue(new Error("Clerk: auth() was called but Clerk can't detect usage of clerkMiddleware()"));
  const { LandingPage } = await import("../../../components/landing/landing-page");
  const element = await RootPage();
  expect(element?.type).toBe(LandingPage);
  expect(redirect).not.toHaveBeenCalled();
  expect(notFound).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});
