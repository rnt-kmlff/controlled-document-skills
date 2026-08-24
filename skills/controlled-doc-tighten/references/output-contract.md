# Output contract

## Required outputs

Return only outputs appropriate to the user's requested format. For a file-backed run, use unique names and never overwrite:

- `<slug>-tightened-<timestamp>.<ext>` — working copy
- `<slug>-edit-manifest-<timestamp>.json` — every deterministic changed span
- `<slug>-change-log-<timestamp>.md` — rationale and review state for every edit ID
- `<slug>-qa-<timestamp>.json` — deterministic checks and human-review status

Native documents may use suggestions, comments, or tracked changes instead of a separate tightened file, but still require an edit ledger and QA summary for high-stakes work.

## Machine edit manifest

Generate the manifest with `scripts/controlled_doc_validator.py` for UTF-8 text or Markdown. It must contain:

- source and revised labels, hashes, and byte counts;
- validator version, Python version, and deterministic diff algorithm;
- every changed span with a stable edit ID;
- exact original and replacement bytes encoded in base64;
- source and revised byte offsets, plus line and column anchors;
- a review annotation for every edit.

The manifest contains the complete changed text and is therefore as sensitive as the source. It is mechanical evidence, not semantic approval.

The generated `annotation` field is initially `null`. Before final validation, populate every edit with:

```json
{
  "category": "filler",
  "rationale": "Exact, context-neutral reason this edit is permitted.",
  "decision": "automatic",
  "reviewer": null
}
```

Allowed categories are `filler`, `empty-transition`, `verbose-phrasing`, `punctuation`, `formatting`, `exact-restatement`, and `other`. Allowed decisions are `automatic`, `author-approved`, and `unresolved`. Insertions, `exact-restatement`, and `other` require `author-approved`. Final validation rejects unresolved or incomplete annotations when `--require-annotations` is set.
An `author-approved` decision must name the reviewer; the validator records the declaration but cannot authenticate the person or approval.

## Human-readable change log

Cover every manifest edit ID. Record:

- location or anchor;
- category from the manifest's allowed category list;
- exact before and after text;
- why meaning is unchanged;
- risk lane;
- manifest decision and reviewer state.

Do not use representative examples in place of complete coverage.

## QA report

The machine-generated JSON report includes:

- immutable source identifier and hash when local;
- revised identifier and hash;
- whole-document bytes, code points, line counts, and whitespace-delimited word counts;
- forward and reverse reconstruction status;
- protected-item and structure check status;
- explicit gates stating that semantic review and unresolved flags are outside the validator and human approval remains required;
- a clear limitation statement.

Supplement it in the human-readable change log or final QA summary with:

- native-format readback and rendering status where applicable;
- unresolved visible flag IDs;
- semantic reviewer and human-approval status.

Do not rewrite the machine-generated report to imply that the validator performed semantic or human review.

Use this verdict language:

`Preservation checks passed; human approval required.`

Use it only after a candidate passes all required mechanical checks. Otherwise use:

- `REVIEW ONLY — no automatic content changes applied.` for blocked material or recommendation-only handling.
- `BLOCKED — verification failed; candidate withheld.` when candidate or native verification fails.

Never use `lossless`, `zero-risk`, or an equivalent guarantee. Never imply that preservation checks ran when no candidate was validated.

The JSON report must retain these limitations:

- It does not prove semantic equivalence or factual correctness.
- Lexical protection is incomplete; project-specific protections may be required.
- Native layout, formulas, OCR, and embedded objects are outside the text validator's scope.

## No-change result

If an eligible working copy is already tight, preserve it unchanged and report a zero-edit result. If the only input is blocked original, executed, signed, or evidentiary material, create no substitute artifact and report `REVIEW ONLY`. Do not create empty artifacts unless the user requested file-backed evidence.

## Confidentiality and filing

- Outputs inherit the source's confidentiality and access restrictions.
- Do not upload content externally unless the user authorized that destination.
- Never place outputs inside source-evidence directories.
- Do not commit per-run outputs to a repository.
- Do not add upstream branding to business deliverables. Keep licensing notices in the skill package.
