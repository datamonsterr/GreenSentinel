# Agent Tool Catalog — Analyst, Driver and Operations

## Status and authority

Business-facing proposal for implementation planning, dated 2026-10-01. Tool names below are proposed canonical names; **Reuse** means an existing callable or service provides part of the capability, not that the complete authorized tool contract has already been delivered. **New adapter** means existing business logic/data needs a safe agent boundary. **New workflow** means additional product behavior. This document does not replace the backlog or claim runtime acceptance.

Sources: [PRD](PRD.md), especially its taxonomy, FR-01–06 and human-control rules; [UC-L06-04](USE_CASES.md#uc-l06-04-adjudicate-initial-case-phase-1-mvp-golden-path); contextual driver collaboration in [UC-L06-08](USE_CASES.md#uc-l06-08-conduct-async-driver-disputation-via-driver-agent) and [UC-L06-09](USE_CASES.md#uc-l06-09-collaborate-with-driver-agent-in-analyst-cockpit); [canonical data model](../architecture/DATA_MODEL.md); and the [runtime design](../superpowers/plans/2026-10-01-issue-60-tool-runtime.md).

### Confirmed stakeholder requirements

The user confirmed the following during discovery:

1. Final Vietnamese case minutes require an already recorded analyst decision. Preliminary evidence requests are separate messages.
2. The Fraud Analyst in charge of the case approves tools such as sending minutes.
3. Approved minutes are delivered in the existing driver case conversation, with delivery status.
4. Case information must be well formatted and injected before the first agent invocation. Persistence in the database is allowed.
5. Both analyst and driver agents need a reusable interactive-question tool supporting choices, yes/no questions and typed text input across different cases.

The case owner's approval does not remove PRD role limits. Junior analysts cannot authorize suspension merely because they own the case. A case must never be automatically dismissed or sanctioned.

### Requirement coverage and remaining discovery

| Requirement layer | Established requirement | Remaining detail |
|---|---|---|
| Business | Reduce repeated investigation and provide a clear, accurate explanation of the human decision; existing Phase 1 MTTR target applies to review. | Measure notification/document-preparation benefit rather than inventing an additional numerical KPI. |
| Stakeholder | Analyst investigates and approves; assigned driver receives the decision; authorized operations staff track progress/failures. | Confirm any additional operational roles before adding permissions. |
| Functional | Initial case context; evidence tools; draft/preview/approval/send minutes; delivery state; separate evidence requests; reusable interactive questions in both agent domains. | Validate the proposed additional tools below against actual operator usage. |
| Non-functional | Source-backed facts, Vietnamese output, case ownership, privacy, human approval, append-only evidence/audit, idempotency and honest failure states. | Delivery SLA, retention and acknowledgement semantics require operations policy. |
| Transition | Reuse current services, versioned evidence snapshots and driver conversation; correct taxonomy drift; add wrappers and new document workflow. | Schema/capability rollout is engineering work after catalog scope is accepted. |

## Violation codes and what evidence can establish

| Code | PRD meaning | Tool contribution and limits | Current delivery boundary |
|---|---|---|---|
| `ERR-01` | Trip/order embezzlement: cancellation followed by off-platform cash service. | Correlate cancellation actor/time, trip progress, payment records and passenger statements. GPS alone cannot establish off-platform cash payment. | Monitored; dedicated cash/off-platform corroboration tool is missing. Tables alone do not prove a connected evidence feed. |
| `ERR-02` | Route deviation, stalling or moving away to induce passenger cancellation. | Compare actual progress with legal pickup route, inspect stops/cancellation, legitimate traffic/weather explanations, technical failures and driver statements. A stall or cancellation alone does not prove intent. | Primary Phase 1 focus. |
| `ERR-03` | Incentive/policy exploitation through fictitious bookings or promotion gaming. | Requires campaign rules, incentive/award transactions and booking patterns; cannot be inferred from route deviation. | Phase 3 batch investigation; dedicated sources/tool are missing. |
| `ERR-04` | Phantom/virtual collusive trips without physical transit. | Requires trip/payment/physical-travel corroboration and permitted driver/passenger relationship evidence. A GPS gap is not a phantom trip. | Phase 3 graph investigation; dedicated sources/tool are missing. |
| `ERR-05` | Fake GPS or technological manipulation. | Inspect reported mock location, source/device integrity signals and impossible motion while separating ordinary jitter/dropout. Missing signals remain unknown. | Core Phase 1 detection signal, subject to human adjudication. |

`no_violation`, `insufficient_evidence` and technical outage are important outcomes/conditions, not additional fraud codes. Any tool may support requesting evidence or dismissing a false alarm; only an authorized human decision finalizes the case.

### Confirmed taxonomy defect

The current driver service's title map calls `ERR-03` fake GPS, `ERR-04` GPS jitter/dropout and `ERR-05` severe route deviation; the analyst prompt labels route deviation `ERR-03`. These conflict with PRD taxonomy. See [driver_dispute_service.py](../../src/services/driver_dispute_service.py), [fraud_analyst_system_prompt.md](../../src/agents/prompts/fraud_analyst_system_prompt.md), and [route_analytics.py](../../src/services/route_analytics.py).

Before generating driver explanations or minutes, use one canonical code-to-title mapping derived from the accepted product taxonomy and test all five codes across analyst, driver, documents and stored evidence. Historical records retain their original code/source/version; do not silently relabel or rewrite signed decisions. Policy clauses must come from approved retrieved documents, not hard-coded article numbers in prompts.

## Proposed information and drafting tools

The server injects actor, organization, case and allowed capabilities; the model cannot choose its identity or grant itself permissions. Every read is authorized for the case and audience. **Both** means separate analyst and driver projections, not the same unrestricted payload.

| Canonical tool | Users | Usage and returned information | Decision support | Implementation basis |
|---|---|---|---|---|
| `get_case_context` | Both | Current case/trip/driver identifiers, factual brief, timeline, evidence availability, source/version references and permitted next steps. Also loaded automatically before first invocation. | All supported codes; prevents decisions about the wrong case or stale evidence. | New adapter over case detail and existing frozen dossiers. |
| `list_cases` | Analyst, authorized operations | Prioritized, role-filtered queue; current owner/lease, awaiting evidence, escalation and unresolved delivery state where available. | All; operational triage rather than a fraud conclusion. | Reuse `list_cases` and constrained case-query services. |
| `get_trip_lifecycle_evidence` | Both | Assignment state, event timestamps, arrival/start/cancellation events and cancellation actor, with actual source references. | `ERR-01`, `ERR-02`, `ERR-04`; supplies sequence, not proof of cash or collusion. | New adapter over trip/assignment events; missing event fields return unavailable. |
| `inspect_trip_telemetry` | Both | Observed GPS/speed points, stops, gaps, accuracy/jitter and reported mock-location flags. | Primarily `ERR-02`, `ERR-05`; technical-error assessment. | Reuse driver telemetry tool/shared case evidence. |
| `compare_trip_routes` | Both | Actual traveled segments versus legal pickup path, measured progress/away movement, route-leg references, `traffic_model` and `match_type` (`matched|unmatched|interpolated`). Route context is advisory and never asserts intent. | `ERR-02`; route context can assist other investigations without proving them. | Case-scoped Geoapify adapter over route analytics/routing (#230). |
| `geocode_address` | Both | Forward geocode of a case-relevant address; candidates carry confidence and distance. Output declares that a lookup is not proof of an actor's location. | Context for `ERR-02`, `ERR-05`; lookup only, never location evidence. | New case-scoped read-only adapter over Geoapify geocoding (#230). |
| `reverse_geocode_coordinates` | Both | Reverse geocode of WGS84 coordinates; candidates carry confidence and provider distance. Output declares that a lookup is not location proof. | Context for `ERR-02`, `ERR-05`; lookup only. | New case-scoped read-only adapter over Geoapify reverse geocoding (#230). |
| `match_trip_telemetry` | Both | Snap stored GPS to the road network; returns match counts and `match_distance` per original point. Stored originals are never overwritten. Unmatched/interpolated points remain explicit. | `ERR-03`, `ERR-04` context; reconstructed route is not an observed trajectory. | New case-scoped read-only adapter over Geoapify map matching (#230). |
| `check_system_error_guardrail` | Both | App/network/platform incident evidence, telemetry completeness and server-enforced action restrictions. | Distinguishes system failure from suspected `ERR-02`/`ERR-05`; prevents wrongful adverse action. | New adapter over [guardrail functions](../../src/services/guardrails.py) and case/incident evidence; no existing canonical tool contract is claimed. |
| `check_traffic_situation` | Both | Genuine traffic observations aligned to the case's location/time, freshness and uncertainty. | `ERR-02` legitimate-delay explanation. | Reuse/harden existing tool; OSRM geometry/duration alone is not traffic evidence. |
| `fetch_corridor_historical_traffic` | Both | Historical observed speed against a recorded free-flow baseline for a corridor/time window. | Legitimate route-deviation or delay explanation; advisory Điều 12.2 review. | Configured normalized gateway; unavailable without a selected provider. Live acceptance pending. |
| `query_traffic_incident_feed` | Both | External incidents filtered by a configured gateway to the requested corridor/time. | Corroborate driver explanation alongside telemetry and case policy. | Empty incidents do not prove absence of force majeure. See [verification boundary](../testing/manual/TRAFFIC_EVIDENCE.md). |
| `check_weather_condition` | Both | Actual provider weather observation/forecast with relevant location, time and source type. | `ERR-02` contextual explanation; weather alone does not prove the cause of this stop. | Reuse/harden; distinguish current conditions from historical trip conditions and forecast. |
| `get_driver_history` | Analyst; driver-own projection | Recorded relevant assignment history, prior adjudications and operating state, with references. | Context for `ERR-01`, `ERR-02`, `ERR-05`; past findings do not prove present guilt. | Reuse history/card/suspension services; stop fabricated default metrics. |
| `check_related_cases_to_vehicle` | Analyst | Authorized, genuinely linked case/vehicle events with separate case identities. | Contextual patterns for `ERR-01`, `ERR-02`, `ERR-05`; future `ERR-03`/`ERR-04` leads only. | Reuse/harden; no seeded fictional related case as production evidence. |
| `search_policy_documents` | Both | Applicable published policy passages, version, effective dates and citations; driver receives permitted explanations. | All categories with actual policy support; permitted outcomes/exceptions. | Reuse policy/RAG aliases; unavailable policy cannot become an invented rule. |
| `get_dispute_dossier` | Analyst; driver-own transcript | Driver's claims, supporting/contradicting evidence, transcript and unresolved questions, labeled by source. | Primarily `ERR-02`, `ERR-05`; other categories only where real evidence exists. | New tool adapter over existing driver dossier/session services. |
| `search_case_precedents` | Analyst | Relevant previously decided cases, historical rationale and policy versions. | Supported codes; consistency aid, not evidence of current guilt or authority to override policy. | New safe adapter over [precedent workflow service](../../src/services/jev_precedent_service.py); current source/data reliability still needs acceptance, and broader durable history remains #66. |
| `get_case_map_snapshot` | Analyst; approved driver projection | Deterministic, evidence-revision-bound map image/artifact plus data references: route refs, checkpoint times, gap windows, traveled path and planned routes. Re-render on a new revision creates a new artifact; sent minutes never mutate. Static Maps powered with GET/POST fallback and structured `unavailable` + retry guidance. | Primarily `ERR-02`, `ERR-05`; visual attachment and explanation. | Case-scoped Geoapify Static Maps adapter bound to frozen `evidence_snapshots.dossier` (#229). |
| `draft_evidence_request` | Analyst | A Vietnamese question/message targeting a specific timestamp or evidence gap, allowed submission options and a policy-backed deadline if one exists. | All supported categories; avoids premature decisions when evidence is insufficient. | New drafting workflow. Sending is separately confirmed. |
| `draft_case_minutes` | Analyst | Vietnamese minutes grounded in the recorded adjudication, frozen evidence, cited policy, official rationale and map reference. | Communicates an already recorded decision; never creates a verdict. | New workflow; replaces unsafe use of `write_ticket_for_driver` for this purpose. |
| `preview_case_minutes` | Assigned analyst | Exact rendered minutes/map/recipient/source snapshot and draft revision that would be sent, with missing-field validation. | Human verification of identity, facts, rationale and disclosure. | New deterministic preview workflow; no external send. |
| `request_action_approval` | Assigned analyst | Approval card showing action, case, recipient, exact payload/preview, consequences and authority required. Returns pending/denied/approved status via trusted UI state. | All important commands; human authorization rather than model consent. | New approval request capability; the model cannot approve it. |
| `ask_interactive_question` | Both | Reusable Vietnamese single-choice, multiple-choice, yes/no or text question with stable options, case/question identity and a durable answer state. | Clarifies driver claims, evidence gaps, analyst intent and next investigation steps for any supported category. Answers remain statements/choices, not automatic verdicts. | New shared question contract and safe adapters; reuse the current choice widget where suitable. |
| `get_action_status` | Both; authorized operations | Authorized approval/execution/delivery state, safe failure reason and next permitted recovery step. | All; prevents duplicate action and false claims that a notice was delivered. | New read adapter over durable action/outbox state. |

Keep aliases such as `get_case_information`, `get_driver_card`, `query_policy`, `query_driver_policy`, `get_telemetry` and `get_driver_dispute_context` only as documented audience/surface adapters to canonical operations. Their parameters and result shapes must be mapped explicitly.

## Commands available only after human authorization

These are application commands behind the approval UI, not unrestricted model-selected mutation tools. The agent may prepare their proposal and request approval; the authenticated server executes the exact approved command.

| Command | Authorized actor and usage | Result and protections |
|---|---|---|
| `send_approved_case_minutes` | The currently authorized case owner confirms sending the previewed final minutes to the assigned driver's existing case conversation. | Same approved revision, recorded decision, map and recipient; durable message/outbox, idempotent send and delivery state. No decision or sanction is created by sending. |
| `send_approved_evidence_request` | Case owner confirms the separate evidence-request message. | Record the approved request and actual delivery; use only a configured/approved policy deadline or an explicitly permitted no-deadline policy state, never an invented SLA. Missing policy is shown as a gap before send. |
| `submit_approved_adjudication` | Case owner confirms an authorized outcome and mandatory rationale; suspension requires permitted senior authority. | Existing human adjudication service records decision/evidence/audit transactionally. Technical guardrail, lease, role, case version and idempotency are rechecked. |
| `submit_approved_escalation` | Case owner confirms referral to the authorized senior queue with the current dossier and reason. | Audited nonterminal review action; case remains reviewable and retains evidence. |
| `submit_driver_statement` | Authenticated driver explicitly submits their own explanation/evidence in the existing conversation. | One recorded statement per command identity; statements remain untrusted reported information until corroborated. No automatic dismissal or sanction. |
| `answer_interactive_question` | The authenticated intended respondent submits a question answer through the UI. | Validate the typed answer against the stored question, actor/case/version, persist once and resume the correct conversation. The model cannot answer on behalf of the analyst or driver. |
| Claim/renew/release review lease | Authenticated analyst's explicit workspace action. | Reuse current queue/lease APIs; never let model text transfer another analyst's case or silently waive ownership. |

Approval is bound to authenticated approver, current case ownership/lease where required, action type, exact recipient, decision/evidence/policy versions and payload hash. Editing content, recipient, map, decision or material evidence requires a fresh preview and confirmation. A chat phrase such as "approved" is not a signed application approval. A rejected/expired approval has no external effect. Retrying an already authorized command recovers its outcome without duplicating writes or sends.

Adjudication/evidence requests use the active review lease where the use case requires it. Final minutes are sent after the recorded decision, when that review lease may already have been released; authorize this communication by durable case ownership/decision linkage and the analyst's current role rather than requiring an open investigation lease. Reassignment invalidates an old owner's outstanding approval.

Important actions include driver-visible sends, adverse adjudication, dismissal/closure, consequential escalation/reassignment and sensitive-data disclosure/export. Read-only lookup and local drafting do not require a new confirmation each time; they still require access authorization. Data-disclosure privileges remain separate from permission to send a document.

## Reusable interactive questions for both agents

`ask_interactive_question` creates a structured question for the current authorized human conversation. One shared contract supports two independent domain consumers: the analyst cockpit and the existing driver conversation. This shares transport/validation behavior without forcing a shared monolithic chat UI.

| Question kind | UI and answer shape | Example use |
|---|---|---|
| `single_choice` | Radio/selectable cards; submit one stable option ID. | Analyst chooses which evidence gap to investigate next; driver chooses the main reason for a recorded stop. |
| `multiple_choice` | Checkboxes; submit a set of distinct permitted option IDs with defined minimum/maximum selections. | Driver reports several contributing conditions; analyst selects permitted sources to inspect. |
| `yes_no` | Explicit yes/no buttons; submit a boolean. `false` is a valid answer, never treated as absent input. | Driver answers whether the app disconnected in the specified interval; analyst answers whether a stated fact is supported by the dossier. |
| `text` | Typed text box with defined length limits and a clear question. | Driver explains a particular time interval; analyst supplies an operational note or rationale draft. |

Example driver wording: `Nguyên nhân chính khiến anh/chị dừng xe là gì?` with `Ùn tắc giao thông`, `Yêu cầu của hành khách`, `Sự cố kỹ thuật`, `Khác` and `Không rõ`. A yes/no clarification can ask `Ứng dụng có bị mất kết nối trong khoảng thời gian được đánh dấu không?`. An analyst question can ask `Anh/chị muốn kiểm tra nhóm chứng cứ nào tiếp theo?`. These are example templates, not assertions that a particular cause or event occurred; the actual case/time references come from the authorized context.

When appropriate, allow `Khác` with a text explanation, `Không rõ`, `Không áp dụng`, or an explicit decline/defer route. Do not force an inaccurate yes/no answer or infer guilt from an unanswered, declined, late or ambiguous response. Explanations and choices are stored as human-reported information with timestamps until separately corroborated.

### Question and answer contracts

A question contains server-issued `question_id`, schema/question revision, case/session/turn identity, relevant evidence/context version, intended respondent scope, purpose, Vietnamese title/prompt/help, question kind, stable option IDs/labels where applicable, required/optional status and kind-specific validation. Actor and case scope come from trusted runtime injection; the model does not nominate another organization or arbitrary respondent identity.

Use `purpose="clarification"` for ordinary investigation questions and a distinct `purpose="action_confirmation"` for the approval renderer. An action-confirmation question requires a server-created approval request bound to the exact preview/action/recipient/version hash. The generic yes/no schema alone cannot authorize minutes delivery, adjudication or a sanction. The authenticated case owner approves via the dedicated signed action endpoint; drivers cannot approve analyst actions, and an agent cannot approve its own proposal.

An answer records question ID/revision, authenticated respondent, submitted value, optional explanation, actual submission timestamp, idempotency identity and a reference to the question's original context. Validate option membership, cardinality, duplicate selections, text length, correct boolean type and current permitted respondent before recording an answer. Preserve the verbatim text separately from any AI interpretation. Do not evaluate entered text as instructions to the system or run arbitrary expressions/URLs embedded in it.

### Durable lifecycle and branching

1. The agent identifies a specific uncertainty and emits a question through the case-bound stream.
2. The server persists the question and returns a waiting-for-user result. End the active generation cleanly; do not keep a tool executor/model request running until a human replies.
3. The relevant existing chat UI renders the permitted question control in its conversation and retains it after reload.
4. The intended human explicitly submits a validated answer; the server stores it idempotently and resumes the correct case conversation with a new bounded generation.
5. The agent uses the answer to select its next evidence query, refine a draft or propose a human action. It cannot turn the answer itself into autonomous enforcement.

Persist question states such as `pending`, `answered`, `declined`, `cancelled`, `expired` or `superseded`; an expiry exists only when an actual product/policy timeout is configured. Time elapsed is never assumed consent. Duplicate question requests/replayed stream events reuse the same stored question/answer identity rather than producing duplicate cards. A response from an old run or another case cannot change the current active question. Material source/question/ownership changes require revalidation or a new question; preserve old answers as historical records rather than silently reinterpreting their option IDs.

The negotiated event extension needs a typed interaction-request payload and an explicit waiting-for-user completion reason, plus authenticated answer/resume transport and recovery state. Reuse the correlated event envelope from #60; do not silently introduce arbitrary JSON into strict v1.0. Answers persist in case history/interaction records and belong in the next context refresh. Sensitive analyst questions/answers are excluded from the driver's projection.

The current [ChoiceSelectorWidget](../../src/webapp/components/ui/chat-widgets.tsx) and its [tests](../../src/webapp/tests/chat-widgets.test.tsx) are reusable presentation foundations. They are not proof that durable question IDs, multi-select, respondent authorization, yes/no/text validation or answer/resume lifecycle already exist.

An analyst's question to their own agent can render immediately in their authorized conversation. A delegated question sent outward to the driver follows the confirmed evidence-request approval/send path before becoming a driver interaction. The driver agent may ask follow-up questions within the driver's already authenticated active conversation; no new portal or unrelated-driver messaging capability is implied.

## Vietnamese case minutes

Final minutes are prepared **after** the official analyst decision has been persisted. The approval for the decision and approval for sending its notice are distinct. Evidence requests remain a separate document/message while investigation continues.

Required sections and source rules:

| Vietnamese section | Required content |
|---|---|
| `Biên bản kết quả xử lý vụ việc` | Document identifier, revision, issuance time and timezone; document status clearly distinguishes draft from approved/sent. |
| `Thông tin định danh` | Case ID, trip/assignment reference, assigned driver reference and permitted display name, vehicle reference/type, incident time window and location. Mask passenger/private details according to recipient access. |
| `Diễn biến vụ việc` | Concise factual Vietnamese summary and chronological events with timestamps; distinguish suspicion, observed facts and adjudicated findings. |
| `Lộ trình đã di chuyển` | Approved map generated from the decision's referenced evidence snapshot; recorded traveled path, start/pickup/destination where recorded, relevant times and visible missing intervals. Clearly distinguish planned route and display estimates from observed GPS. |
| `Nguồn thông tin và chứng cứ` | Evidence/source IDs or authorized links, telemetry/statement references, observation times, reliability/unavailable flags and relevant attachments. Only driver-permitted evidence is disclosed. |
| `Giải trình của tài xế` | Driver's actual statement and timestamp, or an explicit statement that no explanation is recorded. No invented admission. |
| `Căn cứ đối chiếu` | Retrieved approved policy/document name, version, effective date and actual clause citations. No hard-coded uncited articles or assumed amounts. |
| `Kết luận và lý do` | Recorded analyst decision, official rationale, decision ID/date and authorized sign-off. A false alarm/system-error decision is described explicitly; a draft cannot assert confirmed fraud. |
| `Hướng dẫn tiếp theo` | Only supported, policy-backed obligations/contact or response information. Do not invent payment/appeal deadlines or create a deferred appeal portal. |

The map is a deterministic GIS artifact, not an AI-generated illustration. Keep historical sent minutes and their exact evidence/map revision immutable. Corrections create a new linked revision with fresh approval. Driver acknowledgement/read state is receipt information, not an admission of wrongdoing.

Delivery states should reflect actual adapter evidence: `stored`, `queued`, `sent`, `delivered`, `read`, `failed` where supported. Database persistence establishes a stored message; the transport must establish queue/send acceptance separately. `delivered` and `read` remain proposed states until the adapter records the relevant driver acknowledgement/observation. Report only states the conversation transport can establish, and expose a safe failure/retry view to operations. Reuse [outbox_events](../../db/migrations/0001_poc_core.sql) and durable conversation history where possible.

## Initial case context: formatted, versioned and role-scoped

Context loading is a mandatory server/orchestration step before the first agent call, not a tool call the model may forget. `get_case_context` supports authorized refresh and follow-up inspection. The cockpit executor and driver LangGraph both need this step; changing only shared LangGraph state misses the actual cockpit runtime.

The database already stores frozen, versioned JSONB in `app.evidence_snapshots.dossier`, with `version`, `policy_version_id`, cutoff and hash. Reuse that source, [CaseService](../../src/services/case_service.py), current model assessment, case decision and session history to build a strict context projection. A new `agent_context` JSONB field can be a derived cache if measured performance needs it; a migration is not automatically required. Never mutate frozen evidence just to store a changing chat prompt.

The context must contain:

| Field group | Contents |
|---|---|
| Identity/version | Canonical case, trip, assignment and driver IDs; case/context schema/evidence/policy versions; snapshot ID/hash; event cutoff and preparation time. |
| Vietnamese factual brief | Two or three source-grounded sentences; operational incident and current status; uncertainty/gaps made explicit. |
| Timeline and spatial facts | Recorded trip lifecycle, GPS/speed/stop/gap summaries with units and timestamps; route-leg and source/map references. Large trajectories stay in tools/artifacts rather than bloating every prompt. |
| Evidence and claims | Source-linked observations, server-derived metrics, separately labeled driver/passenger statements, contradicting evidence and unavailable sources. |
| Advisory assessment | Current suggested category, evidence refs and score semantics; clearly advisory and distinct from the official decision. Missing assessment remains missing. |
| Policy and official decision | Applicable retrieved policy references; current recorded decision/rationale if one exists; no invented policy, deadlines or sanctions. |
| Conversation state | Case-linked persisted history, pending evidence/approval/delivery state and relevant latest updates. |

A readable Vietnamese rendering uses the order: `Thông tin vụ việc`, `Tóm tắt`, `Dòng thời gian`, `Dữ liệu hành trình`, `Chứng cứ đã có`, `Thông tin còn thiếu`, `Giải trình`, `Căn cứ chính sách`, `Quyết định đã ghi nhận`, `Việc cần thực hiện tiếp theo`. Missing evidence displays `Chưa có dữ liệu` or `Không khả dụng`, never fabricated numbers.

Access capabilities, current actor, active lease and guardrail authorization are fetched/verified by the server at each important action; cached context cannot grant authority. Produce a full permitted analyst projection and a narrower driver-own projection. Treat driver statements and retrieved text as data, not instructions to bypass rules. Do not inject synthetic scenario labels or expected benchmark verdicts as model evidence. Preserve labeled dataset provenance without leaking evaluation intent.

Refresh when case/evidence/policy/decision versions change; preserve durable history on reload. New evidence before adjudication invalidates stale proposals. Already issued decisions and sent minutes retain their original source snapshot; additional evidence follows an authorized review/correction path rather than rewriting history.

## Additional gaps to consider

1. Dedicated `ERR-01` cancellation/payment/off-platform corroboration is missing. Investigate whether actual payment and passenger-report feeds are populated and authorized before offering a conclusion.
2. `analyze_incentive_abuse` for `ERR-03` and `analyze_phantom_trip_links` for `ERR-04` need new evidence/model scope and remain deferred under the current PRD.
3. Evidence-gap listing, targeted driver questions, policy-version checking, source freshness and explicit uncertainty are necessary to support legitimate alternatives rather than merely confirm suspicion.
4. Stale preview/approval, concurrent case transfer, map unavailability, policy outage, duplicate send, document correction and driver acknowledgement require explicit behavior. Missing required case/decision/recipient fields block final send; missing telemetry/map/policy must be surfaced for operator handling rather than silently filled.
5. Safe operations views should identify awaiting-evidence cases, lease conflicts, pending approvals, escalations and failed sends using existing authorized queue data. New batch dispatch, new driver portals and automatic enforcement are outside this catalog's immediate runtime scope.

## Relationship to implementation planning

[Issue #60](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/60) supplies the shared catalog, trusted runtime, error/provenance, idempotency and correlated event foundations. The previous plan hardened existing tools; it did **not** include the new final-minutes delivery workflow. Do not claim that workflow is already covered or delivered by the old eight slices.

Context injection and taxonomy reconciliation are required design additions for consistent tool usage. Minutes/approval/notification behavior is a separately demonstrable product outcome using the shared runtime and existing human adjudication/conversation services. Final scope and ticket changes should follow review of this proposed catalog; this document does not silently create dependencies or alter current issue status.

Interactive questions are another explicit requested addition: a shared schema, durable question/answer state and separate analyst/driver consumers. Existing selection widgets alone do not deliver this behavior. Link these new outcomes to the runtime foundation when ticketing is updated; retain the current issue checklist until the revised feature scope is accepted.

### Assumptions and open questions

- **Assumption:** Minutes are an operational decision communication; no additional legally prescribed signature/document template has been provided.
- **Assumption:** An existing authenticated driver conversation can store the approved document/map references. Actual transport acknowledgement support must be verified.
- **Open:** Approved minutes template/required operational fields, retention policy, delivery SLA, correction protocol and any role-specific disclosure/export policy.
- **Open:** Whether `read`/driver acknowledgement is required, and whether a later printable/PDF artifact is desired. Conversation delivery is the confirmed initial channel.
- **Open:** Which extra evidence feeds for `ERR-01`, `ERR-03` and `ERR-04` actually exist. Deferred categories are not promoted by listing candidate tools.

No production code, database migration, message delivery or sanction execution was performed to produce this catalog.
