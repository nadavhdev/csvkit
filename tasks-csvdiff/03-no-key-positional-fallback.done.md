# task-03 — done

**Task spec:** [done/03-no-key-positional-fallback.md](done/03-no-key-positional-fallback.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/7 (targets `feat/csvdiff-composite-key`)
**Commit:** 384fdf8
**Completed:** 2026-06-11
**Branch:** feat/csvdiff-positional-fallback (branched off task-02's `feat/csvdiff-composite-key`)

## What was built

`csvdiff` now accepts two CSV files without `-c/--key` and compares them row-by-row positionally. Row N of LEFT is compared to row N of RIGHT on the common column intersection. Surplus rows on the longer side are reported as `removed` (LEFT longer) or `added` (RIGHT longer). The key slot in all output lines is the 1-based row index (`row=1`, `row=2`, etc.) via the existing `_key_display` path with synthetic `['row']` key_names. The epilog explicitly warns about the re-sorted-file footgun and points users to `-c`.

## Files changed

- `csvkit/utilities/csvdiff.py` — added `_compute_positional_diff`; removed mandatory-key guard; updated `main()` to dispatch keyed vs positional; extended `epilog` with positional-mode warning
- `tests/test_utilities/test_csvdiff.py` — removed obsolete `test_exit_2_missing_key_flag`; added `TestCSVDiffPositional` (14 CLI tests) and 9 `_compute_positional_diff` engine unit tests within `TestCSVDiffEngine`; imported `_compute_positional_diff`
- `examples/diff_pos_a.csv` — 3-row baseline fixture (name/score)
- `examples/diff_pos_b.csv` — 3-row fixture with row 2 changed (score: 20→99)
- `examples/diff_pos_short.csv` — 2-row fixture (first 2 rows of diff_pos_a) for length-mismatch tests
- `examples/diff_pos_empty.csv` — header-only fixture for both-empty test

## Decisions & departures from spec

- **`['row']` as synthetic key_names**: `render_human` is called with `['row']` in positional mode so `_key_display(['row'], (N,))` renders `row=N`. No changes to `render_human` were needed — clean reuse of the existing single-key display path.
- **`--ignore` does NOT filter surplus-row display fields**: In keyed mode, `_compute_diff` shows all non-key columns in removed/added rows regardless of `ignore_names` — `--ignore` only suppresses the *comparison* for changed rows. `_compute_positional_diff` matches this behavior: surplus rows display all columns, with `ignore_names` applied only to the `compare_cols` loop for paired rows. This was clarified during the review loop (round 2 nit).
- **SchemaDelta is computed but not rendered**: `DiffResult.schema` is populated by `_compute_positional_diff`, consistent with task-01's keyed-mode behavior. Task-04 will wire up schema rendering for both paths without touching `_compute_positional_diff`.
- **`test_exit_2_missing_key_flag` removed**: This test verified that running without `-c` exited 2. That behavior is now replaced by positional mode. The test was cleanly deleted; the new behavior is covered by `TestCSVDiffPositional`.

## Test coverage

- ✓ Equal-length identical files exit 0
- ✓ Equal-length with mid-stream field change exits 1
- ✓ LEFT longer → surplus rows appear as `removed`, exit 1
- ✓ RIGHT longer → surplus rows appear as `added`, exit 1
- ✓ Both-empty (header-only) exits 0
- ✓ Row key format: `row=N` (1-based) in changed, removed, and added lines
- ✓ Changed-row field delta format: `field: left -> right`
- ✓ Removed-row field values: `field=val`
- ✓ Added-row field values: `field=val`
- ✓ Headline counts: `0 changed, 0 added, 1 removed (of 2 rows compared)` etc.
- ✓ `--ignore` suppresses paired-row comparison (exit 0 when only ignored column differs)
- ✓ `--ignore` does NOT hide ignored columns from surplus-row display
- ✓ Epilog contains 'positional', 're-sorted', and '-c'
- ✓ Help text contains 'positional' and 're-sorted'
- ✓ Engine: equal-length identical, equal-length changed, 1-based key, left-longer, right-longer, both-empty, ignore suppresses comparison, schema delta computed, ordering preserved

## Review findings & resolutions

- **Round 1** — APPROVE, 2 nits.
  - Nit: help-text test only asserted 'positional', not 're-sorted'. Fixed: added `assertIn('re-sorted', help_text)`.
  - Nit: no CLI-level `--ignore` test for positional mode. Fixed: added `test_positional_with_ignore_suppresses_change`.
- **Round 2** — APPROVE (post-round-1 re-review), 1 nit.
  - Nit: `ignore_names` filtered surplus-row display fields in positional mode, diverging from keyed-mode behavior. Fixed: removed the filtering; surplus rows now iterate over `left_cols`/`right_cols` directly. Added `test_positional_ignore_does_not_hide_fields_in_surplus_rows` to verify.
- **Round 3** — APPROVE (post-round-2 re-review), 1 nit deferred.
  - Nit: `SchemaDelta` construction block is duplicated between `_compute_diff` and `_compute_positional_diff`. Deferred — cosmetic-only, no correctness impact. Best addressed in task-04 when schema rendering touches both paths.

## Things the next task should know

- **`_compute_positional_diff`** is the new module-level function in `csvkit/utilities/csvdiff.py`. It takes `(left_table, right_table, ignore_names)` → `DiffResult`. Task-04 (schema drift display) can consume `DiffResult.schema` from both the keyed and positional paths without touching either function.
- **Dispatch in `main()`**: `if self.args.key:` → keyed path; `else:` → positional path. Task-04 should hook schema rendering into `render_human`, which is called from both branches.
- **`SchemaDelta` construction is duplicated**: The 6-line schema delta block in `_compute_positional_diff` is identical to the one in `_compute_diff`. Task-04 (or a follow-up cleanup) could extract a `_compute_schema_delta(left_cols, right_cols)` helper to eliminate the duplication.
- **`['row']` is the synthetic key_names for positional mode**: Any future renderer (e.g., task-05's JSONL renderer) that branches on key_names should expect `['row']` as the positional-mode sentinel.
- **Existing `test_exit_2_missing_key_flag` is gone**: It was testing old behavior. Any future task that re-adds a mandatory-key guard (e.g. in a new mode) would need a new test.

## Open questions surfaced

- None — all spec behaviors were clear and implemented as written.
