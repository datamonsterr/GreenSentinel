import { requireDriverCaseAccess } from '@/lib/server-route-guard';

export default async function DriverCaseLayout({ children, params }: {
  children: React.ReactNode;
  params: Promise<{ caseId: string }>;
}) {
  await requireDriverCaseAccess((await params).caseId);
  return children;
}
