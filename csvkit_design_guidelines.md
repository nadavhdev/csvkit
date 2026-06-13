# csvkit — Design Guidelines for Adding a New Capability

> **Purpose.** This document is the rubric for shipping a new csvkit tool (or substantially extending an existing one). It is grounded in the patterns of `csvkit/cli.py`, `csvjoin.py`, `csvsort.py`, `csvclean.py`, `csvstack.py`, `csvcut.py`, `csvgrep.py`, `csvformat.py`, `csvlook.py`, `csvjson.py`, `csvpy.py`, and the shared infra (`tests/utils.py`, `pyproject.toml`, `.github/workflows/`, `docs/`, `man/`). When a guideline cites code, treat that file as the canonical example of the pattern.
>
> **How to use it.** During feature review, score each of the 10 dimensions in §3 as **PASS / PARTIAL / FAIL**, with a one-sentence rationale citing the specific file/line that backs the score. Then check the cross-cutting bars in §4 — these are pass/fail gates, not graded dimensions. The skill in `.claude/skills/csvkit-feature-review/` automates this and emits an HTML report.

---

## 1. Scope

A "capability" in csvkit is one of:

- **A new tool**: a new module under `csvkit/utilities/`, a new `[project.scripts]` entry, its own tests, docs, man page, and CHANGELOG entry. This is the primary case the guidelines target.
- **A material extension to an existing tool**: new flags, new sub-behavior, or new output format. The same dimensions apply, scoped to the surface that changed.

Bug fixes and refactors are out of scope unless they add user-visible behavior.

---

## 2. Canonical templates (pick the closest one and mirror it)

| If the tool…                                | Template            | Why                                                                          |
|---------------------------------------------|---------------------|------------------------------------------------------------------------------|
| Takes one CSV in, one out (transforms)      | `csvsort.py`        | Cleanest read-table-then-transform-then-write loop with `agate.Table.from_csv` |
| Takes one CSV, streams (no whole-file load) | `csvgrep.py`, `csvcut.py` | Uses `agate.csv.reader` + writer; no `Table` in memory                      |
| Takes two-plus CSVs                         | `csvjoin.py`        | `override_flags = ['f']`, positional `input_paths`, `isatty` guard, per-file open/read/close |
| Reformats output style only                 | `csvformat.py`      | `_extract_csv_writer_kwargs` overridden; output uppercase-letter flag space   |
| Renders non-CSV output (markdown, JSON)     | `csvlook.py`, `csvjson.py` | Writes to `self.output_file` directly, not via the CSV writer                 |
| Drops to a Python shell                     | `csvpy.py`          | Explicitly **rejects** stdin via `argparser.error`                            |
| Reports data conditions via exit code       | `csvclean.py`       | Uses `sys.exit(1)` when errors are found; documents the convention            |

**Rule:** if the closest template has it, you must do it the same way unless you can articulate a concrete reason to diverge.

---

## 3. The ten review dimensions

Each dimension is scored **PASS / PARTIAL / FAIL** with rationale and code citations.

---

### D1. Modeling

**What it covers.** Whether the feature is conceived in terms that fit csvkit: tables, rows, columns, typed cells, key columns. Whether the public contract (CLI surface + observable output) is precise and free of accidental complexity.

**How to check.**
- Read the tool's `description` and `epilog`. Can you describe what the tool does in one sentence using "row", "column", "cell"? If you need to invent new nouns, the modeling is leaking.
- Look at flag names and choice enums. Do they describe *what the user gets*, not *how it's implemented*?
- If the tool introduces a new equivalence/identity notion (e.g. "same row"), is it stated in the docs in user terms (e.g. "matched on key column(s)" — not "indexed by hash")?

**PASS.** The tool's mental model is a small extension of existing concepts; flags name user-facing outcomes; identity/equivalence notions are explicit.

**FAIL.** New domain vocabulary leaks into help text; flag names refer to internal data structures; user must read source to understand what "match" or "diff" means.

**References.** `csvjoin.py:11` (one-line description), `csvsort.py:20`, `csvclean.py:11`, `cli.py:122` (the `add_arguments` contract).

---

### D2. Package structuring

**What it covers.** Whether the new code lives where csvkit code lives, follows the naming conventions, and is discoverable.

**How to check.**
- The tool's module is at `csvkit/utilities/<command>.py` where `<command>` is the lowercase, single-word command name (no underscores, no hyphens).
- The class is `class CSV<Capitalized>(CSVKitUtility)` — for example `CSVSort`, `CSVJoin`.
- The module defines `launch_new_instance()` at the bottom and the `if __name__ == '__main__': launch_new_instance()` footer.
- Domain-shared helpers (used by more than one utility) live in **module-level files** under `csvkit/` (e.g. `csvkit/grep.py` for `FilteringCSVReader`, `csvkit/cleanup.py` for `RowChecker`) — *not* inside the utility module.
- Tests live at `tests/test_utilities/test_<command>.py`. Fixtures live at the top-level `examples/` directory (not under `tests/`).

**PASS.** All five locations check out. Helpers are in shared modules if reused, in the utility module if not.

**FAIL.** Module name doesn't match command; helpers buried in the utility module despite being reusable; tests not under `tests/test_utilities/`; fixtures in a non-standard place.

**References.** `csvkit/utilities/csvjoin.py`, `csvkit/grep.py` (shared helper extracted from csvgrep), `csvkit/cleanup.py` (shared helper extracted from csvclean), `tests/test_utilities/test_csvjoin.py`, `examples/join_a.csv`.

---

### D3. Component separation

**What it covers.** Whether the utility's `main()` honors the standard control-flow order, whether responsibilities are factored cleanly, and whether the file opening / argument parsing happens **only** in the base class.

**How to check.**
- `__init__` is NOT overridden. The base class `__init__` does common-arg setup, parsing, and exception-handler installation (`cli.py:77–120`).
- `run()` is NOT overridden. The base class `run()` opens `self.input_file`, calls `main()` inside `warnings.catch_warnings()`, and closes the file (`cli.py:130–149`).
- `main()` follows the **validate → open/read → transform → write** order, exactly like `csvjoin.py:45–118`:
  1. Argument-combination validation, with `self.argparser.error(...)` for any bad combo, *before* opening anything.
  2. Open input file(s) and read into agate; `close()` each file when done reading.
  3. Compute / transform.
  4. Emit to `self.output_file`.
- Long / reusable sub-logic is extracted into helper functions or a separate `csvkit/` module — not inlined into a 200-line `main()`.

**PASS.** Standard four-phase control flow; helpers extracted; no overriding of base lifecycle methods.

**PARTIAL.** Phases out of order (e.g. opens files before validating); helpers inline but module is small enough to be readable.

**FAIL.** `main()` interleaves reading and writing; validation happens after I/O; `__init__` or `run()` is overridden; significant sub-logic that could be reused is buried in the utility.

**References.** `csvjoin.py:45–118` (canonical four-phase flow), `csvclean.py:49–114`, `cli.py:130–149` (`run()` to mirror, never override).

---

### D4. Reuse

**What it covers.** Whether the new tool leverages everything the base class and shared modules already provide — or reinvents it.

**How to check.** Every item below that applies must use the existing facility.

- **Common arguments** — see §4.B: never redefine the inherited flags. If a flag doesn't apply, add its letter (or its long name fragment) to `override_flags`. Examples: `csvjoin` uses `['f']`; `csvcut`, `csvgrep`, `csvclean`, `csvstack`, `csvformat`, `csvlook` use `['L', 'I']` if they don't do type inference; `csvpy` uses `['l', 'zero', 'add-bom']`.
- **Column identifier resolution** — use `match_column_identifier(column_names, c, column_offset)` (`cli.py:487`) for a single column, or `parse_column_identifiers(ids, column_names, column_offset, excluded_columns)` (`cli.py:515`) for a list/range. Never write your own parser for `1,id,3-5`.
- **Reading input** — use the agate idiom from `csvjoin.py:75–82` / `csvsort.py:54–60`:
  ```python
  sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
  table = agate.Table.from_csv(
      f,
      skip_lines=self.args.skip_lines,
      sniff_limit=sniff_limit,
      column_types=self.get_column_types(),
      **self.reader_kwargs,
  )
  ```
  Use `agate.csv.reader(self.skip_lines(), **self.reader_kwargs)` for streaming (see `csvgrep.py:74`, `csvcut.py:47`).
- **Writing CSV output** — use `agate.csv.writer(self.output_file, **self.writer_kwargs)` (`csvcut.py:49`) or `table.to_csv(self.output_file, **self.writer_kwargs)` (`csvjoin.py:118`).
- **Opening files** — use `self._open_input_file(path)` (`cli.py:269`). Handles `.gz/.bz2/.xz/.zst` transparently.
- **stdin guard** — use `isatty(sys.stdin) and self.args.input_paths == ['-']` exactly like `csvjoin.py:46`.
- **Required-input guard** — single-input tools use `if self.additional_input_expected(): self.argparser.error(...)` (`csvlook.py:39`) or `sys.stderr.write(...)` if optional (`csvcut.py:44`).
- **Column-types / inference** — use `self.get_column_types()` (`cli.py:352`). Never construct an agate `TypeTester` directly.
- **Skip-lines** — use `self.skip_lines()` (`cli.py:396`) when streaming.
- **Exceptions** — raise `csvkit.exceptions.ColumnIdentifierError` or `RequiredHeaderError` from `csvkit/exceptions.py` (`csvkit/exceptions.py:19,39`). Don't invent new exception types unless modeling a genuinely new condition.

**PASS.** Every applicable facility is reused.

**PARTIAL.** Most facilities reused; one or two minor reinventions.

**FAIL.** Re-implements column resolution, redefines common args, builds its own type system, or opens files directly without `_open_input_file`.

**References.** `cli.py` lines cited above; `csvjoin.py:75–82`, `csvsort.py:54–60`, `csvcut.py:47–56`, `csvgrep.py:74–82`, `csvlook.py:50–58`.

---

### D5. Testing coverage

**What it covers.** Whether tests follow the suite's testing conventions and cover happy/error/edge surfaces.

**How to check.**
- File at `tests/test_utilities/test_<command>.py`, uses **`unittest`** (classes, not bare pytest), no top-level test functions (`tests/test_utilities/test_csvjoin.py`).
- Subclasses `CSVKitTestCase` (always) and `EmptyFileTests` (always) — and `ColumnsTests` / `NamesTests` where applicable (`tests/utils.py:48,106,113,133`).
- Class attribute `Utility = MyToolClass`.
- Class attribute `default_args` set such that `EmptyFileTests.test_empty` can `utility.run()` without crashing (`tests/utils.py:106`).
- Includes `test_launch_new_instance` that patches `sys.argv` and calls `launch_new_instance()` (every existing test file has this — `test_csvjoin.py:14`, `test_csvsort.py:12`).
- Uses the base helpers — `get_output`, `get_output_as_io`, `get_output_as_list`, `get_output_as_reader`, `assertRows`, `assertLines`, `assertError`, `stdin_as_string` — and does **not** hand-roll stdout capture (`tests/utils.py:51–101`).
- Coverage of:
  - Every "happy" code path of every flag.
  - Every error path that calls `argparser.error`, tested via `assertError(launch_new_instance, options, expected_message_suffix)` (`tests/utils.py:71`).
  - STDIN input via `stdin_as_string(io.BytesIO(b'...'))` (`tests/utils.py:40`).
  - The empty-file case (via the mixin).
  - For multi-file tools: at least one piped/file mix.
- Fixtures added to `examples/` (top-level), named like the existing ones: `<topic>_<variant>.csv` (e.g. `join_a.csv`, `sort_ints_nulls.csv`). Existing fixtures (`dummy.csv`, `blanks.csv`, `empty.csv`, `no_header_row.csv`) are reused where applicable.
- Full suite passes locally: `pytest --cov csvkit`.
- Module-level coverage ≥ 90% (csvkit's existing tools average 93–99%).

**PASS.** All bullet points hold; coverage ≥ 90%.

**PARTIAL.** All structural conventions hold, but one or two behavior cases (e.g. an edge case, a STDIN test) are missing.

**FAIL.** Hand-rolled stdout capture; missing `test_launch_new_instance`; missing `EmptyFileTests`; coverage < 80%; fixtures placed under `tests/` instead of `examples/`.

**References.** `tests/test_utilities/test_csvjoin.py`, `tests/test_utilities/test_csvsort.py`, `tests/test_utilities/test_csvclean.py`, `tests/utils.py`.

---

### D6. Observability

**What it covers.** Whether the tool produces clear, parseable diagnostics, respects stderr discipline, and gives the user a way to dig deeper.

**How to check.**
- **Stderr discipline.** All informational messages, warnings, and error messages go to `sys.stderr` (via `sys.stderr.write(...)`) or to `self.error_file` (set by `__init__` for tests). `stdout` is reserved for the tool's actual output (`csvjoin.py` writes only CSV; `csvclean.py:101–112` writes errors to a separate `self.error_file`).
- **No tracebacks by default.** Inherited from the base class via `_install_exception_handler` (`cli.py:332–350`): uncaught exceptions print a one-line `ExceptionName: message`. The user gets the full traceback only with `-v/--verbose`. Tools should not install their own excepthook.
- **Usage errors go through `argparser.error`.** This prints `<command>: error: <message>` and exits 2 (`tests/utils.py:71–84` asserts this contract). Validation errors caught manually must call `self.argparser.error(...)`, not `sys.exit()` directly.
- **Helpful warning when reading from STDIN with no piped data.** Tools that block on STDIN should emit `sys.stderr.write('No input file or piped data provided. Waiting for standard input:\n')` (`csvclean.py:51`, `csvcut.py:45`, `csvgrep.py:47`, `csvformat.py:73`, `csvstack.py:45`).
- **Progress reporting.** csvkit's convention is **no progress noise** — no spinners, no row counters, no ETA. If your tool deviates (e.g. for genuinely long-running operations), it must be an opt-in flag, with the default being silent.
- **Error messages are user-actionable.** They name the offending column, file, value, or flag — not just "error".

**PASS.** Stderr discipline holds; `-v` works; usage errors via `argparser.error`; messages are specific.

**FAIL.** Status messages on stdout; tracebacks printed without `-v`; ad-hoc `sys.exit()` for usage errors; progress noise by default.

**References.** `cli.py:332–350`, `csvclean.py:51,101–112`, `tests/utils.py:71–84`.

---

### D7. CLI & flag discipline

**What it covers.** Whether the tool's command-line surface fits the suite's conventions, doesn't shadow inherited flags, doesn't collide with cousin tools, and has clear help text.

**How to check.**
- **Inherited flags untouched.** The common set (see §4.B) is never redefined. If a flag doesn't apply, it goes into `override_flags`.
- **No collisions with sibling tools.** Cross-check against `csvjoin`'s `-c`, `csvcut`'s `-c`/`-C`/`-x`, `csvgrep`'s `-c`/`-m`/`-r`/`-f`/`-i`/`-a`, `csvsort`'s `-c`/`-r`/`-i`, `csvstack`'s `-g`/`-n`/`--filenames`, `csvjson`'s `-i`/`-k`/`--lat`/`--lon`/`--type`/`--geometry`/`--crs`/`--no-bbox`/`--stream`, `csvformat`'s upper-case output-side flags `-D`/`-T`/`-A`/`-Q`/`-U`/`-B`/`-P`/`-M`/`-E`. If a similar concept exists in a sibling tool, the new tool uses the same letter.
- **Suite-consistent semantics.** `-c` is always a column-list selector. `-n` is always "list column names and exit". `-y/--snifflimit` is always the sniff limit. `-I/--no-inference` is always to disable type inference. `-r` is reverse (csvsort) or regex (csvgrep) — be careful here.
- **Help text quality.** Every `add_argument(...)` has a non-empty, complete-sentence `help=`. Choice enums state the choices in the help string. Defaults are documented when non-obvious (`csvjoin.py:38` documents the `-y` default; `csvsort.py:38` does the same).
- **Long-form flags.** Multi-word flags use hyphens, never underscores (`--null-value`, not `--null_value`).
- **`-h/--help` and `-V/--version`** work and produce sensible output. (These are inherited automatically.)
- **`--help` matches reality.** All advertised flags actually do something.

**PASS.** No collisions; suite-consistent letter choices; clean help text; long-form hyphenation correct.

**PARTIAL.** Minor collision avoided but flag choice surprises readers (e.g. uses `-k` for something that isn't a key).

**FAIL.** Redefines an inherited flag; reuses a sibling-tool flag with different semantics; missing or copy-pasted help strings; cryptic enum values.

**References.** `cli.py:159–267` (the inherited set), every utility module's `add_arguments`, `docs/common_arguments.rst`.

---

### D8. Error model & exit codes

**What it covers.** The tool's exit-code contract and its use of csvkit's exception types.

**How to check.**
- **Exit 2 for usage errors.** Every usage error goes through `self.argparser.error(...)`, which exits 2 (Python argparse default). Tested with `tests/utils.py:assertError` which asserts `e.exception.code == 2`.
- **Exit 0 for normal completion.** Reached by `main()` returning normally; no explicit `sys.exit(0)` needed.
- **csvkit's exception hierarchy is used** where applicable:
  - `ColumnIdentifierError` (`exceptions.py:19`) — raised when a user-supplied column name/index is invalid. Used by `match_column_identifier` and `parse_column_identifiers` automatically.
  - `RequiredHeaderError` (`exceptions.py:39`) — when an operation needs a header row but the file has none.
  - `InvalidValueForTypeException` (`exceptions.py:26`) — when a value can't be coerced.
- **New exit codes for data conditions are disclosed.** csvkit has **no existing convention** for "a data condition was found" exit codes. csvclean broke ground with `sys.exit(1)` on errors (`csvclean.py:114`). If a new tool needs one, the convention is:
  1. Document the code in the tool's `epilog`.
  2. Document it in `docs/scripts/<tool>.rst`.
  3. Don't collide with 2 (already used by argparse).
  4. Tests assert the exact code.
- **Domain exceptions caught and re-routed.** `ColumnIdentifierError` from key/column-name resolution should be caught and routed via `argparser.error` so the user sees a clean message (exit 2), not a propagated exception (exit 1).

**PASS.** Usage errors via `argparser.error` (exit 2); existing exception types used; any new exit code disclosed in `epilog` + `docs/`.

**PARTIAL.** Mostly correct; one error path that should go through `argparser.error` instead bubbles up a domain exception.

**FAIL.** Bare `sys.exit(2)` or `sys.exit(1)` calls scattered through `main()`; new exit code introduced silently; column-identifier errors leak as tracebacks.

**References.** `csvkit/exceptions.py`, `csvclean.py:114` (precedent for exit 1), `tests/utils.py:71–84` (assertError contract).

---

### D9. Data semantics

**What it covers.** Whether the tool understands typed-vs-string equality, null/blank handling, dates, locales — the layer where most subtle CSV bugs live.

**How to check.**
- **Type inference awareness.** agate infers types by default (`cli.py:352`). A tool that compares cells must know that `1` and `1.0` compare *equal* under default inference, and the tool's documentation must say so.
- **`-I/--no-inference` honored.** If the tool reads typed data (uses `self.get_column_types()`), it must accept `-I/--no-inference` and the flag must actually disable inference. The flag is declared per-tool (not in the common set); see `csvsort.py:41`, `csvjoin.py:42`, `csvjson.py:53`, `csvlook.py:33`, `csvpy.py:30`. Tools that don't read typed data add `'I'` to `override_flags` (`csvclean.py:13`, `csvcut.py:21`, `csvgrep.py:15`, `csvstack.py:26`, `csvformat.py:12`).
- **Blanks / null-value flags respected.** `--blanks` (`cli.py:218`) and `--null-value` (`cli.py:221`) feed into `self.get_column_types()`. A tool that reads through `agate.Table.from_csv` with `column_types=self.get_column_types()` inherits this automatically; a tool that builds its own type tester must reconstruct it.
- **`--date-format`, `--datetime-format`, `--no-leading-zeroes`** all honored via `self.get_column_types()`.
- **`--locale`** honored for number parsing.
- **Sniff-limit honored.** Tools that read CSV must support `-y/--snifflimit` with default 1024, semantics `-1 → None → sniff entire file`, `0 → no sniffing` (`csvjoin.py:36–39`, `csvsort.py:36–39`).
- **Output stays in the inferred-or-not-inferred posture.** A tool that reads typed data and re-emits CSV should round-trip the typed representation (agate's `to_csv` does this). A tool that does its own formatting must document any normalization (e.g. dates → ISO).

**PASS.** All inherited type-handling flags propagate correctly; `-I` behavior is documented; sniff-limit is plumbed.

**PARTIAL.** `-I` accepted but the tool's docs don't tell the user what changes; sniff-limit accepted but with a non-standard default.

**FAIL.** Tool builds its own type tester; ignores `--blanks` / `--null-value` / `--date-format`; treats `1 == 1.0` differently from the rest of the suite without explanation.

**References.** `cli.py:352–389` (the type-tester factory), `csvjoin.py:36–43`, `csvsort.py:36–43`.

---

### D10. Documentation & registration completeness

**What it covers.** The "definition of done" gates: the tool must be discoverable through every documented surface, installed as a console script, and listed in the changelog.

**How to check.**
- **`[project.scripts]` entry in `pyproject.toml`** — `csvname = "csvkit.utilities.csvname:launch_new_instance"`. Tested by `pip install -e .[test]` followed by `which csvname`.
- **Per-tool docs page** at `docs/scripts/<command>.rst`, matching the structure of `docs/scripts/csvjoin.rst`: title, Description (with one-line summary and usage block in `.. code-block:: none`), `See also: :doc:\`../common_arguments\``, Examples section with bash code blocks.
- **Linked in `docs/cli.rst`** in the appropriate section (Input / Processing / Output and Analysis), alphabetically ordered.
- **Man page** at `man/<command>.1`, registered in `pyproject.toml` `[tool.setuptools.data-files]` under `"share/man/man1"`. If you skip the man page, `check-manifest` must still pass.
- **CHANGELOG entry** at the **top** of `CHANGELOG.rst` in the existing style: `-  feat: :doc:\`/scripts/<command>\`. <short description>.`
- **AUTHORS** — new contributors added to `AUTHORS.rst` if appropriate.
- **`epilog` discloses tradeoffs.** Anything the user must know to use the tool safely — memory bound, exit codes if non-standard, type-comparison semantics — is in the `epilog` (which appears at the bottom of `--help`). csvjoin's epilog is the precedent: `"Note that the join operation requires reading all files into memory."` (`csvjoin.py:12`).
- **CI stdin/pipe smoke tests updated.** `.github/workflows/ci.yml` runs `cmd < examples/dummy.csv` and `printf 'a,b,c\n1,2,3' | cmd` for every existing tool (with documented exception for csvpy). New tools should be added to those lists.

**PASS.** All bullet points hold; the new tool is reachable from `--help`, `docs/cli.rst`, `man -l`, and CHANGELOG.

**PARTIAL.** Missing one of: cli.rst link, man page, CHANGELOG entry, AUTHORS update. (Each is a quick fix.)

**FAIL.** Tool isn't registered (not installable as a CLI), no rst docs, no CHANGELOG entry.

**References.** `pyproject.toml` `[project.scripts]` (line 55–69) and `[tool.setuptools.data-files]` (line 74–90), `docs/scripts/csvjoin.rst`, `docs/cli.rst:5–48`, `CHANGELOG.rst:1–7`, `.github/workflows/ci.yml` stdin/pipe sections.

---

## 4. Cross-cutting bars (pass/fail gates, not graded dimensions)

These are minimum bars. Failing any of them blocks the feature regardless of how well the 10 dimensions score.

### A. The control-flow contract

`main()` follows **validate → open/read → transform → write**. `__init__` and `run()` are *never* overridden. `main()` is the only method you write that does I/O. Nothing is opened or read before all arguments are validated.

### B. The inherited common-args set (untouchable)

These come from `cli.py:_init_common_parser` (`cli.py:159–267`) and **must not be redefined**:

```
-d/--delimiter   -t/--tabs           -q/--quotechar    -u/--quoting
-b/--no-doublequote                  -p/--escapechar   -z/--maxfieldsize
-e/--encoding    -L/--locale         -S/--skipinitialspace
--blanks         --null-value        --date-format     --datetime-format
--no-leading-zeroes                  -H/--no-header-row                -K/--skip-lines
-v/--verbose     -l/--linenumbers    --add-bom         --zero
-V/--version
```

To suppress one in a particular tool, add its single-letter or multi-character key to `override_flags`. Examples: `['f']` (csvjoin), `['L', 'I']` (csvcut, csvgrep), `['l', 'zero', 'add-bom']` (csvpy).

### C. STDIN/pipe support

Every tool must work invoked as `tool < file` and `printf '…' | tool`. This is enforced by smoke tests in `.github/workflows/ci.yml` for every existing tool. The new tool must be added to those smoke tests. The only documented exception is `csvpy`, which explicitly errors when stdin is used.

### D. Memory disclosure

If the tool holds whole files in memory (necessary for some operations: sort, join, stat), the `epilog` says so explicitly — using csvjoin's wording as precedent: *"Note that the join operation requires reading all files into memory. Don't try this on very large files."*

### E. Determinism

Same input → byte-identical output. No dict-order leakage in output, no timestamps, no temp-path leakage. Tested by running the tool twice and `diff`-ing.

### F. Backwards compatibility

No public CLI of an existing tool changes. No behavior change of an existing tool. New tools may add fixtures to `examples/`, but must not modify existing ones.

### G. Dependency hygiene

No new runtime dependency unless it is a *small* pure-Python library and there is a clear need that can't be met by agate + the standard library. Test-only deps go under `[project.optional-dependencies].test`.

### H. Cross-platform & Python-version compatibility

CI runs on macOS, Windows, Ubuntu × Python 3.10–3.14 + pypy-3.11 (`.github/workflows/ci.yml:6–11`). Code must avoid platform-specific assumptions: use `os.path` not hardcoded separators, write UTF-8 with `PYTHONUTF8=1` honored, don't rely on bash-specific shell behavior in tests.

### I. Lint & format gates

`flake8 .` clean (max-line-length 119, `setup.cfg`). `isort . --check-only` clean (line-length 119, `pyproject.toml [tool.isort]`). `check-manifest` clean. CI's Lint workflow runs all three.

---

## 5. The review rubric (the table the HTML report renders)

For each dimension D1–D10, the reviewer assigns:

| Score    | Meaning                                                            |
|----------|--------------------------------------------------------------------|
| **PASS** | Every "How to check" bullet is satisfied.                          |
| **PARTIAL** | Most bullets satisfied; one or two minor gaps with low risk.    |
| **FAIL** | At least one "FAIL signal" listed under the dimension is present.  |
| **N/A**  | The dimension does not apply (rare; must be justified in rationale). |

Each score carries a **one-to-three-sentence rationale** that names the specific code path / file / line that backs the score.

For each cross-cutting bar A–I: **PASS** or **FAIL** with one sentence.

The HTML report renders:

1. Overall grade — derived: `FAIL` if any dimension is FAIL or any cross-cutting bar fails; `PARTIAL` if any dimension is PARTIAL; otherwise `PASS`.
2. Summary cards (count of PASS / PARTIAL / FAIL across dimensions).
3. Dimension panels (one per D1–D10) with score pill, rationale, and citation list.
4. Cross-cutting bars panel.
5. Top recommendations — the actionable fixes, sorted by severity.

---

## 6. Process notes

- The review is **black-box-friendly** up to a point: most dimensions can be scored from reading the utility module, the test file, the docs, and `pyproject.toml`. D9 and D3 sometimes require following call chains into `cli.py`.
- The review should produce **actionable** findings. "D5 PARTIAL" with no rationale is useless; "D5 PARTIAL — no STDIN test for the second-file path (compare to `test_csvjoin.py:96` which tests `--no-header-row` over stdin)" is reviewable.
- A reviewer who finds themselves *guessing* at expected behavior should mark the dimension PARTIAL and note the ambiguity rather than picking a side; that signal flows back to documentation gaps.
