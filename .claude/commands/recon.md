---
description: Spawn the recon subagent to investigate the live USTA site. Requires credentials in .env and explicit user authorization for live network activity.
---

Invoke the recon subagent. Before doing so, confirm:

1. `.env` has valid `USTA_USERNAME` and `USTA_PASSWORD`.
2. The user has explicitly authorized live recon in this session.
3. `STATE.md` reflects that recon is the active workstream.

Then:

> Use the Task tool with `subagent_type: recon` and pass the recon charter from `.claude/agents/recon.md`. Do not run recon inline in the main session.
