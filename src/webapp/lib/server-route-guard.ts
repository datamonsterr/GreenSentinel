import 'server-only';
import { auth } from '@clerk/nextjs/server';
import { notFound, redirect } from 'next/navigation';
import { authorizedArea, authorizedDriverCase, localTestAuthentication, type ProtectedArea } from './route-authorization';

export async function requirePageAccess(area: ProtectedArea): Promise<void> {
  if (localTestAuthentication()) return;
  const session = await auth({ treatPendingAsSignedOut: false });
  if (!session.userId) redirect('/sign-in');
  const token = await session.getToken();
  if (!token || !await authorizedArea(token, area)) notFound();
}

export async function requireDriverCaseAccess(caseId: string): Promise<void> {
  if (localTestAuthentication()) return;
  const session = await auth({ treatPendingAsSignedOut: false });
  if (!session.userId) redirect('/sign-in');
  const token = await session.getToken();
  if (!token || !await authorizedDriverCase(token, caseId)) notFound();
}
