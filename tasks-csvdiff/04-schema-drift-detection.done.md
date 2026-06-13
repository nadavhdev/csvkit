# task-04 — done

**Task spec:** [done/04-schema-drift-detection.md](done/04-schema-drift-detection.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/8 (targets `feat/csvdiff-positional-fallback`)
**Commit:** 1e5652c
**Completed:** 2026-06-11
**Branch:** feat/csvdiff-schema-drift (branched off task-03's `feat/csvdiff-positional-fallback` at 384fdf8)

## What was built

`csvdiff` now detects and reports column-level schema drift. When LEFT and RIGHT
differ in their columns, a `! schema changed:` banner is emitted **before** the
headline, naming added columns (in RIGHT order), removed columns (in LEFT order),
and `reordered: true` when the shared columns appear in a different relative order.
A schema-only difference (zero row diffs) now exits 1, completing the TDD §4b
"differences found" contract. A new `--no-schema-check` flag opts out of the banner
and the schema exit-code contribution. Under the inherited `-H/--no-header-row` the
schema section is suppressed entirely (synthetic headers `a, b, c, ...` make drift
meaningless — resolves TDD OQ7). Schema drift works identically in keyed and no-key
positional modes, since the banner renders from the shared `render_human` path.

## Files changed

- `csvkit/utilities/csvdiff.py` — added `_compute_schema_delta(left_cols, right_cols)` (extracted, now used by both compute paths), `_schema_changed(schema)` predicate, `_render_schema_banner(schema, output_file)`; `render_human` gained a `show_schema=False` param; `main()` computes `schema_active` and includes schema in the exit-code decision; added `--no-schema-check`; extended `epilog`
- `tests/test_utilities/test_csvdiff.py` — added `TestCSVDiffSchema` (CLI, all 8 criteria), schema-engine unit tests in `TestCSVDiffEngine` (`_compute_schema_delta` ordering/reorder, `_schema_changed`, `render_human` banner gating + intersection field exclusion); imports `DiffResult, SchemaDelta, _compute_schema_delta, _schema_changed, render_human`
- `examples/diff_schema_base.csv` — canonical LEFT (id,name,price)
- `examples/diff_schema_added.csv` — RIGHT with extra `region`, identical common data (pure schema-only; used for added/removed-by-swap and the `-H` exit-code-flip test)
- `examples/diff_schema_added_changed.csv` — like added.csv but row 2 `price` differs (drives the "added column absent from a real `~` row line" test)
- `examples/diff_schema_reordered.csv` — id,price,name (reordered common columns, same data → schema-only)
- `examples/diff_schema_all_right.csv` — price,id,region (vs base: removed name + added region + reordered, all at once)
- `examples/diff_schema_rename_left.csv` / `diff_schema_rename_right.csv` — qty → quantity rename pair

## Decisions & departures from spec

- **`_compute_schema_delta` extraction:** Task-03's handoff explicitly assigned the duplicated `SchemaDelta`-construction nit to task-04 "when schema rendering touches both paths." Done here — both `_compute_diff` and `_compute_positional_diff` now call the one helper. This is the only structural refactor; it is in-scope per the prior handoff, not freelancing.
- **`render_human(..., show_schema=False)`:** The renderer stays flag-agnostic; `main()` decides activeness (`schema_active = not no_schema_check and not no_header_row`) and passes the boolean in. The banner is emitted only when `show_schema and _schema_changed(result.schema)`. Default `False` keeps the renderer safe for any caller that omits the arg.
- **Banner format (not fully pinned by the TDD §4h):** chose a compact block — `! schema changed:` header, then only the non-empty lines among `  added: a, b`, `  removed: x, y`, `  reordered: true`. Consistent with the tool's existing terse output grammar. This was an implementation-time format choice (the TDD only specified the `! schema changed:` marker), not a spec deviation.
- **Intersection narrowing is pre-existing:** narrowing row comparison to `schema.common` was already in place from task-01, so an added column never produced per-row noise even before this task. Task-04 adds the explicit banner + the exit-code contribution on top.
- **Rename / encoding docs deferred to task-07:** The rename-as-removed+added limitation and the per-file-encoding (OQ6) limitation are surfaced in behavior here (rename works; `-e` is global) but their **rst-page documentation** is task-07's scope per the task spec. The `epilog` documents the schema banner, `--no-schema-check`, and the `-H` suppression.

## Test coverage

- ✓ Identical schema → no banner, row-diff section unchanged, exit 0
- ✓ Added column → `! schema changed:` banner naming it (begins output), exit 1
- ✓ Added column absent from a real `~` changed row-diff line (non-vacuous after round-1 fix)
- ✓ Removed column → `removed:` in banner
- ✓ Reordered common columns → `reordered: true`
- ✓ All three deltas at once
- ✓ Schema-only difference (reordered, 0 row diffs) exits 1, not 0
- ✓ `--no-schema-check` suppresses banner; schema-only diff then exits 0; genuine row diff still exits 1
- ✓ `-H` suppresses banner AND the schema exit-code contribution (exit 1 → 0); also with `--no-schema-check`
- ✓ Rename → `removed: qty` + `added: quantity`
- ✓ Schema banner also renders in no-key positional mode
- ✓ Engine: `_compute_schema_delta` added/removed ordering + reorder vs non-common columns; `_schema_changed` on each delta kind; `render_human` banner gating; added column excluded from a changed row's `fields`
- ✗ No rst/CHANGELOG/AUTHORS (task-07 scope, as specified)

## Review findings & resolutions

**Full ledger:** [04-schema-drift-detection.review.md](04-schema-drift-detection.review.md)

- Round 1 — APPROVE, 1 minor (testing). `test_added_column_not_reported_in_row_diffs` was vacuous: BASE vs ADDED share identical common-column data, so the diff had zero row-diff lines and the assertion loop never ran. Resolved by adding `diff_schema_added_changed.csv` (a changed common column) and asserting a real `~` line exists before checking the added column is absent.
- Round 2 — APPROVE (targeted re-review), 0 new findings; finding 1.1 confirmed closed.
- Deferred nits: none.

## Things the next task should know

- **`_compute_schema_delta(left_cols, right_cols)`** is the single source of truth for the column delta now — both keyed and positional engines call it. Task-05 (JSONL) should build its `schema` event from the same `DiffResult.schema`.
- **`_schema_changed(schema)`** is the reusable predicate for "is there schema drift." Task-05's JSONL `schema_changed` field and task-06's summary marker should use it rather than re-checking `added/removed/reordered`.
- **`render_human` now takes `show_schema: bool`** (default False). The new JSONL/summary renderers (tasks 05/06) should take the same boolean and gate their schema event/marker on `show_schema and _schema_changed(...)`, mirroring `render_human`, so `--no-schema-check` and `-H` behave consistently across all formats.
- **`schema_active` is computed in `main()`** as `not self.args.no_schema_check and not self.args.no_header_row`. When tasks 05/06 add `--format`, they must pass this same boolean to every renderer; do not recompute it per-renderer.
- **Exit-code rule is now** `result.row_diffs or (schema_active and _schema_changed(result.schema))`. Any new renderer/format must NOT change this; the exit code is format-independent (task-06's `--quiet` relies on this).
- **The `! schema changed:` banner format** is: header line, then non-empty `  added:` / `  removed:` / `  reordered: true` lines (comma-separated column lists). If task-07's rst doc shows example output, mirror this exactly.
- **Rename and per-file-encoding (OQ6) limitations** are real and need rst documentation in task-07: a rename shows as `removed: <old>` + `added: <new>`; `-e/--encoding` applies to both files (no per-file override in v1). The behavior is correct here; only the docs are outstanding.

## Open questions surfaced

- None — OQ7 (schema under `-H`) was resolved by suppression as the TDD recommended; OQ6 (per-file encoding) remains a documented v1 limitation for task-07's rst page, not a blocker.
