# Text and Markdown validator

`scripts/controlled_doc_validator.py` is a Python-standard-library validator for strict UTF-8 `.txt`, `.md`, and `.markdown` files up to 8 MiB.

It proves only that:

1. the supplied manifest describes every source-to-candidate byte change;
2. the source and candidate reconstruct one another byte-for-byte through that manifest; and
3. configured lexical and structural invariants did not change.

It does not prove semantic equivalence, factual correctness, or that a declared edit is genuinely redundant.

Every report therefore marks semantic review and unresolved-flag assessment as outside the validator and keeps human approval required. Record the actual semantic-review, flag, and approval status in the companion change log or final QA summary; do not attribute those judgments to the script.

The validator requires a named reviewer on an `author-approved` annotation, but it cannot authenticate that identity or the approval event.

## Commands

```text
python3 scripts/controlled_doc_validator.py make-manifest SOURCE CANDIDATE \
  --manifest-out EDITS.json [--diff-out CHANGES.diff] [--force]

python3 scripts/controlled_doc_validator.py validate SOURCE CANDIDATE \
  --manifest EDITS.json --report-out QA.json \
  [--profile controlled] [--protect PROTECTIONS.json] \
  [--require-annotations | --allow-unannotated-draft] \
  [--warnings-as-errors] [--include-snippets]

python3 scripts/controlled_doc_validator.py apply SOURCE \
  --manifest EDITS.json --output REBUILT-CANDIDATE.md [--force]

python3 scripts/controlled_doc_validator.py reverse CANDIDATE \
  --manifest EDITS.json --output REBUILT-SOURCE.md [--force]
```

Do not use `--force` in the skill workflow. It exists for deliberate standalone recovery operations; even then, an output can never alias a supplied input. New manifests, diffs, reports, and rebuilt documents are written with owner-only permissions on POSIX systems.

The `controlled` profile is mandatory. Resolved annotations are required by default; `--allow-unannotated-draft` is only for intermediate development and reports `PASS_WITH_WARNINGS` when no other policy check fails.

## Built-in controlled checks

- signed and unsigned numbers, amounts, units, dates, and times;
- currency-and-amount pairs;
- modal verbs and negations;
- conditions and qualifiers;
- all-capital identifiers and quoted defined terms;
- clause and schedule references;
- citations, footnotes, links, and URLs;
- quotations;
- YAML front matter, fenced and inline code, math, formula-like lines, and Markdown tables;
- exact heading text and sequence;
- list marker and indentation topology;
- complete, resolved edit annotations;
- non-expansion in whole-document whitespace-delimited words.

Protected checks compare exact occurrence text, count, and order and reject any edit that overlaps a protected span. They are deliberately conservative.

## Privacy

By default, findings contain hashes, counts, and locations rather than document text. `--include-snippets` adds short previews and should be used only when the report may safely carry source content. The manifest always contains all changed text in base64 and is as sensitive as the source.

## Exit codes

- `0`: command succeeded; for `validate`, mechanical policy passed.
- `1`: validation policy failed.
- `2`: command-line usage error.
- `3`: input, unsupported-format, configuration, or output-collision error.
- `4`: manifest integrity or reconstruction error.
- `5`: unexpected internal error.

An identical candidate with zero edits is a valid result.
