# Skills

Agent skills for ML system design and controlled document workflows. Compatible with Codex, Claude Code, and other [Agent Skills](https://skills.sh) consumers.

## controlled-doc-tighten

Creates a separate, auditable tightening of a working-copy document. The skill defaults to keeping text, protects material facts and qualifiers, records every changed span, and uses deterministic forward/reverse reconstruction and structural checks for UTF-8 text and Markdown. It does not claim that model-edited prose is lossless or semantically equivalent.

The skill is explicit-only. High-stakes narratives require human approval; operative or signed legal text, source evidence, payment or banking records, spreadsheets, and unverified OCR are blocked from automatic tightening. Native DOCX, Google Docs, and PDF work must use their native editing and QA workflows.

### Install in Codex

Ask Codex to install this repository path:

```text
https://github.com/rnt-kmlff/controlled-document-skills/tree/main/skills/controlled-doc-tighten
```

Restart Codex after installation so the skill is available in a new task.

### Use

Invoke `$controlled-doc-tighten` explicitly and provide an identified working copy. For file-backed UTF-8 text or Markdown, the skill returns a tightened copy, a complete edit manifest, a human-readable change log, a mechanical QA report, and any unresolved author decisions.

## ml-system-design-review

Reviews ML/AI system designs — a design doc, a repo, or both. Produces a verdict, a 10-dimension stage-aware gradecard (plus an optional modern-AI row for LLM/RAG/agent systems), severity-ranked findings, low-hanging fruit, questions for authors, and a shareable takeaway. Compares doc claims against repo evidence in both directions.

### Install

```bash
npx skills add ML-SystemDesign/MLSystemDesign
```

Or copy the skill directory manually:

```bash
cp -r skills/ml-system-design-review ~/.claude/skills/
```

### Use

Ask your agent to review, grade, or audit an ML system design: "review my ML design doc", "audit this repo for production ML readiness", "grade this RAG architecture". The skill activates on design-review requests and routes itself through `SKILL.md`; the depth lives in `references/` (workflow, rubrics, doc/repo audit, modern-AI addendum, red flags, praise patterns, output templates).

## ai-stage-gate

Runs a stage-gate review for an AI product and reaches an evidence-based gate decision. Locates the product on a six-stage process (Discovery → Delivery, plus an optional Fast Track), scores the current gate's required deliverables and transition criteria (Met / Partial / Not met / Unknown), and returns a traffic-light decision — 🟢 Go, 🟡 Conditional, or 🔴 Kill — with the top blocker, the conditions to advance, and the recommended next-stage investment. Applies dual value-and-technical validation with alignment, ethics, and data checks at every gate.

### Install

```bash
npx skills add ML-SystemDesign/MLSystemDesign
```

Or copy the skill directory manually:

```bash
cp -r skills/ai-stage-gate ~/.claude/skills/
```

### Use

Ask your agent to run or prepare a gate review, or to decide whether an AI initiative can advance: "run a stage-gate review", "are we ready for Gate 3?", "Go/Kill decision for this AI prototype", "triage this portfolio of AI ideas", "should this take the fast track?". The skill activates on gate-decision requests and routes itself through `SKILL.md`; the depth lives in `references/` (gate-review workflow, the six stages and their stage-critical criteria, deterministic gate-decision logic, AI-specific validation, a modern-AI/RAG/agent overlay, fast track, and output templates for standard gates, Fast Track gates, and portfolio triage).

## lossless-doc-compress

Losslessly compresses a design doc — a PRD, RFC, architecture note, or any prose/markdown document. Removes only provable redundancy (filler, hedging, LLM-slop, restated content) and never a fact, number, decision, or caveat; every judgment call is flagged for the author rather than cut. Returns three artifacts: the compressed document, a categorized removal log of everything that was cut, and a shareable scorecard (before/after word count, percent reduction, fidelity confirmation, flag count). Where `ml-system-design-review` grades substance and `ai-stage-gate` decides Go/Kill, this skill trims length without touching substance.

### Install

```bash
npx skills add ML-SystemDesign/MLSystemDesign
```

Or copy the skill directory manually:

```bash
cp -r skills/lossless-doc-compress ~/.claude/skills/
```

### Use

Ask your agent to compress, tighten, or de-slop a document: "compress this design doc without losing information", "tighten this RFC", "cut the slop from this PRD". The skill activates on compression requests and routes itself through `SKILL.md`; the depth lives in `references/` (fidelity rules, removal taxonomy, slop-and-hedging patterns, the compression workflow, and output templates for the compressed doc, removal log, and scorecard). It does not grade design quality (use `ml-system-design-review`) or make gate decisions (use `ai-stage-gate`).
