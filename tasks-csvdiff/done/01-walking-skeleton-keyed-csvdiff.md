### Walking-skeleton `csvdiff`: keyed match, human output, full exit-code contract

**One-liner:** Ship a minimal end-to-end `csvdiff` that compares two CSVs by a single key column, renders the §8 human output, and implements the 0/1/2 exit-code contract across all four invocation styles.

**Composes:**
- New `csvkit/utilities/csvdiff.py` subclassing `CSVKitUtility` per the project's working agreement (`.claude/CLAUDE.md`), with `override_flags = ['f']` and a positional `input_paths` (`nargs='*'`, `default=['-']`) mirroring `csvjoin` — no custom `__init__`/`run()`.
- Argparse surface limited to: positional `LEFT RIGHT`, `-c/--key COL` (single column for this slice; composite handled in [[02-composite-key-and-duplicate-handling]]), `-y/--snifflimit`, `-I/--no-inference`, `--ignore COLS`. All other csvkit common flags inherited from `_init_common_parser`; none redefined (flag-collision audit per TDD §4a is honored).
- `main()` follows the validate → open → read → transform → write order: argparse-error on missing key column, stdin-used-twice, no-input-on-tty; agate `from_csv` for each input using `self.reader_kwargs` and `get_column_types()`; close files after read.
- Row-diff engine producing a `DiffResult` (per §4f) with stable ordering (removed in LEFT order, then changed in LEFT order, then added in RIGHT order) under typed-equality semantics by default and raw-string semantics under `-I`. `--ignore COLS` drops columns from the row comparison set (schema diff is added by [[04-schema-drift-detection]]).
- Human renderer matching the §8 grammar headline + per-row `~ + -` lines for this slice (composite-key formatting, the schema banner, and other renderer modes are added by later tasks).
- Exit-code contract: implicit 0 when no row differences; explicit `sys.exit(1)` when any row differences exist; `argparser.error(...)` (exit 2) for usage problems; **parse errors (`csv.Error`, `UnicodeDecodeError`, `agate.exceptions.CSVTestException`) are wrapped at the `from_csv` site and re-raised via `argparser.error` so they exit 2, not the uncaught-exception default of 1**. This is the single most important deviation from existing tools (TDD §4b edge case) and is tested explicitly.
- Registration line `csvdiff = "csvkit.utilities.csvdiff:launch_new_instance"` in `pyproject.toml [project.scripts]`, mirroring every existing tool.
- `epilog` text covering (a) the in-memory bound (mirrors csvjoin's precedent), (b) the typed-comparison semantics + `-I` escape, (c) the experimental status for the first release.

**TDD sections addressed:** §0 Design constraints, §3 High-level approach, §4a Command surface (foundation subset), §4b Exit codes, §4c STDIN/pipe behavior, §4d Memory & streaming, §4e Error reporting, §4f Data model, §4g Comparison semantics (typed default, `-I`, single-key resolution, `--ignore`), §4h `render_human` (subset), §6 Scalability, §7 Risks (parse-error→exit-2, memory bound, typed-comparison surprise, stdin double-use), §10 OQ3 (key formatting), §10 OQ8 (stdin reconfigure called twice).

**Depends on:** none.

**Acceptance criteria:**
- `csvdiff LEFT.csv RIGHT.csv -c id` produces the §8 human-format diff on stdout: a single headline `"<n> changed, <a> added, <r> removed (of <c> rows compared)"` followed by per-row lines, with deterministic ordering (removed in LEFT order, then changed in LEFT order, then added in RIGHT order).
- Single-column `-c` resolves through `match_column_identifier` so both column-name and 1-based-index forms work, matching csvjoin's `-c/--columns` precedent.
- Exit code is 0 when LEFT and RIGHT compare equal under typed semantics; 1 when any row difference is reported; 2 for: missing `-c` column on either side, malformed CSV in either input, both inputs given as `-`, interactive tty invocation with no piped input.
- All four invocation styles produce identical results on the same inputs: `csvdiff a.csv b.csv -c id`, `csvdiff a.csv - -c id < b.csv` (stdin = RIGHT), `csvdiff - b.csv -c id < a.csv` (stdin = LEFT), and `csvdiff b.csv -c id < a.csv` (one positional + redirected stdin → stdin is LEFT side per §4c).
- Parse failures (truncated quoting, invalid bytes for the chosen encoding, agate `CSVTestException`) exit **2** with stderr of the form `LEFT (<path>): <detail>` or `RIGHT (<path>): <detail>`, **not** the uncaught-exception default of exit 1.
- `-I/--no-inference` switches the comparison engine to raw-string semantics; the same input pair that compares equal by default (e.g. `1` vs `1.0`) compares unequal under `-I`.
- `--ignore col1,col2` excludes the named columns from the row-difference comparison; rows differing only in ignored columns are classified `unchanged`.
- A perf-smoke test (fixture-generated 200k-row × 10-col input) completes under a loose CI-friendly time bound (30 s) and produces the expected classification, demonstrating the §6 in-memory scale target.
- Key value formatting in the human output reads cleanly for ints, decimals, and dates (resolves §10 OQ3 with agate string-casting); a fixture covering each type is asserted.
- Tests in `tests/test_utilities/test_csvdiff.py` use `unittest` classes subclassing `CSVKitTestCase, EmptyFileTests`, include `test_launch_new_instance`, and cover every behavior above; fixtures live under `examples/` matching the existing `join_a.csv`-style naming.
- `flake8 .`, `isort . --check-only`, and `check-manifest` all pass; the full suite passes via `pytest --cov csvkit`.
