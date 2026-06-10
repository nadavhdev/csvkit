## TDD: `csvdiff` — CSV-aware comparison tool for csvkit

**Author:** Tech lead (on behalf of @nhoze)
**Status:** Draft
**Date:** 2026-06-10
**Related PRD:** https://github.com/nadavhdev/ai-session/blob/main/PRD-csvdiff.md

---

## 0. Design constraints from project conventions

Source: `.claude/CLAUDE.md` ("csvkit — working agreement"), `csvkit/cli.py`,
`csvkit/utilities/csvjoin.py` as the closest existing template (two-input tool).
These are non-negotiable; the rest of the design slots inside them.

- **One tool = one command = one module.** `csvdiff` lives at
  `csvkit/utilities/csvdiff.py`, subclasses `CSVKitUtility`, implements
  `add_arguments()` and `main()` only. No custom `__init__` / `run()`.
- **Two-input pattern.** Use `csvjoin`'s shape verbatim:
  - `override_flags = ['f']`
  - positional `input_paths` (`nargs='*'`, `default=['-']`)
  - guard `if isatty(sys.stdin) and self.args.input_paths == ['-']` and
    `argparser.error(...)` with a useful message.
- **Inherited common flags are off limits.** `-d -t -q -u -b -p -z -e -L -S -H
  -K -v -l --blanks --null-value --date-format --datetime-format
  --no-leading-zeroes --add-bom --zero -V` are provided by
  `_init_common_parser()`. `csvdiff` MUST NOT redefine any of these. In
  particular, csvjoin's `-c/--columns` precedent means we cannot reuse `-c` for
  anything else; we use `-c` for the key, same letter, same semantics.
- **Standard agate read idiom.** Read each file via `agate.Table.from_csv(f,
  skip_lines=..., sniff_limit=..., column_types=self.get_column_types(),
  **self.reader_kwargs)`. Close each file after read. Use
  `match_column_identifier` to resolve user-supplied column names/indices.
- **Type inference is on by default; `-I/--no-inference` opts out.** Resolves
  PRD OD4: comparison happens on agate-typed values by default (so `1` == `1.0`
  and `"5.00"` == `5.0` as numbers); raw-string comparison is available via the
  inherited `-I` flag. **This deviates from a naive byte-for-byte diff and the
  user-visible help text MUST say so** in `epilog`.
- **Validate → read → transform → write,** in that order, inside `main()`. No
  work before validation; no interleaving read/write.
- **STDIN/pipe parity is CI-tested for every tool** (`tool < f` and
  `printf … | tool`). Both invocation styles must work for csvdiff too — see
  §4c.
- **New exit code for "differences found" is flagged as a new pattern.** csvkit
  tools today only emit 0 (success) and 2 (argparse usage). FR7 requires a third
  bucket. Per CLAUDE.md, this must be **explicit via `sys.exit(code)`**, not
  silent, and documented in `epilog` + the rst doc page. See §4b.
- **Definition of done** (CLAUDE.md "PR checklist") binds this work: registered
  in `pyproject.toml [project.scripts]`, tests in `tests/test_utilities/`
  mirroring `EmptyFileTests` + `CSVKitTestCase`, fixtures under `examples/`,
  per-tool rst doc at `docs/scripts/csvdiff.rst` (modeled on
  `docs/scripts/csvjoin.rst`), `CHANGELOG.rst` entry, `AUTHORS.rst` update,
  `flake8 .` clean, `isort . --check-only` clean, `check-manifest` clean,
  `pytest --cov csvkit` green across Python 3.10–3.14 + pypy-3.11 on
  macOS/Windows/Linux.
- **No new heavyweight runtime dep.** Build on agate + stdlib. The JSONL
  serializer uses stdlib `json` with `csvkit.cli.default_str_decimal` for
  Decimal/date handling (already in cli.py, used by csvjson).
- **Python 3.10+ only.** Match-statements and PEP 604 union types are fine.

---

## 1. Problem & context

csvkit ships every CSV verb the data-CLI workflow needs — join, sort, filter,
stat, format — except *compare*. Users currently fall back to `diff`/`git diff`
(line-oriented, noisy on re-sort and quoting changes, hides which field moved
inside a row), spreadsheet compare features (GUI, manual, doesn't scale), or
bespoke pandas scripts (everyone rewrites the same brittle merge-and-compare,
no standard output, no CLI). `csvdiff` closes the gap with a CSV-aware,
record/field-level comparison that matches the rest of the suite's idioms.

Consumers: data journalists (monthly dataset deltas), data engineers (CI gate
on transformation output), analysts (catch silent schema drift before it
corrupts downstream joins).

Why now: csvkit just shipped a recent minor; an experimental release of
`csvdiff` slots into the next release cycle without disrupting any existing
tool's surface.

---

## 2. Scope

**In scope (this TDD, GA target):**
- New `csvdiff` tool comparing exactly two CSV files.
- Row classification: added / removed / changed / unchanged.
- Field-level deltas inside changed rows.
- Key-based matching (`-c/--key`, one or more columns).
- Positional row-by-row fallback when no key is given (PRD OD1 resolution).
- Schema-drift detection (columns added / removed / reordered) reported
  distinctly from row diffs.
- Exit-code contract: 0 / 1 / 2.
- Default human-readable output (PRD §8 visual grammar).
- `--format json` → JSONL one-event-per-line (PRD OD-JSONL resolution).
- `--quiet` (suppress output, exit code only) and `--summary-only`.
- Full inheritance of csvkit common flags (encoding, delimiter, quoting,
  header, locale, type inference, etc.).

**Out of scope (this TDD):**
- N-way diff (3+ files). Not in PRD. The interface is left extensible
  (positional `input_paths`) but the code path errors if `len != 2`.
- Patch generation ("apply this diff to file A to get file B"). Not in PRD.
- Fuzzy / similarity matching of changed rows (e.g. "this added row looks like
  that removed one"). Not in PRD; would change the matching model materially.
- Streaming/external-sort backend for files that don't fit in memory — see
  §4d for the in-memory bound and §10/OQ4 for the follow-up question.
- Color / TTY-aware highlighting. Defer; csvkit tools today don't colorize.

---

## 3. High-level approach

`csvdiff` is a single-process, in-memory tool. `main()` validates args, opens
both inputs (file or stdin, lazily, with the common reader kwargs), reads each
into an `agate.Table` with type inference applied via `get_column_types()`,
compares the schemas, builds an index keyed by the user's `--key` columns on
each side (or a positional index when no key is given), walks the union of
keys to classify rows, computes per-field deltas for changed rows on the
intersection of columns, then renders to `self.output_file` in the requested
format. Exit code is chosen at the end: 0 if no row or schema differences,
1 if any, 2 for usage errors (raised via `argparser.error`, which already
exits 2).

```
   left.csv                right.csv
       |                       |
       v                       v
  +---------+            +---------+
  | agate   |            | agate   |       (typed columns,
  | Table L |            | Table R |        same reader kwargs)
  +---------+            +---------+
       \                     /
        \                   /
         v                 v
       +---------------------+
       | schema_diff(L, R)   |---> SchemaDelta
       +---------------------+
                |
                v
       +---------------------+
       | key index L,        |
       | key index R         |     dict[key_tuple] -> row_idx
       +---------------------+
                |
                v
       +---------------------+
       | classify_rows()     |---> added[], removed[], changed[]
       +---------------------+      per common column set
                |
                v
       +---------------------+
       | renderer (human |   |
       | JSONL | summary)    |---> self.output_file
       +---------------------+
                |
                v
            sys.exit(0|1)        2 already used for argparse errors
```

---

## 4. Detailed design

### 4a. Command surface

```
usage: csvdiff [OPTIONS] LEFT RIGHT

Compare two CSV files semantically (record/field, not line).

positional arguments:
  LEFT, RIGHT       The two CSV files to compare. Use "-" for STDIN
                    (at most once).

csvdiff options:
  -c, --key COLS    Column name(s) or index(es) identifying a row.
                    Comma-separated for a composite key
                    (e.g. -c "order_id,line_no"). When omitted,
                    csvdiff compares row-by-row positionally
                    (see "no --key" section in help).
  --on-dup {error,first,all}
                    Behavior when --key is not unique within a file.
                    'error' (default): fail with exit 2.
                    'first': keep the first occurrence, ignore the rest.
                    'all':   compare the Cartesian product of duplicates
                             (warning: O(n*m) per key).
  -f, --format {human,jsonl,summary}
                    Output format. 'human' (default) is the §8 layout.
                    'jsonl' emits one JSON object per change.
                    'summary' prints only the headline counts.
  --no-schema-check Skip the schema-drift section; treat extra/missing
                    columns silently (compare on the column intersection).
  --ignore COLS     Columns to ignore when comparing rows (still shown
                    in schema diff). Repeatable / comma-separated.
  -q, --quiet       Suppress all output. Exit code only.

  -y, --snifflimit BYTES   (same as csvjoin)
  -I, --no-inference       Compare as raw strings (no agate typing).

inherited:
  -d -t -q -u -b -p -z -e -L -S -H -K --blanks --null-value
  --date-format --datetime-format --no-leading-zeroes -v --add-bom
  --zero -V

exit codes:
  0   files are equivalent
  1   one or more differences (row or schema)
  2   usage error (bad args, missing key column, duplicate key with
      --on-dup=error, malformed CSV)

Note: csvdiff reads both inputs fully into memory; do not run it on files
that don't fit. With type inference (default), "1" and "1.0" compare equal;
use -I to compare raw strings.
```

**Flag-collision audit.** Walked the full inherited list in `cli.py`:
- `-c` is the key column. Matches csvjoin's `-c/--columns` semantics
  (column names or indices, comma-separated). Intentional cross-tool
  consistency — NFR1.
- `-f` for `--format` — **conflict risk**. There is no `-f` in the common
  parser (it's reserved for the file flag, which we already `override_flags
  = ['f']`), so the letter is free. Confirmed safe.
- `-q`: collides with the inherited `-q/--quotechar`. **Resolved by
  dropping the short form** — `--quiet` only. Documented in help.
- `-y`: matches csvjoin's `-y/--snifflimit`. Same name on purpose.
- All other inherited single-letter flags untouched.

**Input source matrix:**

| LEFT | RIGHT | Behavior |
|------|-------|----------|
| file | file  | open both via `_open_input_file` |
| file | `-`   | RIGHT reads stdin (reconfigured to args.encoding) |
| `-`  | file  | LEFT reads stdin |
| `-`  | `-`   | error: stdin can serve only one side |
| missing both / interactive tty + no piped data | — | error: "Provide two input files, or one file plus piped data on stdin." |

This mirrors csvjoin's `_open_input_file` + isatty guard, extended with the
"stdin used twice" check (csvjoin allows it because joining the same stdin
twice degenerates harmlessly; for a diff it would silently report "no
differences" against an empty/exhausted second read — actively misleading).

**Help / epilog.** The `epilog` MUST state two things explicitly:
1. The whole-file in-memory bound (mirroring csvjoin's epilog).
2. The typed-comparison behavior (`1` ≡ `1.0`) and the `-I` escape hatch.

### 4b. Exit codes

| code | meaning | mechanism |
|------|---------|-----------|
| 0 | files equivalent (zero row diffs AND zero schema diffs) | implicit return |
| 1 | differences found (row diffs OR schema diffs) | explicit `sys.exit(1)` |
| 2 | usage error: missing/invalid key column, duplicate key with `--on-dup=error`, stdin used twice, malformed CSV at parse time, `ColumnIdentifierError` | `argparser.error(...)` for arg validation; raised exception for parse failures (csvkit's installed excepthook prints to stderr; argparse exits 2; uncaught exceptions exit 1 — see "edge case" below) |

**This is a new pattern for csvkit.** Per CLAUDE.md, it's flagged explicitly
here. The mapping mirrors GNU `diff(1)` (0=same, 1=different, 2=error), which
is the strongest precedent in the broader CLI world and avoids surprise.

**Edge case — parse error vs. data diff.** A `csv.Error` / agate parsing
exception raised during `from_csv` is not "differences" — it's "could not
read". The current `_install_exception_handler` would let it surface as exit
1 (uncaught), which collides with our "differences found" code. **Fix:** wrap
the `agate.Table.from_csv` calls in a try/except for `csv.Error`,
`UnicodeDecodeError`, `agate.exceptions.CSVTestException`, and re-raise via
`argparser.error('LEFT: <message>')` so they exit 2. This is the single most
important deviation from existing tools and MUST be tested.

**`--quiet`** still exits 0/1/2 — same code, no stdout/stderr (errors still
go to stderr; only the diff body is suppressed).

### 4c. STDIN / pipe behavior

- `csvdiff a.csv b.csv` — both files.
- `csvdiff a.csv -` — `-` is stdin for RIGHT.
- `csvdiff - b.csv` — `-` is stdin for LEFT.
- `printf '...' | csvdiff - b.csv` — same.
- `csvdiff < a.csv b.csv` — shell redirects stdin to a.csv; argv has only
  `b.csv`. **This is the trickiest case.** csvjoin handles it via
  `default=['-']`: if you give 1 path, the positional list is `['b.csv']` and
  it doesn't read stdin at all. For csvdiff we need exactly 2 inputs. **Rule:**
  if exactly 1 path is given and stdin is not a tty, treat as `('-', given)`
  (the redirected stdin is the LEFT side). If exactly 1 path is given and
  stdin IS a tty, error with the "two inputs" message. Document this in help.
- Interactive tty + zero paths: `argparser.error("Provide two input files, or
  one file plus piped data on stdin.")` — exit 2. Mirrors csvjoin's guard.

CI must cover all four invocation styles (named/named, named/pipe, pipe/named,
redirect+named).

### 4d. Memory & streaming

**Bounded by `2 × max(file_a, file_b)` in agate's in-memory row representation
plus two `dict[key_tuple] → int]` indices.** Stated explicitly in `epilog` per
csvjoin's precedent.

- Both tables are fully materialised via `agate.Table.from_csv`. This is
  required to (a) compute the column-set diff, (b) build the key index, (c)
  honor type inference (which scans the full column).
- No streaming alternative is offered in v1. Files in the "hundreds of
  thousands of rows" PRD scale comfortably fit in memory (a 500k-row × 20-col
  CSV at typical sizes is ~100 MB raw, ~3–5× that in typed Python objects —
  well under 1 GB). Files significantly larger than that should be handled
  by sorting upstream and using a streaming merge — listed as OQ4.
- The key index is a `dict[tuple, int]` (or `dict[tuple, list[int]]` when
  `--on-dup=all`). Memory is `O(rows)` per side.

### 4e. Error reporting

- All errors go to stderr. Stdout carries only diff output.
- Argparse-style usage errors (missing key column, duplicate-key with default
  `error`, stdin used twice) → `argparser.error('<message>')` → exit 2.
- Parse errors get the file name prefixed: `argparser.error('LEFT
  (orders_jan.csv): CSV parse error at line 4203: <detail>')`.
- `ColumnIdentifierError` and `RequiredHeaderError` from `csvkit.exceptions`
  are raised where they fit and caught by csvkit's installed excepthook,
  which prints `'<ExceptionName>: <message>'`. Verify by test that they exit
  with code 1 (uncaught) — and if FR7 requires they exit 2 instead, catch and
  re-raise via `argparser.error`. **Decision:** treat
  `ColumnIdentifierError` (the user named a column that doesn't exist) as a
  usage error → catch it and route through `argparser.error` → exit 2. This
  is consistent with the "usage error" bucket and avoids ambiguity with "1 =
  differences".

### 4f. Data model

**`SchemaDelta`** (dataclass):
- `added: list[str]` — columns in RIGHT not in LEFT (in RIGHT's order)
- `removed: list[str]` — columns in LEFT not in RIGHT (in LEFT's order)
- `reordered: bool` — common columns appear in a different order
- `common: list[str]` — common columns, in LEFT's order (used for row diff)

**`RowDelta`** (dataclass):
- `status: Literal['added','removed','changed']`
- `key: tuple[Any, ...]` — the key tuple (positional index for no-key mode)
- `fields: dict[str, tuple[Any, Any]]` — `{col: (left_value, right_value)}`
  for `'changed'`; for `'added'`/`'removed'`, the whole row keyed by column
  name with the missing side as `None`

**`DiffResult`** (dataclass):
- `schema: SchemaDelta`
- `row_diffs: list[RowDelta]` — in stable order: schema events implicit,
  then **removed** in LEFT order, then **changed** in LEFT order, then
  **added** in RIGHT order. (Deterministic per NFR3.)
- `unchanged_count: int`
- `compared_count: int`

The renderer (`render_human`, `render_jsonl`, `render_summary`) takes a
`DiffResult` + the file handle and produces output. This separation lets us
unit-test the diff engine independently of the renderer.

### 4g. Comparison semantics

- **Typed by default** (agate inference). `1` == `1.0`; `"true"` ==
  `"True"` parsed as Boolean; whitespace-only difference inside a number
  collapses. Documented in `epilog`. Override with `-I` for raw-string
  comparison.
- **Null handling.** Inherited `--blanks`, `--null-value`, and the type
  inference rules apply. `NULL` == `NULL`. A typed `None` is distinct from
  the string `"null"` unless inferred.
- **Key resolution.** `--key` is parsed identically to csvjoin's
  `--columns` (comma-separated names or 1-based indices, resolved via
  `match_column_identifier`). **The key must exist in BOTH files** (and
  reference the same logical column) — if either side is missing the named
  key column we exit 2.
- **Composite key.** `(value1, value2, …)` tuple. Order matters for index;
  order does not matter for matching (the same column list is applied to
  both sides).
- **Duplicate key behavior** (resolves PRD OD2 via the
  `--on-dup={error,first,all}` flag introduced above).
- **No-key mode (PRD OD1).** When `-c` is absent, `csvdiff` compares row
  N of LEFT to row N of RIGHT (positional). If the row counts differ, the
  surplus rows on the longer side are reported as `added` (if RIGHT longer)
  or `removed` (if LEFT longer). The schema-drift section still runs.
  Help/epilog calls out the footgun (re-sorted files will show wide
  diffs) and points at `-c`.
- **`--ignore COLS`** drops the named columns from the row comparison (but
  not the schema diff). Useful for timestamps and surrogate IDs.

### 4h. Renderers

**`render_human`** matches PRD §8 exactly:
- Headline: `"<n> changed, <a> added, <r> removed (of <c> rows compared)"`.
- If schema differs: a `! schema changed:` block before the headline.
- Per-row lines: `~ key=<value>   field: <left> -> <right>` for changed,
  `+ key=<value>   field=<v>  field=<v>` for added, `- …` for removed.
- Multiple changed fields on the same row are joined with two-space
  separators (or wrapped per line if total length > 200 cols — punted as
  OQ5).
- Composite key is shown as `(<v1>,<v2>)`.

**`render_jsonl`** — one JSON object per line, with stdlib `json.dumps(...,
default=default_str_decimal)` (reuse `csvkit.cli.default_str_decimal` for
Decimal/date). First line is a header event, then one event per diff:

```jsonl
{"event":"summary","compared":1204,"changed":3,"added":1,"removed":2,"schema_changed":false}
{"event":"schema","added_columns":["region"],"removed_columns":["legacy_code"],"reordered":true}
{"event":"row","status":"changed","key":{"id":4471},"fields":{"price":{"left":19.99,"right":24.99},"in_stock":{"left":"yes","right":"no"}}}
{"event":"row","status":"added","key":{"id":9001},"fields":{"name":"New SKU","price":12.00,"in_stock":"yes"}}
{"event":"row","status":"removed","key":{"id":3300},"fields":{"name":"Discontinued","price":8.00,"in_stock":"no"}}
```

JSONL chosen for streamability per the answered triage question.

**`render_summary`** — emits just the headline (and `! schema changed`
marker if applicable). Useful for shell `if csvdiff ... | grep changed`
patterns and for CI logs that don't need per-row noise.

### 4i. External dependencies

Just agate (already a runtime dep) and stdlib `json`. No new dependency.

If agate is down/broken: same blast radius as every other csvkit tool — the
whole suite breaks. No special handling.

---

## 5. Alternatives considered

1. **Add `--diff` as a flag on `csvjoin`** rather than a new tool. Rejected:
   conflates two verbs, breaks the "one tool = one verb" rule that csvkit's
   discoverability rests on (a user looking for "diff" would never read
   `csvjoin --help`). Also pollutes csvjoin's clear semantics with mode-
   switching code. csvkit's existing tool set has zero precedent for this.

2. **Line-oriented byte diff via stdlib `difflib`.** Rejected: this is
   precisely the failure mode the PRD §1 names — column reorder produces all-
   row noise, single-cell edits hide which field changed. Solves nothing.

3. **Sort both files by key, then streaming merge-compare.** Trades memory
   for a sort step (and disk if the sort spills). Rejected for v1 because
   (a) the PRD scale ("hundreds of thousands") fits in memory, (b) it would
   require coordinating with `csvsort`'s sort semantics, (c) it removes the
   ability to honor input order in output ("show me the diffs in the order
   they appeared in LEFT"), and (d) it doubles the surface area. Listed as
   OQ4 for a future v2 if users hit the memory wall.

4. **External binary (Go `csvdiff`, Rust `qsv diff`).** Faster and lower
   memory than agate. Rejected: violates "no new heavyweight runtime
   dependency" hard rule in CLAUDE.md; users would now need a separate
   install; loses csvkit's encoding/delimiter/locale handling.

5. **Do nothing — point users at pandas / `qsv`.** Rejected: the PRD frames
   this as the *current* status quo and the very gap to close. csvkit's
   value proposition is "the complete CLI suite"; an absent verb undermines
   that.

---

## 6. Non-functional requirements

Walking `references/nfrs-checklist.md` in order; every NFR is either
addressed or explicitly N/A.

**Scalability**
- **Target:** correct results on files up to ~1M rows × 50 cols on a
  developer laptop (8 GB RAM headroom). PRD says "hundreds of thousands"; we
  aim 2–3× to leave a margin.
- **Mechanism:** in-memory agate tables + dict-keyed index. O(n+m) time and
  memory.
- **Verification:** add one perf-smoke test in `tests/test_utilities/` that
  generates a 200k-row file via fixture script, asserts elapsed time under
  some loose bound (say, 30 s on CI) and asserts process completes. Don't
  promise sub-second.

**Reliability & availability** — N/A. CLI, no uptime SLO.

**Resilience** — N/A in the service sense. The closest analogue is "don't
crash on malformed input": covered in §4b/§4e (parse errors map to exit 2
with a useful stderr message).

**Performance**
- **Target:** linear in input size. p99 single-run latency is irrelevant for
  a CLI; wall-clock is bounded by I/O + agate parsing (same as csvjoin).
- **Mechanism:** single pass per table for parse; single pass per side for
  index build; single pass over union of keys for classify.
- **Verification:** the perf-smoke test above + cProfile snapshot during
  development. No CI gate on wall time (flaky on shared runners).

**Observability**
- For a CLI, observability == stderr diagnostics + exit codes. Covered in §4b
  and §4e. The `-v/--verbose` inherited flag enables full tracebacks.
- No metrics, logs, traces, alerts, runbook. N/A — local CLI.

**Security**
- **AuthN / AuthZ:** N/A — runs as the invoking user, on local files.
- **Secrets:** does not read or accept secrets. CSV contents are treated as
  opaque data.
- **Input validation:** treats both inputs as untrusted CSV. Inherits
  csvkit's `field_size_limit` handling and the CSV parser's existing
  safety. Does not eval, exec, or shell-out anything.
- **Threat model:** local, single-user. A maliciously crafted CSV could
  cause large memory use (already true of every csvkit tool). The
  `--maxfieldsize` inherited flag is the existing mitigation.
- **Supply chain:** depends on agate + stdlib; no new dep. Inherits csvkit's
  lockfile/version story.

**Cost** — N/A. Local CLI; no managed-service cost.

**Compliance & privacy** — N/A in the GDPR/HIPAA sense. The tool processes
whatever the user gives it, writes nothing persistent.

**Deployment & operations**
- **Deploy strategy:** released as part of csvkit's next minor version,
  documented as **experimental** per PRD §12. The `epilog` includes the
  experimental notice; the rst doc page calls it out at the top.
- **Rollback:** revert the release. No state, no migration.
- **Feature flags:** none — distribution-channel gating only (the
  experimental label).
- **Config:** standard csvkit flags only. No env vars beyond
  `PYTHONIOENCODING` (already used by `_init_common_parser`).

**Disaster recovery** — N/A. No persistent state.

**Maintainability**
- **Test strategy:** unittest classes in
  `tests/test_utilities/test_csvdiff.py`, subclassing
  `CSVKitTestCase, EmptyFileTests`. Fixtures in `examples/diff_*.csv`. Cover:
  - all four invocation styles (named/named, named/pipe, pipe/named,
    redirect+named, tty-with-no-input)
  - keyed match (single, composite)
  - no-key positional fallback (equal length, LEFT longer, RIGHT longer)
  - duplicate key under each `--on-dup` value
  - schema drift (column added, removed, reordered, all three at once,
    `--no-schema-check`)
  - typed equality (`1` vs `1.0`, `"true"` vs `"True"`) — assert equal by
    default, unequal under `-I`
  - exit codes 0, 1, 2 for every relevant path
  - `--format human / jsonl / summary` produce expected output for the
    same diff
  - `--quiet` produces empty stdout, correct exit code
  - missing key column → exit 2 with helpful message
  - malformed CSV → exit 2 with helpful message (NOT exit 1)
  - `--ignore` excludes a column from row diff but reports it in schema
- **Documentation:** `docs/scripts/csvdiff.rst` mirroring csvjoin's; entry
  in the docs script index; `CHANGELOG.rst` top entry; AUTHORS update.
- **Ownership:** csvkit maintainers; no separate team.

**Extensibility**
- The `DiffResult` / `Renderer` split (§4f, §4h) lets a future
  `--format=patch` or `--format=html` be added without touching the diff
  engine. The `--on-dup` flag is open to new values. `input_paths` is
  positional `*` so an N-way diff could be layered later (out of scope here).

---

## 7. Risks & failure modes

| Risk | Likelihood | Blast radius | Mitigation | Recovery |
|------|------------|--------------|------------|----------|
| User runs without `--key` on a re-sorted file and gets a misleading "all rows changed" report | High | One user, one run | `epilog` + the rst doc's "no-key" section warn explicitly; output's headline shows raw counts so the size of the false-positive is obvious. The §8 vision the PM approved retains this design choice (PRD OD1 answered "positional"). | User adds `--key`. No data harm. |
| Memory blow-up on multi-GB files | Medium for users at the upper end of the PRD scale | Single process OOM | `epilog` states the in-memory bound, mirroring csvjoin. | OOM kill; user shrinks input or uses upstream sort. Not silent. |
| Parse error reported as "differences found" (exit 1) instead of "error" (exit 2) | Low after fix; high without it | CI scripts misclassify | §4b fix: wrap `from_csv` in try/except, re-raise via `argparser.error`. Tested explicitly. | N/A once tested. |
| New exit code semantics break a downstream script that assumed "csvkit tools only exit 0 or 2" | Low | Specific script's CI | Document loudly in CHANGELOG and rst doc page that csvdiff exit codes are 0/1/2. Mark experimental for one release cycle to gather feedback before locking. | Caller branches on exit code; existing scripts not using csvdiff are unaffected. |
| Typed-comparison hides "real" string differences (e.g. `"01"` vs `"1"` collapsed to the integer `1`) | Medium | User confusion | `epilog` explains; `-I` is the escape hatch; PRD §8 user persona ("data journalist") generally wants typed comparison. | User reruns with `-I`. |
| `--on-dup=all` Cartesian explodes on a pathologically duplicated key | Low | Single run | Default is `error`; `all` is opt-in and the help warns about O(n·m). | Caller picks `first` or `error`. |
| Stdin double-use silently reports "no differences" | Low (we guard it) | Single user, one run | Explicit guard in §4a's input matrix; tested. | N/A. |
| Schema-drift detection misses a header that's renamed but otherwise compatible (e.g. `qty` → `quantity`) | Inherent | User decides | Out of scope; reported as `removed: qty` + `added: quantity` (the literal truth). Document. | User fixes column names upstream. |
| Encoding mismatch between LEFT and RIGHT | Medium | False diffs / parse error | The inherited `-e/--encoding` applies to BOTH files (single setting). Document this limitation; if users need per-file encoding, that's a v2 feature (OQ6). | Convert one file with `csvformat -e` first. |

---

## 8. Rollout & migration

- **Phase 1 — experimental release.** Ship `csvdiff` in csvkit `2.3.0`
  (next minor). The rst doc page and `epilog` both carry an
  **"experimental"** banner with a link to the issue tracker for feedback.
  Exit codes, output format, flag names may change in `2.4.x` based on
  feedback.
- **Phase 2 — stabilisation (one to two minor cycles).** Watch for issues
  on key/dup/schema edge cases, locale-specific number parsing diffs,
  unicode-normalization surprises. Validate the OD1/OD3/JSONL choices
  against real usage. Lock the interface.
- **Phase 3 — GA.** Remove the experimental banner. Mention in
  CHANGELOG/release notes. Add to the "Tutorial" docs alongside csvjoin
  and csvsort.

**Backwards compatibility:** N/A — net-new command. **No existing tool's
CLI surface changes.** This is a hard guardrail from CLAUDE.md.

**Rollback:** revert the release.

---

## 9. Observability & operations

For a CLI, "observability" reduces to:
- **Exit codes** (§4b) are the primary signal for CI.
- **Stderr diagnostics** are the secondary signal for humans. `-v/--verbose`
  toggles full tracebacks (inherited).
- **No central metrics, logs, traces, alerts, runbook.** N/A — local CLI.

**Operations surface area:** none. There is no service to operate.

---

## 10. Open questions

1. **OQ1 — Exit-code parity across the suite.** csvdiff introduces "1 =
   differences found" as the first csvkit tool to use a non-zero data-
   condition exit code. Should we audit other tools where a similar pattern
   would help (e.g. `csvgrep` with a `--count` mode signaling "no matches"
   like `grep`)? Recommendation: leave the question to a follow-up after
   csvdiff lands; do not retrofit existing tools.

2. **OQ2 — Whitespace and unicode normalisation.** Should leading/trailing
   whitespace inside text fields be stripped before comparison? Should
   `é` (precomposed) compare equal to `é` (decomposed)? Recommendation:
   no normalization in v1; add `--ignore-whitespace` and a `--normalize`
   flag if users ask. Document the v1 behavior.

3. **OQ3 — Key value formatting in human output.** When the key column is
   a date or large number, what's the formatting? Current plan: agate's
   string casting, same as `csvjson`. Verify it reads cleanly in the §8
   layout before GA.

4. **OQ4 — Streaming / sorted-merge backend.** For files that don't fit
   in memory, a sorted-merge alternative would scale further. Decision:
   defer until a user files an issue. Today's PRD scale is comfortably
   in-memory.

5. **OQ5 — Long changed-row line wrapping.** When dozens of fields change
   in one row, the §8 single-line format becomes unreadable. Options:
   wrap, paginate, or print one field per line. Recommend: stick with
   single-line for v1, watch for complaints, then add `--wrap` or a
   tabular `--format=table` variant.

6. **OQ6 — Per-file encoding override.** Inherited `-e/--encoding` is
   global. If a user has LEFT in UTF-8 and RIGHT in latin-1, they have
   to preprocess. Adding `--left-encoding` / `--right-encoding` is
   straightforward but adds two flags for a rare case. Recommend: deferred,
   solved upstream by `csvformat`.

7. **OQ7 — Schema-drift reporting under `-H/--no-header-row`.** With no
   header, "added column" is meaningless (columns are named a, b, c by
   `make_default_headers`). Recommend: when `-H` is set, suppress schema
   diff entirely (it would always be "no schema change" or pure noise) and
   document.

8. **OQ8 — Per-platform stdin reconfigure with two paths.** `cli.py`'s
   `_open_input_file` reconfigures stdin encoding only once (the `opened`
   guard); on the second call it does not. csvdiff calls
   `_open_input_file` twice. Verify this is safe (we only ever reconfigure
   stdin for the single side that uses `-`) — the existing code is
   structured to support it, but add a test.
