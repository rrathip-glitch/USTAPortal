---
description: Run the self-improvement loop — scan recent changes and propose updates to canonical docs (SPEC.md, STATE.md, QUESTIONS.md, DECISIONS.md).
---

Execute:

```bash
python scripts/update_canonical_docs.py
```

The script does not silently rewrite docs. It produces a diff to review. Apply changes with `--apply` only after reading them.
