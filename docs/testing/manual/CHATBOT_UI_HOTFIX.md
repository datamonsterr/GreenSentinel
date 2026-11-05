# Chatbot UI hotfix

## Scope

Verify the fraud analyst Copilot fills the right sidebar and the composer uses this order: attachment control, expanding textarea, icon-only transparent send control. Controls must be vertically centered. User messages retain the existing gray background with white text.

## Local fixture check

1. Start the webapp with the repository fixture API and open `/workplace` at desktop width (1280px or wider).
2. Select a case and confirm the Analyst Copilot panel fills the remaining right column. The composer spans the full panel width.
3. Inspect the composer DOM. Confirm the actual `textarea` is the expanding middle control; attachment is leftmost and send is rightmost.
4. Confirm attachment, textarea, and send icon are vertically centered on one composer row.
5. Confirm the send control has no background in normal or hover state and keeps its accessible label.
6. Upload an attachment and confirm its preview appears without changing the control order.
7. Enter multiline text and confirm the textarea grows within the composer without clipping or horizontal overflow.
8. Repeat at a 375px viewport. Confirm the composer remains full width, ordered, centered, and usable.
9. Send a message and confirm the user bubble retains its gray secondary background and has white text.
10. Record revision, viewport, environment, and screenshot or trace path in the PR evidence.

Automated fixture coverage: `tests/e2e/browser/analyst-composer-layout.spec.ts` checks the real `textarea` bounding box, composer child order, vertical centering, transparent send normal/hover styles, visible upload preview and removal control, multiline sizing, 375px layout, and computed user-bubble colors. Local fixture result: 6/6 passed at commit `1bbbe44` plus working-tree fix; screenshots are emitted under `test-results/analyst-composer-layout-*`.
