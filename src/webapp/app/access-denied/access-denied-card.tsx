"use client";

import Link from "next/link";
import { SignOutButton } from "@clerk/nextjs";
import { DRIVER_ROUTE, ORGANIZATION_ROUTE, WORKSPACE_ROUTE } from "../../lib/role-routing";

// Role-mismatch landing page. Signed-in users with a valid, provisioned
// principal but the wrong role for the area they tried to open (middleware
// `wrong_role` decision) land here instead of a bare 403, with guidance to
// switch accounts or go back to the view their role does allow.

const BACK_TARGETS: Record<string, { label: string; href: string }> = {
  driver: { label: "driver", href: DRIVER_ROUTE },
  analyst: { label: "analyst", href: WORKSPACE_ROUTE },
  admin: { label: "admin", href: ORGANIZATION_ROUTE },
};

export function AccessDeniedCard({ role }: { role: string | null }) {
  const clerkKeyed = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const target = role ? BACK_TARGETS[role] : undefined;
  const backLabel = target ? `Back to ${target.label} view` : "Back to home";
  const backHref = target ? target.href : "/";

  return (
    <div className="flex-1 flex items-center justify-center p-6 overflow-y-auto">
      <div className="w-full max-w-md flex flex-col gap-4 border rounded-lg p-6 bg-white">
        <h1 className="text-lg font-semibold">
          This view is not available for your account
        </h1>
        <p className="text-sm text-gs-mute-2">
          The account you are signed in with does not have the role needed to
          open this page. Switch to an account with the right role, or go
          back to the view your account can use.
        </p>
        <div className="flex gap-2">
          <Link
            href={backHref}
            className="text-sm border rounded px-3 py-1.5 hover:bg-surface-container-low"
          >
            {backLabel}
          </Link>
          {clerkKeyed ? (
            <SignOutButton redirectUrl="/sign-in">
              <button
                type="button"
                className="text-sm border rounded px-3 py-1.5 hover:bg-surface-container-low"
              >
                Switch account
              </button>
            </SignOutButton>
          ) : (
            <Link
              href="/sign-in"
              className="text-sm border rounded px-3 py-1.5 hover:bg-surface-container-low"
            >
              Switch account
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
