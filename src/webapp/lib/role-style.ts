/** Role badge colours + labels from the GSM reference ROLES table (ADR-031). */
export type RoleStyle = { label: string; bg: string; fg: string; vi: string; en: string };

const KSGL = { label: "KSGL", bg: "#f0e6fb", fg: "#7b3ed6", vi: "Kiểm soát gian lận", en: "Fraud analyst" };
const SYSTEM = { label: "System", bg: "#eef1f4", fg: "#5a6b78", vi: "Hệ thống", en: "System" };

/** Keyed by backend role. */
const ROLE_STYLE: Record<string, RoleStyle> = {
  admin: { label: "ADMIN", bg: "#e3ecfb", fg: "#3b6fd6", vi: "Quản trị", en: "Admin" },
  senior_analyst: { ...KSGL, label: "KSGL+" },
  fraud_analyst: KSGL,
  analyst: KSGL,
  driver: { label: "TX", bg: "#e3f6e8", fg: "#22a45d", vi: "Tài xế", en: "Driver" },
  reviewer: { label: "KSCL", bg: "#fbe9d6", fg: "#c8791e", vi: "Depot · Kiểm soát chất lượng", en: "Depot reviewer" },
  ops_director: { label: "OPS_DIR", bg: "#e3ecfb", fg: "#3b6fd6", vi: "Giám đốc vận hành", en: "Operations director" },
  marketplace_director: { label: "MKP_DIR", bg: "#fde4e4", fg: "#e0484b", vi: "Giám đốc Marketplace", en: "Marketplace director" },
};

/** Keyed by reference actor code (stepper chips). */
const CODE_TO_ROLE: Record<string, string> = {
  KSGL: "fraud_analyst", KSCL: "reviewer", OPS_DIR: "ops_director", MKP_DIR: "marketplace_director", TX: "driver",
};

export function roleStyle(role?: string | null): RoleStyle {
  const key = (role ?? "").toLowerCase();
  if (key === "system") return SYSTEM;
  return ROLE_STYLE[key] ?? { ...SYSTEM, label: (role ?? "—").toUpperCase(), vi: role ?? "—", en: role ?? "—" };
}

/** Style for a reference actor code (KSGL / KSCL / OPS_DIR / MKP_DIR / TX / System). */
export const actorStyle = (code?: string | null): RoleStyle => roleStyle(CODE_TO_ROLE[code ?? ""] ?? code);
