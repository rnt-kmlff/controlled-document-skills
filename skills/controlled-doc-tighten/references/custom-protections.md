# Custom protection file

Use a custom protection file when the built-in controlled profile is not enough for project-specific entities, defined terms, identifiers, or immutable regions.

```json
{
  "schema_version": 1,
  "literals": [
    {
      "id": "entity.northstar",
      "text": "Northstar Trading Ltd",
      "case_sensitive": true
    },
    {
      "id": "term.business_day",
      "text": "Business Day",
      "case_sensitive": true
    }
  ],
  "regexes": [
    {
      "id": "project.reference",
      "pattern": "\\bPRJ-\\d{4}-\\d{3}\\b",
      "flags": []
    }
  ],
  "regions": [
    {
      "id": "approval-block",
      "start_marker": "<!-- PROTECT:approval -->",
      "end_marker": "<!-- /PROTECT:approval -->"
    }
  ]
}
```

## Rules

- Literal and regex occurrence text, count, order, and edit non-overlap must remain exact.
- Regex flags may be only `IGNORECASE` or `MULTILINE`.
- Region markers must be balanced and non-nested. The full marked block is immutable.
- Do not place markers into a canonical source merely to make validation easier. Mark only an authorized working-copy baseline, or protect the exact text as a literal or regex.
- Treat the protection file as controlled configuration and review it before use.
- There is no waiver mode. If protected content legitimately changes, approve a new source baseline instead of certifying the change as tightening.
