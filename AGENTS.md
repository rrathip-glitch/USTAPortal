# AGENTS.md — multi-agent coordination charter

This file defines how human contributors and Claude-driven subagents share state on this project. Every agent — human or otherwise — reads this file before doing meaningful work.

## Why this file exists

The project is bootstrapped and developed primarily by Claude Code subagents working under an Orchestrator. Subagents start cold each session: they have no memory of prior conversations and only see the files in the repo plus the prompt the Orchestrator gives them. The canonical state files (STATE, DECISIONS, QUESTIONS, TODO, RECON, RESEARCH, DATA_MODEL, API_CONTRACTS, RUNBOOK, TESTING, CHANGELOG, SPEC) are how knowledge persists across sessions. If those files are stale or contradictory, the next agent does the wrong work.

## Agent registry

Each named agent has a charter file in `.claude/agents/` that scopes its tools and mission. The Orchestrator (the lead Claude session, or the human running it) decides when each is invoked.

| Agent | Charter | Designated outputs | When invoked |
| --- | --- | --- | --- |
| Orchestrator | this session | STATE.md, CHANGELOG.md, ADR drafts, dispatch decisions | Always — top of stack |
| recon | `.claude/agents/recon.md` | RECON.md, API_CONTRACTS.md, ADR-001 | Phase 0; only with credentials and explicit user authorization |
| parser | `.claude/agents/parser.md` | one parser module + tests + fixture | After ADR-001, per entity |
| enrich | `.claude/agents/enrich.md` | one enrichment module + tests | Phase 2, per metric |
| ui | `.claude/agents/ui.md` | one route + template + test | Phase 3, per page |
| tennislink | (charter deferred) | TennisLink parsers, TennisLink sync wiring, Janav profile sync from legacy surface | Phase 1.5 wave; primary live data plane while Clubspark is blocked |
| rearchitect | (charter deferred) | SPEC.md and DECISIONS.md edits when scope changes warrant it | When a wave's evidence demands updates to canonical strategy docs |
| docs-clean | (charter deferred) | Alignment passes across README, RUNBOOK, TESTING, TODO, AGENTS, DATA_MODEL, QUESTIONS, CHANGELOG | After multi-agent waves leave drift between the code and the docs |

The bottom three rows are agents that have emerged in practice during the multi-wave development cycle but do not yet have formal charter files in `.claude/agents/`. Their scopes are constrained by the prompts the Orchestrator dispatches them with rather than a checked-in charter; the formal charter files are deferred until each role stabilizes. Agents not in this table — formal or de-facto — should not exist. If a workstream doesn't fit any row, the Orchestrator first proposes a new charter (a new file in `.claude/agents/`, or a new row here for an emerging role) before spawning.

## Coordination protocol

Every agent follows this protocol every time:

1. **Read first.** Before writing anything, read STATE.md, DECISIONS.md, QUESTIONS.md, TODO.md in that order. Read SPEC.md sections relevant to your charter. If your work touches an entity, read DATA_MODEL.md too.
2. **Claim work.** Append a one-line claim into STATE.md under "Active workstreams" with your agent name, charter scope, and start time. This prevents two agents from reaching for the same module.
3. **Do the work.** Stay inside your charter's scope. If the scope turns out to be wrong, stop and surface it via QUESTIONS.md rather than expanding silently.
4. **Update state on completion.** Edit STATE.md to reflect what's now true. Append a CHANGELOG.md entry (one to three lines, dated, signed with your agent name). Move resolved questions out of QUESTIONS.md into the doc where they now live (RECON.md, DECISIONS.md, etc.).
5. **Escalate when answers materially shape the product.** If your finding changes scope, architecture, or UX, write it as a new question or ADR-Proposed entry rather than acting on it. Examples: a third-party API tier requires payment; the WTN endpoint is rate-limited per minute; the user wants doubles results visible on the singles dashboard.

## Conflict avoidance

Two agents must not edit the same module concurrently. The Orchestrator decides ordering. If a conflict appears anyway (a parser agent wants to touch `src/models/` while a model-refactor agent is in flight), the second agent picks a different scope or pauses.

## Self-improvement loop

After every meaningful session, the Orchestrator runs `python scripts/update_canonical_docs.py`. The script does not silently rewrite docs — it produces a report covering: files modified since last STATE.md snapshot, open questions, [Proposed] ADRs, completed-but-still-listed TODOs. The Orchestrator reviews, then either applies mechanical fixes (`--apply`, which only refreshes the STATE snapshot timestamp) or hand-edits the canonical docs.

The deeper version of this loop runs at session boundary: when an Orchestrator-led session ends, it asks "does SPEC.md still describe reality? did we resolve a recon question? did we open a new one? are any DECISIONS.md ADRs now obsolete?" and updates accordingly. Over many sessions SPEC.md is expected to drift from its initial form — that drift is the point. The version at any given commit is the team's best current understanding.

## Escalation to the user

Use QUESTIONS.md for anything that:
- changes the scope of v1 (adding/removing a goal),
- chooses between architectural options that aren't symmetric (e.g., GraphQL vs HTML scraping vs hybrid — these have different ToS implications and different failure modes),
- requires a credential, payment, or third-party signup,
- creates a UX decision the user has a strong preference on (e.g., dashboard layout, which scouting fields matter most).

Do NOT use QUESTIONS.md for:
- preferences inside an already-approved scope (pick one and document it),
- minor naming or style decisions (pick one and move on),
- questions whose answer doesn't change what code you write.

## Subagent invocation pattern

When the Orchestrator spawns a subagent via the Task tool, the prompt must be self-contained — the subagent does NOT see the conversation. Include:

- The subagent name (matches a charter file).
- The narrow scope (one entity, one decision, one page).
- Pointers to the exact files/sections to read first.
- The expected output files.
- The completion criteria.
- The escalation protocol (when to stop and write to QUESTIONS.md instead of acting).

See `scripts/spawn_agent.md` for the template.
