import { clerkMiddleware } from '@clerk/nextjs/server';
import { NextResponse, type NextRequest, type NextFetchEvent } from 'next/server';
import { decideArea, localTestAuthentication, protectedArea } from './lib/route-authorization';
import { isolatedGisBuild } from './lib/isolated-gis-build';
import { primaryRoleFor } from './lib/role-routing';

const authenticated = clerkMiddleware(async (auth, request) => {
  const area = protectedArea(request.nextUrl.pathname);
  if (!area) return NextResponse.next();
  const session = await auth();
  if (!session.userId) {
    const url = new URL('/sign-in', request.url);
    url.searchParams.set('redirect_url', request.url);
    return NextResponse.redirect(url);
  }
  const token = await session.getToken();
  if (!token) {
    console.warn(`[middleware] No session token available for user ${session.userId} requesting ${area}`);
    return new NextResponse('Access denied', { status: 403 });
  }
  const decision = await decideArea(token, area, request.url);
  if (decision === 'allow') return NextResponse.next();
  if (decision === 'unprovisioned') {
    // Signed in, but the backend knows no organization or role for this
    // identity (S4-CONTRACT #291). Guide to onboarding instead of a bare 403.
    console.warn(`[middleware] Unprovisioned user ${session.userId} requesting ${area}; redirecting to onboarding`);
    return NextResponse.redirect(new URL('/onboarding', request.url));
  }
  if (decision === 'unreachable') {
    return new NextResponse('Authentication unavailable', { status: 503 });
  }
  if (typeof decision === 'object' && decision.kind === 'wrong_role') {
    // Known, provisioned identity with the wrong role for this area: guide
    // to a rendered switch-account page instead of a bare 403.
    const role = primaryRoleFor(decision.roles);
    console.warn(`[middleware] Wrong-role user ${session.userId} (${role}) requesting ${area}; rewriting to access-denied`);
    return NextResponse.rewrite(new URL(`/access-denied?role=${role}`, request.url), { status: 403 });
  }
  console.warn(`[middleware] Authorization check failed for user ${session.userId} requesting ${area}`);
  return new NextResponse('Access denied', { status: 403 });
});

export default async function middleware(request: NextRequest, event: NextFetchEvent) {
  const hostname = request.headers.get('host')?.split(':')[0] || new URL(request.url).hostname;
  if (isolatedGisBuild() && !['127.0.0.1', 'localhost'].includes(hostname)) {
    return new NextResponse('Access denied', { status: 403 });
  }
  if (localTestAuthentication()) return NextResponse.next();
  // Keyless public passthrough: without a Clerk publishable key the Clerk
  // handler below throws before the page renders. Public routes (no protected
  // area, e.g. `/`) skip Clerk so the landing stays 200 in keyless
  // local/preview envs. Protected routes stay fail-closed via the 503 below.
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && !protectedArea(request.nextUrl.pathname)) {
    return NextResponse.next();
  }
  try {
    return await authenticated(request, event);
  } catch (error) {
    // Report only exception type and a known transport code, never tokens or
    // provider messages that may contain authentication credentials.
    const name = error instanceof Error ? error.name : 'UnknownError';
    const cause = error instanceof Error ? error.cause as { code?: unknown } | undefined : undefined;
    const code = typeof cause?.code === 'string' &&
      ['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN'].includes(cause.code)
      ? cause.code : 'unavailable';
    console.error('[middleware] Authentication unavailable', { name, code });
    // Invalid configuration, expired sessions and backend failures never expose a page.
    return new NextResponse('Authentication unavailable', { status: 503 });
  }
}

export const config = {
  // `/` is matched so Clerk context exists for RootPage's auth() (Refs #181).
  // Public routes need no session: the handler returns next() when there is
  // no protected area. Keyless envs (no Clerk keys) bypass Clerk above so the
  // public landing still renders instead of 503.
  matcher: ['/', '/onboarding', '/test/:path*', '/workplace/:path*', '/workspace/:path*', '/organization/:path*', '/knowledge/:path*', '/driver/:path*', '/dashboard/:path*', '/analytics/:path*',
    '/profile/:path*', '/sign-in/:path*', '/sign-up/:path*', '/__clerk/:path*'],
};
