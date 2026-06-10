### Documentation, changelog entry, AUTHORS update, and experimental rollout

**One-liner:** Land the user-facing documentation, the CHANGELOG entry, the AUTHORS contributor update, and the experimental-status banner that gates the first release per the project's definition of done.

**Composes:**
- `docs/scripts/csvdiff.rst` mirroring `docs/scripts/csvjoin.rst`'s structure: synopsis, description, flag reference (covering every csvdiff-specific flag plus an inherited-flag reference), and examples for keyed match, no-key positional, composite key, schema-drift, and JSONL output. The page leads with an **"experimental — interface may change in 2.4.x"** banner per TDD §8 Phase 1.
- The rst page documents the exit-code contract (0/1/2) prominently — this is a new pattern for csvkit and the §7 risk ("downstream script assumed csvkit tools only exit 0 or 2") makes the explicit doc critical.
- The rst page documents the design choices and known limitations: typed-comparison-by-default with the `-I` escape (§4g), the in-memory bound (§4d), the schema-rename-as-removed+added behavior (§7), the global `-e/--encoding` limitation (§7 / §10 OQ6), and the `-H`/schema-diff suppression (§10 OQ7).
- The docs script index is updated to list `csvdiff` alongside the other tools.
- `CHANGELOG.rst` top entry in the existing style: `-  feat: :doc:`/scripts/csvdiff` adds a CSV-aware diff tool (experimental).` plus a short note that csvdiff introduces a 0/1/2 exit-code contract — the new-pattern callout from §7.
- `AUTHORS.rst` is updated for any new contributors on this work per the project's PR checklist.
- The `epilog` text already set in [[01-walking-skeleton-keyed-csvdiff]] is reviewed against the final rst copy and reconciled if the experimental-status, typed-comparison, or in-memory-bound wording drifted.
- This task is a **cross-cutting closer**: each bullet covers a release-wide concern that no single feature task owns (one rst page that spans every flag, one CHANGELOG entry, one AUTHORS update, one banner roll-out). Per-feature help text and per-section `epilog` wording live in the feature tasks' acceptance criteria — this task assembles only the release-wide artifacts.

**TDD sections addressed:** §0 (PR-checklist items: rst doc, CHANGELOG, AUTHORS, registration verification), §7 (downstream-script-assumed-exit-codes risk → CHANGELOG callout), §8 Rollout (Phase 1 experimental banner), §10 OQ6 + OQ7 (limitation documentation).

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]], [[02-composite-key-and-duplicate-handling]], [[03-no-key-positional-fallback]], [[04-schema-drift-detection]], [[05-jsonl-renderer]], [[06-summary-renderer-and-quiet]].

**Acceptance criteria:**
- `docs/scripts/csvdiff.rst` exists, follows the same structural template as `docs/scripts/csvjoin.rst`, documents every csvdiff-specific flag, and is added to the docs script index alongside the other tools.
- The rst page's first section is an "experimental" banner stating that flags, output, and exit codes may change in 2.4.x and pointing readers at the issue tracker for feedback.
- The rst page documents the 0/1/2 exit-code contract explicitly, with one paragraph each on the parse-error → 2 mapping, the row-or-schema-diff → 1 mapping, and the equivalence → 0 mapping.
- The rst page documents the typed-by-default comparison + `-I` escape, the in-memory bound, the rename-as-removed+added schema behavior, the global `-e/--encoding` limitation (no per-file encoding), and the `-H`/schema-diff suppression.
- `CHANGELOG.rst` top entry follows the existing `-  feat: :doc:`/scripts/X`` style and explicitly notes csvdiff's 0/1/2 exit-code contract.
- `AUTHORS.rst` lists any new contributors on this work.
- The CLI `epilog` text matches the final user-visible doc copy on experimental status, typed comparison, and in-memory bound; any drift between rst and epilog is reconciled before merge.
- `check-manifest` passes after the new rst file is added; `flake8 .` and `isort . --check-only` remain clean; the full `pytest --cov csvkit` suite passes across Python 3.10–3.14 + pypy-3.11 on macOS / Windows / Linux per the project CI matrix.
