/** Optimized GIS test artifact: never deploy this build to a hosted environment. */
export function isolatedGisBuild(): boolean {
  if (process.env.NEXT_PUBLIC_GIS_OPTIMIZED_TEST !== 'true'
    || process.env.NEXT_PUBLIC_E2E_TEST !== 'true') return false;
  try {
    const backend = new URL(process.env.NEXT_PUBLIC_API_URL || '');
    return backend.protocol === 'http:' && backend.hostname === '127.0.0.1';
  } catch {
    return false;
  }
}
