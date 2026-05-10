# Spawning a subagent

Template for the Orchestrator (the human or the lead Claude session) when invoking a named subagent in `.claude/agents/`.

## Pattern

1. Read STATE.md to see what's currently in flight.
2. Pick the agent whose charter matches the work.
3. Invoke via the Task tool with `subagent_type: <agent name>` and a self-contained prompt that includes:
   - The specific scope (one entity, one route, one decision — not "everything").
   - Pointers to the relevant fixtures, ADRs, or sections of SPEC.md.
   - The expected output files.
   - The completion criteria.
4. After the agent reports back, the Orchestrator updates STATE.md and CHANGELOG.md.

## Anti-patterns

- Spawning multiple agents that touch the same module concurrently — they'll fight.
- Asking an agent to "do recon and write parsers and ship UI" — too broad. Subagents work best with narrow charters.
- Letting an agent silently rewrite SPEC.md or DECISIONS.md without surfacing the change.

## When to NOT spawn a subagent

- Single-file edits with no research component — do them inline.
- Quick clarifying questions — answer in the main session.
- Anything that needs to see the full conversation context — subagents start cold.
