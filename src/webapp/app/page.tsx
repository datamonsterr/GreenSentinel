import { auth } from "@clerk/nextjs/server";
import { notFound, redirect } from "next/navigation";
import { headers } from "next/headers";
import { resolveBackendUrl } from "@/lib/route-authorization";
import { DRIVER_ROUTE, ORGANIZATION_ROUTE, WORKSPACE_ROUTE, resolveInitialRoute } from "@/lib/role-routing";

const INITIAL_ROUTES = new Set([DRIVER_ROUTE, ORGANIZATION_ROUTE, WORKSPACE_ROUTE]);

// Root-resolver pattern (S4-ENTRY #296, ADR-025): "/" is the single
// server-verified entry. Sign-in/sign-up fall back here; direct links,
// invite accept, reload, and org switch all re-resolve per request.
export default async function RootPage() {
  const headerList = await headers();
  const host = headerList.get("host") || "";

  if (host.includes("driver") || process.env.NEXT_PUBLIC_APP_MODE === "driver") {
    redirect("/driver");
  }

  if (process.env.E2E_TEST === "true" || process.env.NEXT_PUBLIC_E2E_TEST === "true") {
    redirect("/workspace");
  }

  async function renderLanding() {
    // Signed-out visitors see the public landing experience (#308/#286).
    // Dynamic import: keeps the static landing mock out of the auth bundle.
    const { LandingPage } = await import("@/components/landing/landing-page");
    return <LandingPage />;
  }

  // Auth() requires Clerk middleware context (matcher must cover `/`,
  // Refs #181). Missing keys, unreachable Clerk, or missing context must
  // fall back to the public landing, never 500.
  let userId: string | null;
  let getToken: () => Promise<string | null>;
  try {
    const session = await auth();
    userId = session.userId;
    getToken = session.getToken;
  } catch {
    return renderLanding();
  }

  if (userId) {
    let destination: string | null = null;
    // Backend 403 means the identity is unknown to the app (no organization
    // or role, S4-CONTRACT #291): route to onboarding guidance, never 404.
    let unprovisioned = false;
    try {
      const token = await getToken();
      if (!token) notFound();
      const backend = resolveBackendUrl(host);
      const res = await fetch(`${backend}/api/v1/account/route`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      if (res.ok) {
        const body = await res.json();
        if (!INITIAL_ROUTES.has(body?.route)) notFound();
        destination = body.route;
      } else if (res.status === 403) {
        unprovisioned = true;
      } else if (res.status !== 404) {
        notFound();
      }
      if (!destination && !unprovisioned) {
        const settings = await fetch(`${backend}/api/v1/account/settings`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
          signal: AbortSignal.timeout(10_000),
        });
        if (settings.ok) {
          const principal = await settings.json();
          if (!principal?.organization_id || !Array.isArray(principal.roles) ||
              !principal.roles.some((role: string) =>
                ["admin", "analyst", "fraud_analyst", "senior_analyst", "driver"].includes(role))) notFound();
          destination = resolveInitialRoute(principal?.roles);
        } else if (settings.status === 403) {
          unprovisioned = true;
        } else {
          notFound();
        }
      }
    } catch (error) {
      // Next's notFound() and redirect() use control-flow exceptions. Preserve
      // them; unavailable or unauthorized account resolution must fail closed.
      if (error && typeof error === "object" && "digest" in error) throw error;
      notFound();
    }
    if (unprovisioned) redirect("/onboarding");
    if (destination) redirect(destination);
    notFound();
  }

  return renderLanding();
}
