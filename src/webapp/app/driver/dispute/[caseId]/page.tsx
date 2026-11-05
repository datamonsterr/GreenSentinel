import { redirect } from 'next/navigation';

export default async function DriverDisputeRedirect({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  redirect(`/driver/chat/${encodeURIComponent(caseId)}`);
}
