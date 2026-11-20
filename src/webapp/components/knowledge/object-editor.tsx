"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocale as useIntlLocale, useTranslations } from "next-intl";
import {
  knowledgeApi, parseApiError,
  type CatalogueParam, type FormulaCheck, type FormulaIssue, type KbObject, type KbType, type PreviewRow,
} from "@/lib/knowledge-client";
import {
  KB_TYPES, STATUS_TONE, defaultBody, formulaField, objectActions, splitAtPosition, toLines, type Me,
} from "@/lib/knowledge-ui";
import { Card, Chip, Field, Notice, SectionTitle, areaCls, btn, fmtDate, inputCls } from "@/components/knowledge/ui";

const SCOPE_KEYS = ["region", "service", "contract_type", "policy", "rule"] as const;
const TOOLS = ["identify_behavior", "list_motives", "compute_motive", "match_scenario", "get_workflow", "request_help", "propose_knowledge"];

type Props = {
  /** Existing object, or null when creating a new one. */
  obj: KbObject | null;
  createType: KbType;
  me: Me;
  catalogue: CatalogueParam[];
  onChanged: (o: KbObject) => void;
  onSelectVersion: (o: KbObject) => void;
  onClose: () => void;
};

function FormulaEditor({ type, value, onChange, catalogue, disabled }: {
  type: KbType; value: string; onChange: (v: string) => void; catalogue: CatalogueParam[]; disabled: boolean;
}) {
  const t = useTranslations("knowledge");
  const [check, setCheck] = useState<FormulaCheck | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!value.trim() || value.trim() === "=") { timer.current = setTimeout(() => setCheck(null), 0); return; }
    timer.current = setTimeout(() => {
      knowledgeApi.validateFormula(value).then(setCheck).catch(() => setCheck(null));
    }, 350);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [value]);
  const first = check?.errors[0];
  const [pre, bad, post] = splitAtPosition(value, first?.position);
  return (
    <div className="space-y-2">
      <textarea
        aria-label={t(type === "motive" ? "editor.formula" : "editor.condition")}
        data-testid="formula-input" rows={3} spellCheck={false} disabled={disabled} value={value}
        onChange={(e) => onChange(e.target.value)} className={`${areaCls} font-mono`} placeholder="=IF(trips_today+1>=milestone_trips, milestone_bonus_vnd - trip_cost_vnd, 0)"
      />
      {check && (
        <div data-testid="formula-check" className="space-y-1.5">
          {check.ok ? (
            <Notice kind="ok">
              {t("editor.formulaOk")}
              {check.sample !== null && <> · {t("editor.sample")}: <span className="font-mono font-bold">{String(check.sample)}</span></>}
              {check.warnings.length > 0 && <> · {check.warnings.map((w) => w.message).join("; ")}</>}
            </Notice>
          ) : (
            <Notice kind="error" issues={check.errors}>
              {first && first.position !== undefined && bad && (
                <div className="mb-1 font-mono text-[12px]">{pre}<mark className="rounded bg-gs-red/20 px-0.5 text-gs-red">{bad}</mark>{post}</div>
              )}
              {t("editor.formulaInvalid")}
            </Notice>
          )}
          {check.used_params.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-[11px] text-gs-mute-2">
              {t("editor.usedParams")}:
              {check.used_params.map((p) => <span key={p} className="rounded bg-surface px-1.5 py-0.5 font-mono">{p}</span>)}
            </div>
          )}
        </div>
      )}
      {!disabled && (
        <div>
          <div className="mb-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("editor.catalogue")}</div>
          <div className="flex flex-wrap gap-1">
            {catalogue.map((p) => (
              <button key={p.code} type="button" title={`${p.description} · ${p.unit} · ${p.source} · ${p.owner} · ${p.latency}`}
                onClick={() => onChange(`${value.replace(/\s+$/, "")}${/[=(+\-*/,<>\s]$/.test(value) ? "" : " "}${p.code}`)}
                className="cursor-pointer rounded-md border border-gs-line-2 bg-white px-1.5 py-0.5 font-mono text-[11px] text-gs-ink-2 hover:border-primary hover:bg-gs-cyan-soft">
                {p.code}<span className="ml-1 text-gs-mute">{p.unit}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BodyFields({ type, body, setBody, disabled, catalogue }: {
  type: KbType; body: Record<string, unknown>; setBody: (b: Record<string, unknown>) => void; disabled: boolean; catalogue: CatalogueParam[];
}) {
  const t = useTranslations("knowledge");
  const set = (k: string, v: unknown) => setBody({ ...body, [k]: v });
  const str = (k: string) => String(body[k] ?? "");
  const [published, setPublished] = useState<Record<string, string[]>>({});
  useEffect(() => {
    if (type !== "scenario") return;
    (["motive", "behavior", "workflow"] as const).forEach((tp) =>
      knowledgeApi.listObjects({ type: tp, status: "published" }).then((r) =>
        setPublished((p) => ({ ...p, [tp]: r.items.map((o) => o.code) }))).catch(() => undefined));
  }, [type]);
  const text = (k: string, label: string, props: { multiline?: boolean } = {}) => (
    <Field label={label}>
      {props.multiline
        ? <textarea rows={2} disabled={disabled} className={areaCls} value={str(k)} onChange={(e) => set(k, e.target.value)} />
        : <input disabled={disabled} className={inputCls} value={str(k)} onChange={(e) => set(k, e.target.value)} />}
    </Field>
  );
  const ff = formulaField(type);
  if (type === "motive") return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">{text("beneficiary", t("editor.beneficiary"))}{text("policy", t("editor.policy"))}</div>
      <Field label={t("editor.formula")} hint={t("editor.formulaHint")}>
        <FormulaEditor type={type} value={str(ff!)} onChange={(v) => set(ff!, v)} catalogue={catalogue} disabled={disabled} />
      </Field>
      {text("threshold_label", t("editor.thresholdLabel"))}
    </div>
  );
  if (type === "behavior") return (
    <div className="space-y-3">
      {text("description", t("editor.description"), { multiline: true })}
      <Field label={t("editor.signals")} hint={t("editor.signalsHint")}>
        <input disabled={disabled} className={`${inputCls} font-mono`} value={((body.signals as string[]) ?? []).join(", ")}
          onChange={(e) => set("signals", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
      </Field>
      <Field label={t("editor.condition")} hint={t("editor.conditionHint")}>
        <FormulaEditor type={type} value={str(ff!)} onChange={(v) => set(ff!, v)} catalogue={catalogue} disabled={disabled} />
      </Field>
      {text("source_rule", t("editor.sourceRule"))}
    </div>
  );
  if (type === "scenario") return (
    <div className="space-y-3">
      {(["motive_code", "behavior_code", "workflow_code"] as const).map((k) => {
        const tp = k.replace("_code", "");
        return (
          <Field key={k} label={t(`editor.${k}`)}>
            <input disabled={disabled} list={`dl-${k}`} className={`${inputCls} font-mono`} value={str(k)} onChange={(e) => set(k, e.target.value)} />
            <datalist id={`dl-${k}`}>{(published[tp] ?? []).map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
        );
      })}
      {text("reason", t("editor.reason"))}
    </div>
  );
  if (type === "workflow") {
    const steps = (body.steps as { question: string; tool?: string; branch?: string }[]) ?? [];
    const setStep = (i: number, patch: Record<string, string>) => set("steps", steps.map((s, n) => (n === i ? { ...s, ...patch } : s)));
    return (
      <div className="space-y-3">
        <Field label={t("editor.askFirst")} hint={t("editor.askFirstHint")}>
          <textarea rows={3} disabled={disabled} className={areaCls} value={((body.ask_first as string[]) ?? []).join("\n")}
            onChange={(e) => set("ask_first", toLines(e.target.value))} />
        </Field>
        <div className="space-y-2">
          <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("editor.steps")}</div>
          {steps.map((s, i) => (
            <div key={i} className="grid grid-cols-[1fr_150px_auto] items-start gap-2 rounded-lg border border-gs-line bg-surface p-2">
              <div className="space-y-1.5">
                <input disabled={disabled} aria-label={t("editor.stepQuestion")} placeholder={t("editor.stepQuestion")} className={inputCls} value={s.question} onChange={(e) => setStep(i, { question: e.target.value })} />
                <input disabled={disabled} aria-label={t("editor.stepBranch")} placeholder={t("editor.stepBranch")} className={inputCls} value={s.branch ?? ""} onChange={(e) => setStep(i, { branch: e.target.value })} />
              </div>
              <select disabled={disabled} aria-label={t("editor.stepTool")} className={inputCls} value={s.tool ?? ""} onChange={(e) => setStep(i, { tool: e.target.value })}>
                <option value="">{t("editor.noTool")}</option>
                {TOOLS.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              {!disabled && <button type="button" className={btn.ghost} aria-label={t("editor.removeStep")} onClick={() => set("steps", steps.filter((_, n) => n !== i))}><span className="material-symbols-outlined text-[16px]">close</span></button>}
            </div>
          ))}
          {!disabled && <button type="button" className={btn.secondary} onClick={() => set("steps", [...steps, { question: "", tool: "", branch: "" }])}>
            <span className="material-symbols-outlined text-[16px]">add</span>{t("editor.addStep")}</button>}
        </div>
        <div className="grid grid-cols-2 gap-3">{text("stop_condition", t("editor.stopCondition"))}{text("help_condition", t("editor.helpCondition"))}</div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3">
      {text("name", t("editor.name"))}{text("unit", t("editor.unit"))}{text("source", t("editor.source"))}{text("owner", t("editor.owner"))}
      {text("latency", t("editor.latency"))}{text("description", t("editor.description"))}
    </div>
  );
}

export function ObjectEditor({ obj, createType, me, catalogue, onChanged, onSelectVersion, onClose }: Props) {
  const t = useTranslations("knowledge");
  const locale = useIntlLocale();
  const creating = obj === null;
  const [type, setType] = useState<KbType>(obj?.type ?? createType);
  const [code, setCode] = useState(obj?.code ?? "");
  const [name, setName] = useState(obj?.name ?? "");
  const [scope, setScope] = useState<Record<string, string>>(obj?.scope ?? {});
  const [body, setBody] = useState<Record<string, unknown>>(obj?.body ?? defaultBody(createType));
  const [reasonText, setReasonText] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [confirm, setConfirm] = useState<"retire" | "rollback" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; issues: FormulaIssue[] } | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [versions, setVersions] = useState<KbObject[]>([]);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!obj) return;
    knowledgeApi.versions(obj.type, obj.code).then((r) => setVersions(r.items)).catch(() => setVersions([]));
  }, [obj]);

  const hasOpenSibling = versions.some((v) => ["draft", "ready_for_test", "trial"].includes(v.status));
  const act = obj ? objectActions(obj, me, hasOpenSibling) : null;
  const editable = creating || !!act?.edit;
  const patch = <T,>(setter: (v: T) => void) => (v: T) => { setter(v); setDirty(true); };

  const run = async (fn: () => Promise<KbObject>, msg: string) => {
    setBusy(true); setError(null); setOkMsg(null);
    try {
      const o = await fn();
      setDirty(false); setPreview(null); setConfirm(null); setReasonText(""); setOkMsg(msg);
      onChanged(o);
    } catch (e) { setError(parseApiError(e)); } finally { setBusy(false); }
  };
  const save = () => (creating
    ? knowledgeApi.create({ type, code: code.trim(), name: name.trim(), scope, body })
    : knowledgeApi.update(obj!.id, { name, scope, body }));

  const submit = () => run(async () => {
    const saved = dirty || creating ? await save() : obj!;
    return knowledgeApi.submit(saved.id);
  }, t("editor.submitted"));

  const runPreview = async () => {
    if (!obj) return;
    setBusy(true); setError(null);
    try { setPreview((await knowledgeApi.preview(obj.id)).results); } catch (e) { setError(parseApiError(e)); } finally { setBusy(false); }
  };

  const replay = obj?.replay;
  const needReason = confirm !== null && reasonText.trim().length < 3;
  const typeLabel = (tp: KbType) => t(`types.${tp}`);
  const ownerTitle = useMemo(() => (obj ? `${obj.code} · v${obj.version}` : t("editor.newTitle")), [obj, t]);

  return (
    <Card className="flex h-full min-h-0 flex-col" >
      <div className="flex items-center justify-between gap-3 border-b border-gs-line px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-mono text-[14px] font-extrabold text-on-surface" data-testid="editor-title">{ownerTitle}</h3>
            {obj && <Chip tone={STATUS_TONE[obj.status]}>{t(`status.${obj.status}`)}</Chip>}
            <Chip tone="purple">{typeLabel(type)}</Chip>
          </div>
          {obj && (
            <div className="mt-0.5 text-[11.5px] text-gs-mute-2">
              {t("editor.author")}: {obj.author_name ?? "—"}
              {obj.approver_name && <> · {t("editor.approver")}: {obj.approver_name}</>}
              {obj.published_at && <> · {fmtDate(obj.published_at, locale)}</>}
            </div>
          )}
        </div>
        <button type="button" className={btn.ghost} aria-label={t("editor.close")} onClick={onClose}><span className="material-symbols-outlined text-[18px]">close</span></button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {error && <Notice kind="error" issues={error.issues}>{error.message}</Notice>}
        {okMsg && <Notice kind="ok">{okMsg}</Notice>}
        {obj && !editable && <Notice kind="info">{t(obj.status === "retired" ? "editor.readOnlyRetired" : "editor.readOnly")}</Notice>}

        <div className="grid grid-cols-2 gap-3">
          {creating && (
            <>
              <Field label={t("editor.type")}>
                <select className={inputCls} value={type} onChange={(e) => { const v = e.target.value as KbType; setType(v); setBody(defaultBody(v)); }} aria-label={t("editor.type")}>
                  {KB_TYPES.map((x) => <option key={x} value={x}>{typeLabel(x)}</option>)}
                </select>
              </Field>
              <Field label={t("editor.code")}>
                <input className={`${inputCls} font-mono`} aria-label={t("editor.code")} value={code} placeholder="MOT_..." onChange={(e) => setCode(e.target.value)} />
              </Field>
            </>
          )}
          <div className="col-span-2"><Field label={t("editor.name")}>
            <input disabled={!editable} className={inputCls} aria-label={t("editor.name")} value={name} onChange={(e) => patch(setName)(e.target.value)} />
          </Field></div>
        </div>

        <div>
          <div className="mb-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-gs-mute">{t("editor.scope")}</div>
          <div className="grid grid-cols-3 gap-2">
            {SCOPE_KEYS.map((k) => (
              <input key={k} disabled={!editable} aria-label={t(`scope.${k}`)} placeholder={t(`scope.${k}`)} className={inputCls} value={scope[k] ?? ""}
                onChange={(e) => patch(setScope)({ ...scope, [k]: e.target.value })} />
            ))}
          </div>
        </div>

        <BodyFields type={type} body={body} setBody={patch(setBody)} disabled={!editable} catalogue={catalogue} />

        {replay && (
          <div className="space-y-2" data-testid="replay-report">
            <SectionTitle icon="science" title={t("replay.title")} hint={t("replay.hint")} />
            <div className="grid grid-cols-5 gap-2 text-center">
              {([["cases_total", replay.cases_total], ["matched", replay.matched], ["changed_scenario", replay.changed_scenario],
                ["not_computable", replay.not_computable], ["est_turns", replay.est_turns]] as const).map(([k, v]) => (
                <div key={k} className="rounded-lg border border-gs-line bg-surface px-2 py-2">
                  <div className="text-[18px] font-extrabold text-on-surface">{v}</div>
                  <div className="text-[10.5px] text-gs-mute-2">{t(`replay.${k}`)}</div>
                </div>
              ))}
            </div>
            <Chip tone={replay.gate_passed ? "green" : "amber"}>{t(replay.gate_passed ? "replay.gatePassed" : "replay.gateFailed", { pct: Math.round(replay.gate_min * 100) })}</Chip>
            {obj?.override_reason && <div className="text-[12px] text-gs-mute-2">{t("replay.override")}: {obj.override_reason}</div>}
          </div>
        )}

        {obj && formulaField(obj.type) && (
          <div className="space-y-2">
            <SectionTitle icon="fact_check" title={t("preview.title")} hint={t("preview.hint")}
              right={<button type="button" className={btn.secondary} disabled={busy || dirty} onClick={runPreview}>{t("preview.run")}</button>} />
            {preview && (
              <div className="overflow-x-auto rounded-lg border border-gs-line" data-testid="preview-table">
                <table className="w-full text-left text-[12px]">
                  <thead className="bg-surface text-gs-mute-2"><tr>
                    <th className="px-2 py-1.5 font-semibold">{t("preview.case")}</th><th className="px-2 py-1.5 font-semibold">{t("preview.value")}</th>
                    <th className="px-2 py-1.5 font-semibold">{t("preview.params")}</th></tr></thead>
                  <tbody>
                    {preview.map((r) => (
                      <tr key={r.case_id} className="border-t border-gs-line align-top">
                        <td className="px-2 py-1.5 font-mono">{r.case_id.slice(0, 8)}</td>
                        <td className="px-2 py-1.5">
                          {r.error ? <Chip tone="amber">{t("preview.notComputable")}: {r.error.message}</Chip>
                            : <><span className="font-mono font-bold">{String(r.value)}</span> <Chip tone={r.matched ? "red" : "grey"}>{t(r.matched ? "preview.matched" : "preview.notMatched")}</Chip></>}
                        </td>
                        <td className="px-2 py-1.5 font-mono text-[11px] text-gs-mute-2">
                          {Object.entries(r.params_used).map(([k, v]) => `${k}=${v}${r.assumed.includes(k) ? "*" : ""}`).join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="border-t border-gs-line px-2 py-1 text-[11px] text-gs-mute">* {t("preview.assumedNote")}</div>
              </div>
            )}
          </div>
        )}

        {obj && versions.length > 0 && (
          <div className="space-y-2">
            <SectionTitle icon="history" title={t("versions.title")} />
            <ul className="divide-y divide-gs-line rounded-lg border border-gs-line" data-testid="version-list">
              {versions.map((v) => (
                <li key={v.id}>
                  <button type="button" onClick={() => onSelectVersion(v)}
                    className={`flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[12px] hover:bg-surface ${v.id === obj.id ? "bg-gs-cyan-soft" : ""}`}>
                    <span className="font-mono font-bold">v{v.version}</span><Chip tone={STATUS_TONE[v.status]}>{t(`status.${v.status}`)}</Chip>
                    <span className="min-w-0 flex-1 truncate text-gs-mute-2">{v.author_name ?? "—"}{v.approver_name ? ` → ${v.approver_name}` : ""}</span>
                    <span className="text-gs-mute">{fmtDate(v.updated_at, locale)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {obj && obj.history.length > 0 && (
          <div className="space-y-2">
            <SectionTitle icon="receipt_long" title={t("history.title")} />
            <ol className="space-y-1 text-[12px]" data-testid="object-history">
              {[...obj.history].reverse().map((h, i) => (
                <li key={i} className="flex gap-2"><span className="w-32 shrink-0 text-gs-mute">{fmtDate(h.at, locale)}</span>
                  <span className="font-semibold text-gs-ink-2">{h.action}</span><span className="text-gs-mute-2">{h.by_name ?? ""} {h.note}</span></li>
              ))}
            </ol>
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-gs-line bg-surface px-4 py-3">
        {confirm && (
          <div className="flex items-center gap-2">
            <input autoFocus className={inputCls} aria-label={t("editor.reasonLabel")} placeholder={t("editor.reasonPlaceholder")} value={reasonText} onChange={(e) => setReasonText(e.target.value)} />
            <button type="button" className={btn.primary} disabled={busy || needReason}
              onClick={() => run(() => (confirm === "retire" ? knowledgeApi.retire(obj!.id, reasonText) : knowledgeApi.rollback(obj!.id, reasonText)),
                t(confirm === "retire" ? "editor.retired" : "editor.rolledBack"))}>{t("editor.confirm")}</button>
            <button type="button" className={btn.secondary} onClick={() => setConfirm(null)}>{t("editor.cancel")}</button>
          </div>
        )}
        {act?.needsOverride && act.publish && (
          <input className={inputCls} aria-label={t("editor.overrideLabel")} placeholder={t("editor.overridePlaceholder")} value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} />
        )}
        {act?.publishBlocked && (
          <Notice kind="info">{t(act.publishBlocked === "author" ? "editor.fourEyesAuthor" : "editor.fourEyesRole")}</Notice>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {creating && <button type="button" className={btn.primary} disabled={busy || !code.trim()} onClick={() => run(save, t("editor.saved"))}>{t("editor.save")}</button>}
          {creating && <button type="button" className={btn.secondary} disabled={busy || !code.trim()} onClick={submit}>{t("editor.submit")}</button>}
          {act?.edit && <button type="button" className={btn.primary} disabled={busy || !dirty} onClick={() => run(save, t("editor.saved"))}>{t("editor.save")}</button>}
          {act?.submit && <button type="button" className={btn.secondary} disabled={busy} onClick={submit}>{t("editor.submit")}</button>}
          {act?.trial && <button type="button" className={btn.primary} disabled={busy} onClick={() => run(() => knowledgeApi.trial(obj!.id), t("editor.trialStarted"))}>{t("editor.startTrial")}</button>}
          {act?.publish && (
            <button type="button" className={btn.primary} disabled={busy || (act.needsOverride && overrideReason.trim().length < 10)}
              onClick={() => run(() => knowledgeApi.publish(obj!.id, overrideReason), t("editor.published"))}>{t("editor.publish")}</button>
          )}
          {act?.rollback && <button type="button" className={btn.secondary} disabled={busy} onClick={() => setConfirm("rollback")}>{t("editor.rollback")}</button>}
          {act?.clone && obj && <button type="button" className={btn.secondary} disabled={busy} onClick={() => run(() => knowledgeApi.clone(obj.id), t("editor.cloned"))}>{t("editor.clone")}</button>}
          {act?.retire && <button type="button" className={btn.secondary} disabled={busy} onClick={() => setConfirm("retire")}>{t("editor.retire")}</button>}
        </div>
      </div>
    </Card>
  );
}
