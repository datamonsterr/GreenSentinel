import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import en from "../messages/en.json";
import vi from "../messages/vi.json";
import { KB_STATUSES, KB_TYPES } from "../lib/knowledge-ui";

type Tree = { [k: string]: string | Tree };
const flatten = (o: Tree, prefix = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (typeof v === "string" ? [`${prefix}${k}`] : flatten(v, `${prefix}${k}.`)));
const get = (o: Tree, key: string): unknown => key.split(".").reduce<unknown>((cur, k) => (cur && typeof cur === "object" ? (cur as Tree)[k] : undefined), o);

const dir = path.join(__dirname, "../components/knowledge");
const sources = readdirSync(dir).filter((f) => f.endsWith(".tsx")).map((f) => readFileSync(path.join(dir, f), "utf8"));

test("vi and en knowledge namespaces have identical keys", () => {
  const e = flatten((en as unknown as { knowledge: Tree }).knowledge).sort();
  const v = flatten((vi as unknown as { knowledge: Tree }).knowledge).sort();
  expect(v).toEqual(e);
});

test("every static t('key') used by the knowledge UI exists in both languages", () => {
  const keys = new Set<string>();
  for (const src of sources) for (const m of src.matchAll(/\bt\(\s*"([A-Za-z0-9_.]+)"/g)) keys.add(m[1]);
  expect(keys.size).toBeGreaterThan(80);
  const missing = [...keys].filter((k) => get((en as unknown as { knowledge: Tree }).knowledge, k) === undefined || get((vi as unknown as { knowledge: Tree }).knowledge, k) === undefined);
  expect(missing).toEqual([]);
});

test("enumerated labels exist for every type and status", () => {
  for (const lang of [en, vi] as unknown as { knowledge: Tree }[]) {
    for (const tp of KB_TYPES) expect(get(lang.knowledge, `types.${tp}`)).toBeTypeOf("string");
    for (const s of KB_STATUSES) expect(get(lang.knowledge, `status.${s}`)).toBeTypeOf("string");
  }
});
