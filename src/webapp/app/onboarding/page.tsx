"use client";

import Link from "next/link";
import { SignOutButton } from "@clerk/nextjs";

// Public provisioning-pending page. Signed-in visitors land here when the
// backend knows no organization or role for their identity (S4-CONTRACT
// #291): fail-closed for protected routes, but with guidance instead of a
// bare 403. Keyless envs (no Clerk keys) render plain links; keyed envs use
// SignOutButton so switching accounts fully clears the Clerk session before
// signing in again.

export default function OnboardingPage() {
  // Evaluated per render so tests can cover both branches via env stubs.
  const clerkKeyed = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  return (
    <div className="flex-1 flex items-center justify-center p-6 overflow-y-auto">
      <div className="w-full max-w-md flex flex-col gap-4 border rounded-lg p-6 bg-white">
        <h1 className="text-lg font-semibold">Account pending setup</h1>
        <p className="text-sm text-slate-600">
          You are signed in, but no organization or role is assigned to this
          account yet. An administrator needs to add you to an organization
          with an analyst, driver, or admin role before you can open the
          workplace, driver portal, or analytics.
        </p>
        <ol className="text-sm text-slate-600 list-decimal list-inside flex flex-col gap-1">
          <li>Ask your organization administrator for an invite.</li>
          <li>
            Use Switch account below to sign out, then sign back in — the fresh
            session picks up the new role.
          </li>
          <li>
            Just created a new organization as its admin?{" "}
            <Link href="/organization" className="underline">
              Open organization
            </Link>{" "}
            to finish setting it up — you will be routed to your workspace automatically.
          </li>
        </ol>
        <div className="flex gap-2">
          <Link
            href="/"
            className="text-sm border rounded px-3 py-1.5 hover:bg-slate-50"
          >
            Back to home
          </Link>
          {clerkKeyed ? (
            <SignOutButton redirectUrl="/sign-in">
              <button
                type="button"
                className="text-sm border rounded px-3 py-1.5 hover:bg-slate-50"
              >
                Switch account
              </button>
            </SignOutButton>
          ) : (
            <Link
              href="/sign-in"
              className="text-sm border rounded px-3 py-1.5 hover:bg-slate-50"
            >
              Switch account
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
