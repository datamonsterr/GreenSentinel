# Driver-first domain glossary

| Term | Meaning |
|---|---|
| Driver assistance | The assigned Driver's evidence-grounded conversation before Analyst triage. |
| Confirmation question | A successfully delivered question requiring an explicit Driver choice about resolution or continued appeal. |
| Driver confirmed resolution | The Driver explicitly accepts resolution at a valid confirmation step. This is not exoneration, proof of innocence or a sanction. |
| Analyst dismissal | An authorized Analyst dismisses a case with written rationale under the existing adjudication rules. |
| Escalation | Durable handoff into authorized Analyst triage; a late Driver reply cannot reverse it. |
| Reopening | An authorized Analyst resumes a previously terminal case while retaining its prior evidence, dialogue and dispositions. |
| Classifier confidence | A versioned [0,1] score assessing suspected violation, uncalibrated by default; not measured guilt probability or accuracy. |
| Vehicle plate | Vehicle registration/plate (biển số xe); the intended meaning of license number in case search. |
| Context reset | Omit prior Analyst chatbot messages from one model request while retaining case context and stored conversation/audit. |

Canonical rules: [Driver-first requirements](DRIVER_FIRST_REQUIREMENTS.md). Approval and implementation acceptance: [#147](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/147).
