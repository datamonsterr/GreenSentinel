# Evaluation Corpus Error Analysis

- Corpus: `eval-v1`
- Run: `baseline-inventory-2026-10-02`
- Environment: `repository-artifact-review`
- Source revision: `16c1ad6bdc910badbe852418bc5de5b456759156`
- Status counts: `{"fail": 1, "not_run": 52}`

## Findings

| Case ID | Suite | Split | Status | Failure | Owner |
|---|---|---|---|---|---|
| `driver-a2a-traffic` | `driver_a2a` | `train` | `fail` | Legacy driver fixture expects AUTO_DISMISS and is_auto_dismissed=true; PRD FR-03 requires analyst-confirmed dismissal. | `policy` |

## Coverage gaps

`not_run` (52): `brief-cancel`, `brief-degraded`, `brief-stall`, `driver-a2a-clear-road`, `driver-a2a-deadline`, `driver-a2a-dropout`, `driver-a2a-passenger-wait`, `error-duplicate-send`, `error-stale-version`, `protocol-dic-01`, `protocol-dic-02`, `protocol-dic-03`, `protocol-dic-04`, `protocol-dic-05`, `protocol-dic-06`, `protocol-dic-07`, `protocol-dic-08`, `protocol-dic-09`, `protocol-dic-10`, `protocol-outage-01`, `protocol-outage-02`, `protocol-outage-03`, `protocol-outage-04`, `protocol-outage-05`, `protocol-outage-06`, `protocol-outage-07`, `protocol-outage-08`, `protocol-outage-09`, `protocol-outage-10`, `protocol-traffic-01`, `protocol-traffic-02`, `protocol-traffic-03`, `protocol-traffic-04`, `protocol-traffic-05`, `protocol-traffic-06`, `protocol-traffic-07`, `protocol-traffic-08`, `protocol-traffic-09`, `protocol-traffic-10`, `rag-policy-001`, `rag-policy-010`, `rag-policy-029`, `role-declined-approval`, `role-denied-driver`, `taxonomy-err-01`, `taxonomy-err-02`, `taxonomy-err-03`, `taxonomy-err-04`, `taxonomy-err-05`, `tool-err02-dic`, `tool-prompt-injection`, `tool-provider-outage`

## Actionable follow-ups

- **Remove stale AUTO_DISMISS evaluation labels** (`policy`): `driver-a2a-traffic`
