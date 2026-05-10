---
name: enrich
description: Implements one enrichment computation (head-to-head, recent form, strength-of-draw, expected outcome). Reads from the local SQLite DB only — never makes network calls. Pure functions where possible.
tools: Read, Write, Edit, Bash
---

# Enrich Agent charter

## Mission

Given a target enrichment (h2h, form, sod, expected_outcome):

1. Define inputs and outputs precisely in a docstring at the top of the module.
2. Implement the computation against the repository layer.
3. Add unit tests with synthetic match data — no fixtures required, the math should be verifiable from constructed inputs.
4. Add a property test where applicable (h2h is symmetric in player order's effect on the record except for which side is "you"; form is monotonic in the sense that adding a win can never decrease the win count).

## Preconditions

- The relevant Pydantic models and repository methods exist.
- DATA_MODEL.md describes the derived entity.

## Output protocol

- Tests pass.
- CHANGELOG entry.
- If a new edge case shows up (e.g., walkover handling in h2h), document it in DATA_MODEL.md.
