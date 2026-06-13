# task-02 — done

**Task spec:** [done/02-composite-key-and-duplicate-handling.md](done/02-composite-key-and-duplicate-handling.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/6 (targets `feat/csvdiff-walking-skeleton`)
**Commit:** efd6924
**Completed:** 2026-06-11
**Branch:** feat/csvdiff-composite-key (branched off task-01's `feat/csvdiff-walking-skeleton` at cfdabf2)

## What was built

`csvdiff`'s `-c/--key` now accepts a comma-separated list of column names or 1-based indices, forming a composite tuple key per row. A new `--on-dup` flag (choices: `error`, `first`, `all`) controls behavior when the chosen key is not unique within a file. The `error` default exits 2 with a diagnostic naming the side (LEFT/RIGHT), the duplicated key value, and the 1-based row numbers of the first and repeated occurrence. `first` silently keeps only the first occurrence per key. `all` compares the Cartesian product of all matching duplicate rows, with the O(n·m) hazard documented in both the flag help text and the epilog. Composite keys render as `key=(v1,v2)` in human output; single keys retain the `name=val` format from task-01.

## Files changed

- `csvkit/utilities/csvdiff.py` — added `DuplicateKeyError` exception, `_build_key_index` helper, updated `_compute_diff` signature to `(left_key_names, right_key_names, on_dup, ignore_names)` with full Cartesian/first/error logic, updated `_key_display` and `render_human` for composite keys, added `--on-dup` flag and updated epilog, added `_resolve_key_names` method, moved `key_names.append` inside try block
- `tests/test_utilities/test_csvdiff.py` — updated 7 existing `TestCSVDiffEngine` calls to the new signature, extracted `_CSVDiffOutputMixin` with shared `get_output`/`_exit_code_for`, added `TestCSVDiffCompositeKey` (8 CLI tests), added `TestCSVDiffOnDup` (14 CLI tests), added `TestBuildKeyIndex` (5 unit tests), added 11 new engine tests for composite keys, on_dup modes, and `_key_display`
- `examples/diff_composite_a.csv`, `examples/diff_composite_b.csv` — composite key (order_id,line_no) fixture pair: 1 changed, 1 removed, 1 added, 1 unchanged
- `examples/diff_dup_a.csv`, `examples/diff_dup_b.csv` — duplicate key (id=1 duplicated in a) fixture pair for --on-dup tests

## Decisions & departures from spec

- **`_compute_diff` signature change:** Changed from `(left_key_name: str, right_key_name: str, ignore_names)` to `(left_key_names: list, right_key_names: list, on_dup: str, ignore_names)`. This is the only breaking change to the internal API; all prior calls in tests are updated.
- **Index always `dict[tuple, list[int]]`:** `_build_key_index` always returns a list of indices per key. For `error`/`first`, each list has at most one element after processing. For `all`, lists may have N elements. This uniform representation simplifies the comparison loop.
- **`compared_count` for `--on-dup=all`:** Counts Cartesian pairs, not unique key matches. So a key with 2 left and 3 right occurrences contributes 6 to `compared_count`. This is the literal truth of "how many comparisons were made" and matches the headline "N rows compared."
- **`all_key_names` union for `compare_cols`:** Excluded both `left_key_names` and `right_key_names` from `compare_cols` to avoid asymmetric column-name differences causing spurious key column comparisons. This is strictly correct.
- **agate type inference in engine tests:** Engine tests use alphabetic key values (e.g. `'K1'`, `'Ka'`) rather than numeric strings like `'1'`, because agate infers single-value or boolean-looking columns as `True`/`False`. Numeric-looking multi-value columns work fine (agate uses Decimal), but the `str(key_part)` pattern is used for key assertions in the existing test suite.

## Test coverage

- ✓ Composite arity-2 key matched by tuple (same first part, different second → distinct)
- ✓ Composite key display: `key=(A001,1)` in changed/removed/added lines
- ✓ Key by name and by 1-based index produce identical output
- ✓ Key columns excluded from changed/removed/added field dicts
- ✓ `--on-dup=error` exits 2, names LEFT or RIGHT, names key value, names 1-based row numbers
- ✓ `--on-dup=first` left-side dup: compares first occurrence, discards second
- ✓ `--on-dup=first` right-side dup: symmetric behavior
- ✓ `--on-dup=all` LEFT=2/RIGHT=1 → 2 pairs; LEFT=1/RIGHT=2 → 2 pairs; LEFT=2/RIGHT=2 → 4 pairs
- ✓ O(n·m) text present in `--on-dup` flag help and `CSVDiff.epilog`
- ✓ `_build_key_index` unit tests for all three modes
- ✓ `_key_display` unit tests for single (name=val) and composite (key=(v1,v2,v3)) forms
- ✗ CLI-level arity-3 fixture test: not added. The engine test (`test_composite_key_arity3`) covers the logic; a CLI test would require an arity-3 fixture file. Deferred nit from round-2 review; can be added in task-07 (docs) or a follow-up.

## Review findings & resolutions

- **Round 1** — APPROVE, 2 minors, 1 nit.
  - Minor (code-quality): `get_output`/`_exit_code_for` copy-pasted between two test classes. Fixed by extracting `_CSVDiffOutputMixin`.
  - Minor (testing): missing right-side-dup coverage for `--on-dup=first` and `--on-dup=all` LEFT=1/RIGHT=2. Fixed by adding 4 new tests.
  - Nit: `idx` possibly unbound after `argparser.error()` in `_resolve_key_names`. Fixed by moving `key_names.append` inside the try block.
- **Round 2** — APPROVE, 3 nits.
  - Nit: `Utility = CSVDiff` redundant in mixin. Fixed by removing it from mixin, relying on subclass declarations.
  - Nit: CLI-level dup row assertion only checked `'row'` not specific numbers. Fixed to assert `'row 1'` and `'row 2'`.
  - Nit: No CLI-level arity-3 test. Deferred (see above).
- **Deferred nits:** CLI-level arity-3 composite key test.

## Things the next task should know

- **`_compute_diff` new signature:** `(left_table, right_table, left_key_names: list, right_key_names: list, on_dup: str, ignore_names: set)`. Any task that calls `_compute_diff` must pass lists for key names. Task-03 (no-key positional fallback) will bypass `_compute_diff` entirely or add a separate positional path; task-04 (schema drift) can use the existing function unchanged.
- **`_build_key_index` is the seam for index construction.** It's a standalone module-level function taking `(table, key_names, on_dup, side)` → `dict[tuple, list[int]]`. If task-03 needs to build an index for positional rows, it should follow the same pattern.
- **`render_human` now takes `key_names: list` not `key_name: str`.** Update any future renderer or test that calls it directly.
- **`DuplicateKeyError` is a module-level exception** in `csvkit/utilities/csvdiff.py`. The CLI catches it in `main()` and routes through `self.argparser.error()` → exit 2. Anything that adds new index-building logic should raise `DuplicateKeyError` (not call argparser directly) to stay consistent.
- **The `done/` directory** under `tasks-csvdiff/` already exists from task-01's handoff. Task-03 etc. can move their `.md` there after completion.

## Open questions surfaced

- None — all spec behaviors were clear and implemented as written.
