import { requirePageAccess } from '@/lib/server-route-guard';

export default async function KnowledgeLayout({ children }: { children: React.ReactNode }) {
  await requirePageAccess('knowledge');
  return children;
}
