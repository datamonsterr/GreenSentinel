import { AccessDeniedCard } from "./access-denied-card";

// Server page: reads the `role` search param set by middleware's rewrite
// (`/access-denied?role=<primaryRole>`) and hands only that string down.
// Never pass tokens or user ids here (middleware only forwards the role).
export default async function AccessDeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ role?: string | string[] }>;
}) {
  const resolved = await searchParams;
  const role = typeof resolved.role === "string" ? resolved.role : null;
  return <AccessDeniedCard role={role} />;
}
