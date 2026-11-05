# Issue 60 — Interaction design handoff

**Review artifact:** [`preview.html`](./preview.html)  
**Visual previews:** [`desktop`](./screenshots/issue-60-desktop.png) · [`mobile`](./screenshots/issue-60-mobile.png)  
**Status:** local HTML fallback; visual approval pending.

## Stitch availability

Stitch MCP was unavailable in this agent session: no callable MCP tool exposing Stitch was present. The existing HTML preview is therefore the review source and is explicitly labelled as a local preview, not Stitch output. No production code was changed.

## Design intent

Keep structured questions inside the existing conversation surfaces. Analyst work stays in `Agents`; driver-facing questions stay in the existing `GSupport` conversation. The case owner’s approval of a minutes document is a separate action from answering a question and from sending a chat message.

The visual language reuses the existing cockpit direction: pale blue page ground, white conversation surfaces, emerald primary actions, navy text, thin green-gray borders, compact radius, and sentence-case Vietnamese copy. Content is left aligned; status is communicated with text plus restrained color.

## Reusable question contract

All four question types use the same labelled fieldset, status badge, helper text, validation region, answer action, decline action, and live status message:

| Type | Control | Rule | Example |
|---|---|---|---|
| `single_choice` | radio group | exactly one answer | Nguyên nhân chính là gì? |
| `multiple_choice` | checkbox group | one to three answers | Điều gì xảy ra trong khoảng dừng? |
| `yes_no` | radio group | exactly one answer | Ứng dụng có mất kết nối không? |
| `text` | labelled textarea | 1–500 characters | Mô tả điều đã xảy ra |

The user must select or type an answer, then press **Gửi câu trả lời**. The answer is shown with its recorded time and the form is locked after submission. **Từ chối trả lời** records a distinct state and must never be interpreted as a violation. A stale question is locked while its history remains visible; a new question carries the updated request.

The preview’s submit interaction persists the answer in the rendered conversation state and announces the result through `role="status"`. App implementation must persist the same answer, question version, actor, timestamp, and outcome in the case history before reporting success; a network acknowledgement must not be implied by local UI state.

## Separate approval and minutes flow

The analyst sees a Vietnamese minutes preview in `Agents`, including version, decision, recipient, sources, evidence sections, and an explicit evidence gap. The case owner reviews the exact version and then uses **Duyệt và gửi biên bản**. Answering a question does not approve the minutes. Sending is a separate service-backed state machine: saved, pending, sent, received, read, or failed. A failed send keeps the approved version and must not create a duplicate.

The driver conversation receives only the approved, permitted content in the existing chat. It does not expose analyst approval controls or internal evidence.

## Keyboard and Vietnamese accessibility

- Native `select`, radio, checkbox, textarea, `details`, and buttons preserve predictable Tab and arrow-key behavior.
- Every field has a visible Vietnamese label or `legend`; validation appears beside the question with `role="alert"`.
- Submission feedback uses a local `role="status"` region without stealing focus. Focus rings are visible with `:focus-visible`.
- Interactive targets are at least 44px high with 8px spacing. Mobile body inputs remain 16px to avoid browser zoom.
- Meaningful state uses words (`Chờ trả lời`, `Đã trả lời`, `Đã từ chối trả lời`, `Cần cập nhật`) alongside color. Decorative map SVG is hidden from assistive technology.
- Mobile uses one column below 760px, wraps long Vietnamese text, and keeps page zoom enabled. Reduced-motion support should be retained when the interaction is implemented in the product.

## Screenshot audit

Captured with `agent-browser` at 1440×1000 and 390×844. Desktop hierarchy is clear: the two conversation surfaces are comparable, while the analyst-only minutes and approval block remain in the analyst column. Mobile preserves the same order and makes the first question immediately operable without horizontal scrolling. The screenshots show the pending state; the dropdown controls can be used to review answered, declined, stale, and each question type locally.

## Boundary for app coding

Reuse the preview’s four question renderers and state vocabulary. Wire persistence and service acknowledgements at the application boundary, preserving the distinction between answer submission, case-owner approval, and minutes delivery. Do not infer evidence, delivery, receipt, or read state from a local preview update.
