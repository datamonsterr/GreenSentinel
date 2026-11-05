import { requirePageAccess } from '@/lib/server-route-guard';

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  await requirePageAccess('workplace');
  return children;
}
