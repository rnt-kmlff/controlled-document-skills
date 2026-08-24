# Risk and fidelity rules

## Risk lanes

### Low-risk working prose

Examples include internal explanatory prose, management communications, and already-grounded working drafts that do not create legal, financial, regulatory, safety, or evidentiary consequences.

Allow automatic removal only when the shorter wording is exact and the span is outside quotations, citations, tables, code, defined terms, and protected zones. Examples may include:

- `in order to` to `to`
- `due to the fact that` to `because`
- `at this point in time` to `now`
- a ceremonial transition that contains no document-specific claim

If context changes force, time, emphasis, scope, or tone, use `FLAG`.

### Controlled high-stakes narrative

This includes Board or investment papers, diligence narratives, transaction notes, forecasts, legal or tax summaries, regulatory or safety discussions, and technical conclusions.

- Allow only narrow lexical edits that cannot alter meaning.
- Make hedges, repetition, consolidation, reordered text, claim merging, and structural edits `FLAG` only.
- Require separate semantic review and human approval.
- Do not treat repetition between summary and detail as redundant.

### Blocked material

Do not run automatic tightening on:

- original data-room or source evidence;
- executed, signed, or operative agreements, amendments, opinions, notices, or submissions;
- defined-term schedules, signature blocks, initials, stamps, or seals;
- bank statements, payment records, invoices, or other financial evidence;
- spreadsheets, formulas, models, validations, or control tables;
- unverified OCR, low-confidence scans, handwriting, or image-only text;
- a file whose native structure or access permissions cannot be verified.

Offer a separate narrative working copy, a redline, or visible suggestions instead.
If the user supplied only blocked source material, do not create or validate a candidate. Report `REVIEW ONLY — no automatic content changes applied.`

## Protected content

Preserve exact text, occurrence, order, scope, and relationship for:

- facts, claims, reasons, decisions, and conclusions;
- numbers, signs, ranges, currencies, percentages, units, bases, and periods;
- dates, times, versions, deadlines, and durations;
- names, parties, entities, jurisdictions, authorities, systems, and products;
- assumptions, qualifications, uncertainties, limitations, evidence gaps, and review status;
- modal and operative terms including `shall`, `must`, `may`, `will`, `should`, `can`, and `cannot`;
- negations, exceptions, and conditions including `not`, `no`, `unless`, `except`, `subject to`, `provided that`, and `only if`;
- qualifiers including `approximately`, `roughly`, `appears`, `seems`, `assuming`, `pending`, `unverified`, and `to be confirmed`;
- defined terms, quotations, citations, links, footnotes, cross-references, clause numbers, and source anchors;
- headings, numbering, ordering, tables, formulas, code, configuration, commands, comments, tracked changes, and metadata needed for review;
- signatures, initials, stamps, seals, execution blocks, owners, decision gates, red flags, and bottlenecks.

## Prohibited transformations

Never automatically:

- turn uncertainty into fact;
- change `may` to `will`, `should` to `must`, or remove a negation;
- merge claims with different evidence, citations, periods, owners, or scopes;
- remove repeated operative wording or defined-term language;
- replace a precise date, amount, unit, or reference with a generalization;
- rewrite a quotation;
- move a statement to a different section;
- infer that a filename, signature label, or document presence establishes approval or execution.

## Fidelity decision rule

`KEEP` is the default. Use `REMOVE` only when identical meaning is provable in context. Use `FLAG` whenever a reasonable reader could interpret the change differently.
