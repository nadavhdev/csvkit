### Schema-drift detection: added / removed / reordered columns

**One-liner:** Detect and report column-level differences (added, removed, reordered) between LEFT and RIGHT as a distinct section ahead of row diffs, with `--no-schema-check` to opt out and `-H` interaction per OQ7.

**Composes:**
- New `schema_diff(left_table, right_table)` step producing a `SchemaDelta` (`added`, `removed`, `reordered`, `common`) per TDD §4f, computed before row classification.
- Human renderer emits a `! schema changed:` block before the headline when any of `added`, `removed`, or `reordered` is non-empty, naming added columns in RIGHT order and removed columns in LEFT order.
- Row diff narrows to the column intersection (`common`) so a column added on one side does not produce per-row noise; the schema banner makes the column-set change explicit instead.
- `--no-schema-check` skips the schema section entirely and silently uses the intersection — the diff exits as if the schema were identical.
- `-H/--no-header-row` interaction (resolves TDD §10 OQ7): with `-H`, column names are `make_default_headers` synthetic (`a, b, c, …`) and a schema diff would be either no-op or pure noise; this task suppresses the schema section under `-H` and documents the behavior in both `epilog` and the rst doc page added by [[07-docs-changelog-experimental-rollout]].
- Schema-only differences route to the exit-code 1 bucket per §4b (zero row diffs + non-empty schema delta → exit 1, not 0).
- Document the §7 "rename misses" limitation: a renamed column (`qty` → `quantity`) appears as `removed: qty` + `added: quantity` — the literal truth, not papered over.
- Encoding-mismatch limitation from §7 belongs here too: the inherited `-e/--encoding` applies to both files; document in the rst page that per-file encoding is out of scope (resolves §10 OQ6 for the v1 ship).

**TDD sections addressed:** §4a (`--no-schema-check`), §4b Exit codes (schema-only diffs route to exit 1), §4f Data model (`SchemaDelta`), §4g Comparison semantics (column intersection), §4h Human renderer (`! schema changed:` banner), §7 (rename-as-removed+added risk, encoding-mismatch limitation), §10 OQ6 + OQ7.

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]].

**Acceptance criteria:**
- When LEFT and RIGHT have identical column sets in the same order, no schema banner is emitted and the row-diff section is unchanged from the walking skeleton's behavior.
- When RIGHT contains a column absent from LEFT, the human output begins with `! schema changed:` naming the added column; that column is not reported in row diffs (rows differ only on the intersection).
- When LEFT contains a column absent from RIGHT, similarly named in `removed:`.
- When the common columns appear in a different order, `reordered: true` is reported in the schema banner.
- A run with only schema differences and no row differences exits 1, not 0.
- `--no-schema-check` suppresses the schema banner and the exit code is determined by row diffs alone.
- Under `-H/--no-header-row`, the schema section is suppressed regardless of `--no-schema-check`, and this behavior is documented in `epilog` (and surfaces in the rst doc page from [[07-docs-changelog-experimental-rollout]]).
- A rename (`qty` → `quantity`) is reported as `removed: qty` + `added: quantity` per the documented design choice; the rst page from [[07-docs-changelog-experimental-rollout]] calls out the limitation.
- Tests cover: identical schemas, added-only, removed-only, reordered-only, all three at once, `--no-schema-check`, `-H` suppression, and schema-only-diff exit code = 1.
