# task-05 — done

**Task spec:** [done/05-jsonl-renderer.md](done/05-jsonl-renderer.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/9
**Commit:** 2a7aae1
**Completed:** 2026-06-12
**Branch:** feat/csvdiff-jsonl-renderer (off feat/csvdiff-schema-drift)

## What was built

`csvdiff` now emits machine-readable JSONL via `-f/--format jsonl`. The
renderer sends one JSON object per line: a `summary` event (always first,
with `compared`/`changed`/`added`/`removed`/`schema_changed` fields), an
optional `schema` event (iff schema drift is being reported), then one `row`
event per diff in the existing stable order. Decimal and date values are
serialized via `default_str_decimal` from `csvkit.cli` — no new runtime
dependency. A new `-f/--format {human,jsonl}` flag selects the renderer;
the default remains `human`.

## Files changed

- `csvkit/utilities/csvdiff.py` — added `render_jsonl()`, `import json`,
  `default_str_decimal` import, `-f/--format` flag in `add_arguments()`,
  and a one-line `renderer =` dispatch in `main()` replacing the two
  hardcoded `render_human()` calls
- `tests/test_utilities/test_csvdiff.py` — added `import json`, `RowDelta`
  to imports, `render_jsonl` to imports; added `TestCSVDiffJSONL`
  (17 tests) inheriting from `_CSVDiffOutputMixin, CSVKitTestCase`

## Decisions & departures from spec

- **`choices=['human', 'jsonl']` (not `['human', 'jsonl', 'summary']`):**
  The TDD §4a lists all three format values but task-05 only implements
  `jsonl`. Added only `human` and `jsonl` as valid choices so that
  `--format summary` fails fast with an argparse error rather than
  falling through to undefined behavior. Task-06 extends choices to include
  `summary` when it implements `render_summary`.
- **Counter loop instead of list comprehensions:** Round-1 review (nit 1.4)
  pointed out that building three filtered lists just to call `len()` creates
  unnecessary objects. Replaced with a single `n_changed/n_added/n_removed`
  counter pass, then the existing row-event loop iterates `result.row_diffs`.
- **`render_jsonl` signature mirrors `render_human`:** Same
  `(result, key_names, output_file, show_schema=False)` signature so
  task-06 can dispatch to it in exactly the same way as `render_human`.

## Test coverage

- ✓ Equal files → single summary event, all-zero counts, `compared` field asserted
- ✓ Every output line independently parseable by `json.loads`
- ✓ Row-only diff: summary + row events, no schema event
- ✓ Summary counts match row event counts (verified programmatically)
- ✓ `changed` fields shape: `{col: {"left": val, "right": val}}`
- ✓ `added`/`removed` fields shape: flat `{col: val}` (missing side implicit)
- ✓ Schema-only diff: schema event present, `schema_changed: true`, no row events
- ✓ Schema event fields: `added_columns`, `removed_columns`, `reordered`
- ✓ Combined row+schema: schema event precedes row events
- ✓ `--no-schema-check` suppresses schema event, `schema_changed: false`
- ✓ Composite key shape: `{"order_id": ..., "line_no": ...}`
- ✓ No-key positional key shape: `{"row": N}` (integer)
- ✓ Decimal serialization: price field (agate-inferred Decimal) → str via `default_str_decimal`
- ✓ Exit codes 0/1/2 each verified with `--format jsonl`
- ✓ Engine unit test: `render_jsonl` called directly on a `DiffResult` (no CLI)
- ✗ Date-type serialization not tested with a real date fixture (Decimal is exercised;
  `default_str_decimal` handles both via the same `isinstance` branches, so this is
  a low-risk gap)

## Review findings & resolutions

**Full ledger:** [05-jsonl-renderer.review.md](05-jsonl-renderer.review.md)

- Round 1 (REQUEST_CHANGES): 2 major, 1 minor, 1 nit.
  - Major 1.1: `TestCSVDiffJSONL` duplicated `get_output`/`_exit_code_for` instead of
    inheriting `_CSVDiffOutputMixin`. Fixed: class now inherits the mixin.
  - Major 1.2: Decimal serialization test used `-I`, making all values strings —
    `default_str_decimal` was never invoked. Fixed: removed `-I`, asserts price field
    values are `str` after agate infers them as `Decimal`.
  - Minor 1.3: `compared` field not asserted in any summary test. Fixed: added
    `assertEqual(ev['compared'], 3)` to `test_equal_files_emits_summary_only`.
  - Nit 1.4: three list comprehensions for counts. Fixed: single counter loop.
- Round 2 (APPROVE): 0 new findings; all prior findings confirmed closed.
- Deferred nits: none.

## Things the next task should know

- **`render_jsonl` signature is `(result, key_names, output_file, show_schema=False)`** —
  exactly mirrors `render_human`. Task-06 (`render_summary`) should use the same
  signature so the dispatch in `main()` remains a one-liner:
  `renderer = {dispatch dict}.get(self.args.format, render_human)`.
- **Format dispatch is in `main()` at line ~407:**
  `renderer = render_jsonl if self.args.format == 'jsonl' else render_human`.
  Task-06 should extend this to handle `'summary'` (add `render_summary` import and
  update the dispatch expression).
- **`--format` choices are `['human', 'jsonl']` currently.** Task-06 must add
  `'summary'` to the `choices` list in `add_arguments()`. The argparse definition is
  at around line 357 of `csvdiff.py`.
- **`TestCSVDiffJSONL` uses `_CSVDiffOutputMixin`.** The `test_decimal_serialization_via_default_str_decimal`
  test exercises the price field (Decimal) but not date fields — worth noting if
  task-07's rst doc examples use date-valued columns.
- **The `_CSVDiffOutputMixin` pattern is the established convention** for all
  feature-level test classes in `test_csvdiff.py`. Any new test class (task-06's
  `TestCSVDiffSummary`, task-06's `TestCSVDiffQuiet`, etc.) must inherit from it.

## Open questions surfaced

- None — spec and TDD were unambiguous. The only implementation-time decision
  (limiting `choices` to `['human', 'jsonl']` for now) is documented above.
