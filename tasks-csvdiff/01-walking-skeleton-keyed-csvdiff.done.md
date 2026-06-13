# task-01 — done

**Task spec:** [done/01-walking-skeleton-keyed-csvdiff.md](done/01-walking-skeleton-keyed-csvdiff.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/4
**Commit:** cfdabf2
**Completed:** 2026-06-11
**Branch:** feat/csvdiff-walking-skeleton (off csv-tdd)

## What was built

`csvdiff` is a new csvkit CLI tool that compares two CSVs by a single key column and
reports row-level differences in human-readable format. It implements a three-exit-code
contract (0 = identical, 1 = differences found, 2 = usage/parse error), supports all
four stdin/named-file invocation styles, typed and raw-string comparison (`-I`), and
column exclusion (`--ignore`). Entry point registered as `csvdiff` in `pyproject.toml`.

## Files changed

- `csvkit/utilities/csvdiff.py` — created; `CSVDiff` tool, `_compute_diff`, `render_human`, data classes
- `tests/test_utilities/test_csvdiff.py` — created; 43 tests across `TestCSVDiff` (CLI) and `TestCSVDiffEngine` (pure engine)
- `examples/diff_a.csv` — fixture: 3 rows (id/name/price), baseline
- `examples/diff_b.csv` — fixture: 3 rows, 1 changed (price), 1 removed (cherry), 1 added (date)
- `examples/diff_types_a.csv` / `diff_types_b.csv` — typed equality fixture (value 1 vs 1.0)
- `examples/diff_key_types.csv` / `diff_key_types_b.csv` — key type formatting fixture (int, decimal, date keys)
- `pyproject.toml` — added `csvdiff = "csvkit.utilities.csvdiff:launch_new_instance"` to `[project.scripts]`

## Decisions & departures from spec

- **Exit 2 for parse errors:** `_read_table` wraps `csv.Error`, `UnicodeDecodeError`,
  and `agate.exceptions.FieldSizeLimitError` (not `CSVTestException` — that class does
  not exist in current agate). All three route to `self.argparser.error()` → exit 2.
  This is the most important behavioral departure from the existing tools (which let
  parse errors become unhandled exceptions → exit 1). See TDD §4b.
- **`agate.exceptions.CSVTestException` does not exist:** The TDD referenced it as an
  example; the real class is `FieldSizeLimitError`. Used that instead.
- **Key column excluded from field display:** The key column is shown as `key=VALUE` in
  every diff line and is never repeated in the field list. This is implied by the format
  spec but not made explicit.
- **Schema diff computed but not rendered/acted on:** `DiffResult.schema` is fully
  populated by `_compute_diff` but not rendered in `render_human` and does not affect
  the exit code. Schema diff output is task 04's scope. The data is ready; the display
  is not.
- **`-I/--no-inference` is tool-specific:** It is NOT an inherited common flag (was
  verified against `_init_common_parser`). Re-declared as `-I/--no-inference` in
  `add_arguments()`.
- **`-y/--snifflimit` is tool-specific:** Similarly not inherited; declared manually.
- **Docs/CHANGELOG/AUTHORS deferred:** `docs/scripts/csvdiff.rst`, `CHANGELOG.rst`, and
  `AUTHORS.rst` are absent. This is intentional — task 07 owns those. The PR description
  calls this out explicitly.

## Test coverage

- ✓ Exit code 0 (no diffs), 1 (diffs found), 2 (missing key, bad key name, stdin double-use, interactive tty)
- ✓ Real `UnicodeDecodeError` integration test — temp file with `b'\xff\xfe'` bytes, no mocking of `_read_table`
- ✓ LEFT/RIGHT label in stderr for parse errors
- ✓ All four invocation styles (named/named, named/-, -/named, 1-path+redirected-stdin)
- ✓ All four produce identical output
- ✓ Headline format: `N changed, A added, R removed (of C rows compared)`
- ✓ Removed line prefix `-`, changed `~`, added `+` with key display and field values
- ✓ Output ordering: removed → changed → added
- ✓ Key by name and by 1-based index
- ✓ Typed equality (Decimal('1') == Decimal('1.0')) exits 0 with inference on
- ✓ Raw-string inequality under `-I` exits 1
- ✓ `--ignore` suppresses changed classification while preserving added/removed
- ✓ `--ignore` on nonexistent column is silent
- ✓ Key value formatting for int, decimal, and date types
- ✓ Perf-smoke: 200k × 10 cols, 1 changed row, exits 1, completes < 30 s
- ✓ Engine unit tests: schema delta, unchanged count, ordering, ignore semantics
- ✗ `csv.Error` trigger not tested (Python's csv module is lenient without `strict=True`; `UnicodeDecodeError` tests the same handler code path)
- ✗ `FieldSizeLimitError` trigger not tested (requires a 128 KB field; impractical as a fixture)
- ✗ `test_empty` override does not test the empty-CSV-as-input path (satisfies the mixin but does not verify behavior when an empty file is supplied as one input); the key-not-found path covers the relevant failure mode

## Review findings & resolutions

- **Round 1** — `REQUEST_CHANGES`, 1 major, 1 minor, 1 nit.
  - Major: parse-error tests mocked `_read_table`, bypassing the actual `except _PARSE_ERRORS` block.
    Fixed by adding `test_parse_error_real_unicode_error_exits_2` using a real temp file with invalid UTF-8.
  - Minor: docs/CHANGELOG/AUTHORS absent — accepted deferral to task 07.
  - Nit: `test_empty` override — accepted as-is (behavior adequately covered by key-not-found tests).
- **Round 2** — `APPROVE`, 2 minors, 1 nit.
  - Minor: perf-smoke test asserted only timing, not exit code. Fixed: changed fixture to produce a genuine
    1-changed row (modified non-key column, no duplicate keys) and added `assertEqual(code, 1)`.
  - Minor: docs/CHANGELOG/AUTHORS absent — deferred to task 07 (same as round 1).
  - Nit: misleading perf-smoke comment "one row differs" — fixed by changing the fixture and updating the comment.
- **Deferred nits:** `test_empty` override behavior (acceptable per mixin contract).

## Things the next task should know

- **`_compute_diff`** (`csvkit/utilities/csvdiff.py:71`) is the pure diff engine. It takes two `agate.Table`
  objects and returns a `DiffResult` dataclass. It is the seam for all future diff logic — task 02 (composite
  key), task 03 (no-key positional fallback), and task 04 (schema diff display) all hook in here.
- **`DiffResult.schema`** is a fully populated `SchemaDelta` (added/removed/reordered/common column lists)
  that `render_human` currently ignores. Task 04 can wire up schema rendering without touching `_compute_diff`.
- **`RowDelta.fields`** is `{col_name: (left_val, right_val)}`. For removed rows, `right_val` is `None`;
  for added rows, `left_val` is `None`. Task 02's rendering must handle this consistently.
- **Key is always a 1-tuple** `(typed_value,)`. Task 02 will need to extend this to an n-tuple; the dict
  key for `left_key_index` / `right_key_index` will need to change accordingly.
- **`_PARSE_ERRORS`** tuple is module-level. If task 02 or 03 adds file-reading logic, import and reuse it —
  do not define a second exception tuple.
- **`-y/--snifflimit` and `-I/--no-inference` are NOT inherited common flags.** They are declared in
  `CSVDiff.add_arguments()`. If any future task adds flags, check the common-flag list in CLAUDE.md first.
- **Typed comparison is the default.** `Decimal('1') == Decimal('1.0')` is `True` in Python; under `-I`
  these are unequal strings. Tests covering this are in `test_typed_equality_exits_0` and
  `test_raw_string_inequality_exits_1`.
- **`opened=True`** must be passed to `_open_input_file` for the RIGHT file when LEFT consumed stdin.
  If task 02 changes the file-opening logic, preserve this invariant or stdin reconfiguration will break.

## Open questions surfaced

- None — all OQs from the TDD were resolved during implementation or explicitly deferred to later tasks.
