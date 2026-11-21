import { describe, expect, it } from "vitest";
import type { KbObject } from "@/lib/knowledge-client";
import { parseApiError } from "@/lib/knowledge-client";
import { canAuthor, defaultBody, formulaField, isApprover, objectActions, splitAtPosition, toLines } from "@/lib/knowledge-ui";

const obj = (over: Partial<KbObject>): KbObject => ({
  id: "o1", type: "motive", code: "MOT_A", version: 1, status: "draft", name: "A", scope: {}, body: {}, change_reason: null,
  author_id: "u-analyst", author_name: "Hà", approver_id: null, approver_name: null, replay: null, override_reason: null,
  retired_reason: null, history: [], created_at: "", updated_at: "", published_at: null, ...over,
});
const analyst = { id: "u-analyst", roles: ["fraud_analyst"] };
const admin = { id: "u-admin", roles: ["admin"] };

describe("knowledge roles", () => {
  it("separates authors from approvers", () => {
    expect(canAuthor(["fraud_analyst"])).toBe(true);
    expect(canAuthor(["driver"])).toBe(false);
    expect(isApprover(["fraud_analyst"])).toBe(false);
    expect(isApprover(["senior_analyst"])).toBe(true);
  });
});

describe("objectActions mirrors the lifecycle", () => {
  it("draft: edit + submit, nothing else", () => {
    const a = objectActions(obj({ status: "draft" }), analyst);
    expect(a).toMatchObject({ edit: true, submit: true, trial: false, publish: false, retire: true });
  });
  it("ready_for_test: trial", () => {
    expect(objectActions(obj({ status: "ready_for_test" }), analyst).trial).toBe(true);
  });
  it("trial: author cannot publish own work, other approver can", () => {
    const t = obj({ status: "trial" });
    expect(objectActions(t, analyst)).toMatchObject({ publish: false, publishBlocked: "role" });
    expect(objectActions(obj({ status: "trial", author_id: "u-admin" }), admin)).toMatchObject({ publish: false, publishBlocked: "author" });
    expect(objectActions(t, admin)).toMatchObject({ publish: true, publishBlocked: null });
  });
  it("gate failure demands an override", () => {
    const replay = { cases_total: 5, matched: 0, changed_scenario: 0, not_computable: 5, est_turns: 0, computable_ratio: 0, gate_passed: false, gate_min: 0.5, run_at: "" };
    expect(objectActions(obj({ status: "trial", replay }), admin).needsOverride).toBe(true);
  });
  it("published: rollback for approvers only; retired: nothing but clone", () => {
    expect(objectActions(obj({ status: "published" }), admin).rollback).toBe(true);
    expect(objectActions(obj({ status: "published" }), analyst).rollback).toBe(false);
    expect(objectActions(obj({ status: "retired" }), analyst)).toMatchObject({ retire: false, edit: false, clone: true });
  });
  it("hides clone when an unpublished sibling version exists", () => {
    expect(objectActions(obj({ status: "published" }), analyst, true).clone).toBe(false);
  });
});

describe("helpers", () => {
  it("knows the formula field per type", () => {
    expect(formulaField("motive")).toBe("formula");
    expect(formulaField("behavior")).toBe("condition");
    expect(formulaField("workflow")).toBeNull();
    expect(defaultBody("workflow")).toHaveProperty("steps");
  });
  it("splits lines", () => expect(toLines(" a \n\nb\n")).toEqual(["a", "b"]));
  it("splits a formula at an error position", () => {
    expect(splitAtPosition("=nope+1", 1)).toEqual(["=", "nope", "+1"]);
    expect(splitAtPosition("=1+1", undefined)).toEqual(["=1+1", "", ""]);
  });
  it("parses validation errors out of API error text", () => {
    const e = new Error('API Error 422: {"message":"Validation failed","errors":[{"code":"unknown_param","message":"x","path":"body.formula"}]}');
    expect(parseApiError(e)).toEqual({ message: "Validation failed", issues: [{ code: "unknown_param", message: "x", path: "body.formula" }] });
    expect(parseApiError(new Error("API Error 403: Four-eyes: the approver must differ")).message).toBe("Four-eyes: the approver must differ");
  });
});
