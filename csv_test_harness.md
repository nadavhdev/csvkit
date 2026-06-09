# `csvdiff` — Black-Box Test Harness Specification

> **Status**: design document. The reviewer is expected to approve (or amend) this spec before the bash harness is implemented.
>
> **Stance**: black-box. The author of this spec did **not** look at the `csvdiff` implementation while writing this document. Tests are derived purely from the PRD and from what a CLI user can observe (stdout, stderr, exit code, file output). When the PRD intentionally leaves a decision to the implementer (no-key default, duplicate-key policy, key flag spelling, exit codes >0), the harness *probes* the actual behavior at startup and runs the appropriate branch of tests.

---

## 1. Goal

Produce a **single bash entry point** (`run_csvdiff_tests.sh`) that:

1. Generates all required fixture CSVs (so the harness is self-contained — no dependency on `examples/` shipped with csvkit).
2. Discovers the actual CLI surface of `csvdiff` (key flag spelling, format values, exit-code scheme, no-key policy, duplicate-key policy) via `--help` and a small set of probe runs.
3. Executes ~80 named tests across 6 categories (happy / alternate / error / edge / performance / inherited).
4. Re-runs each test N times (default 3 for functional, 5 for performance) and classifies the result as **PASS**, **FAIL**, **FLAKY**, or **SKIPPED**.
5. Prints a human-readable report and (optionally) emits a machine-readable artifact (JSON + JUnit XML).
6. Exits 0 iff every functional test passed (flaky and skipped are tolerated unless `--strict` is passed).

---

## 2. PRD requirements distilled into test obligations

The PRD requires the harness to cover all of the following. Each obligation maps to one or more test IDs in §4.

| # | PRD obligation                                                                                                   | Covered by              |
|---|------------------------------------------------------------------------------------------------------------------|-------------------------|
| R1 | Two positional CSV inputs; STDIN allowed for one; guarded tty-no-input case                                     | H01, A06, A07, E01, E02, E03 |
| R2 | `--key` matches by one or more columns; flag doesn't collide with common args or csvjoin's `-c`                 | H03–H07, A01–A03        |
| R3 | Row classification: added / removed / changed / unchanged                                                       | H03–H08                 |
| R4 | Changed rows report **which** columns differ, with before→after; unchanged fields **not** reported              | H05, H07                |
| R5 | No-key default is "useful and defensible" (positional OR require-key, documented)                               | H09a, H09b (branched)   |
| R6 | Schema drift (added / removed / reordered cols) reported **distinctly** and **before** row diffs                | A08, A09, A10, ED16     |
| R7 | Exit codes: 0 equivalent / distinct non-zero for differences / separate misuse; argparse already uses 2         | every test asserts exit |
| R8 | Default human-readable output: summary headline + marked rows (`~`, `+`, `-`) leading with key                  | H03–H07                 |
| R9 | Machine-readable output via a `--format` flag (JSON and/or CSV)                                                 | A04, A05, A04b, A05b    |
| R10 | All standard input handling inherited (encoding / delimiter / quoting / header / skip-lines / inference / …)   | I01–I16                 |
| R11 | If file held in memory, epilog documents the tradeoff                                                          | H10 (text scan of `--help`) |
| R12 | Identical, re-sorted, schema-drifted, duplicate-key, typed-vs-string, bad-key, empty, STDIN, machine-output     | A11, A12, A13, E08, E09, ED01–ED03, A06, A07 |
| R13 | Works on Linux + macOS + Windows                                                                                | platform note in §9     |

---

## 3. Test taxonomy

```
happy/        Smallest possible inputs proving each documented behavior
alternate/    Variations: composite keys, indices, formats, stdin, schema drift
error/        Usage errors, bad args, missing files, exit-code shape
edge/         Empty/header-only/single-row, BOM, unicode, newlines, nulls, dates
perf/         Wall-time + peak-RSS on 1k / 10k / 100k rows; determinism
inherited/    One test per common csvkit arg that must pass through
```

Naming: `category/NN_short_name`, where `NN` is a stable 2-digit ID.

---

## 4. Test catalogue

Each entry is written in **Given / When / Then** style. The "Then" line is the harness's assertion — it must be satisfied by **every** of the N retries to count as PASS.

### 4.1 Happy path (H)

| ID | Given | When | Then |
|----|-------|------|------|
| H01 | Two byte-identical small CSVs `id,name,age` × 3 rows | `csvdiff -k id A A` | exit=0; stdout has "Summary:" line with `0 added, 0 removed, 0 changed, 3 unchanged` (or semantically equivalent); no schema section; no row-diff section |
| H02 | Same as H01 | `csvdiff A A` (no key) | If no-key default = **positional**: exit=0, all-unchanged summary. If no-key default = **require-key**: exit=2, stderr mentions the key flag. (Branched via probe — see §5.2.) |
| H03 | A=3 rows; B = A + one extra row | `csvdiff -k id A B` | exit=non-zero-differences; summary shows `1 added`; stdout contains a row line beginning with `+` and including the new key value |
| H04 | A=3 rows; B = A minus one row | `csvdiff -k id A B` | exit=differences; summary shows `1 removed`; stdout contains a row line beginning with `-` and including the removed key |
| H05 | A and B differ in **one cell** of one matched row | `csvdiff -k id A B` | exit=differences; summary shows `1 changed`; stdout contains a row line beginning with `~`, the key, and `column: a -> b` for the changed column **only**; no other column appears on that line |
| H06 | A, B differ by 1 add + 1 remove + 1 change + 1 unchanged | `csvdiff -k id A B` | summary shows exactly `1 added, 1 removed, 1 changed, 1 unchanged`; row section contains exactly one `+`, one `-`, one `~` row line |
| H07 | A and B identical except one cell in row R | `csvdiff -k id A B` | the `~` line for R does **not** mention unchanged columns from R (asserted by counting `column:` segments on that line vs. the number of actually-changed columns) |
| H08 | A and B identical | `csvdiff -k id A B` | exit=0; stdout does **not** contain the string used as the row-diff section header (probed from a known-diff run); no schema section |
| H09a | Probed no-key default = **positional**: A and B same shape, differ in row 2 only | `csvdiff A B` | exit=differences; the change is reported with a positional row identifier (row number, not data key) |
| H09b | Probed no-key default = **require-key**: A and B same shape, differ in row 2 only | `csvdiff A B` | exit=2; stderr message references the `--key`/`-k` flag |
| H10 | `csvdiff --help` | run | exit=0; help text mentions the in-memory tradeoff (a substring like "memory" or "indexes" or "into memory" in the epilog) — fulfills R11 |
| H11 | A and B identical | `csvdiff -k id A B; echo $?` twice in a row | both runs produce **byte-identical** stdout (determinism) |

### 4.2 Alternate flows (A)

| ID | Given | When | Then |
|----|-------|------|------|
| A01 | A,B have composite key `(year, quarter)`; differ in Q2 revenue | `csvdiff -k year,quarter A B` | exit=differences; `~` row identifies the composite key (e.g. `2024 \| Q2` or `2024,Q2`) |
| A02 | 3-column composite key | `csvdiff -k a,b,c A B` | exit and diff content correct on 3-key match |
| A03 | A,B with `id` as 1st column | `csvdiff -k 1 A B` | behaves identically to `-k id` (column index resolves to same column) |
| A04 | A,B with 1 add + 1 remove + 1 change | `csvdiff --format json -k id A B` | stdout is valid JSON (parses with `python -m json.tool`); contains `summary` with the four counts; rows are addressable by `added`/`removed`/`changed` arrays; each `changed` entry has the column name and both before & after values |
| A04b | Same | `csvdiff --format json -k id A A` | exit=0; JSON parses; summary counts are all 0 except `unchanged` |
| A05 | A,B with 1 add + 1 remove + 1 change | `csvdiff --format csv -k id A B` | stdout is a valid CSV that `csvcut -n` can read; first row is a header with 5+ columns including `status`, `key`, and column-name-like fields; contains at least one row whose `status` is `changed` and whose key matches the changed row |
| A05b | Same | `csvdiff --format csv -k id A A` | header-only CSV (no row records) |
| A06 | A,B as files; B piped | `cat B \| csvdiff -k id A -` | identical diff to A03 run (the `-` resolves to B from stdin) |
| A07 | A piped, B as file | `cat A \| csvdiff -k id - B` | identical diff (mirrors A06 with the order flipped) |
| A08 | A has cols `(id,name,age)`; B has `(id,name,age,city)`; key matches in all rows | `csvdiff -k id A B` | exit=differences; schema section reports a column `city` as added; row section reports 0 row changes; **schema section appears BEFORE the row section** in stdout |
| A09 | A has `(id,name,age)`; B has `(id,name)` | `csvdiff -k id A B` | schema section reports `age` as removed; schema before rows |
| A10 | A `(id,name,age)`, B `(id,age,name)` (reordered) | `csvdiff -k id A B` | schema section reports reordering; row section shows 0 changes (proves rows compared by column **name** not position) |
| A11 | B is A with rows in different order, key `id` | `csvdiff -k id A B` | exit=0; 0 row changes — proves identity-based matching |
| A12 | A age=30,25,40; B age=30.0,25.0,40.0 | `csvdiff --no-inference -k id A B` | exit=differences; all 3 rows reported as changed in `age` |
| A13 | Same files as A12 | `csvdiff -k id A B` | exit=0 — typed comparison treats `30` == `30.0` |
| A14 | A,B are TSVs | `csvdiff -t -k id A B` | parses correctly; same diff as the CSV equivalent |
| A15 | A,B use `;` delimiter | `csvdiff -d ';' -k id A B` | parses; correct diff |
| A16 | A,B encoded latin-1 with non-ASCII names | `csvdiff -e latin1 -k id A B` | non-ASCII values preserved in output; correct diff |
| A17 | A,B with no header row (data starts immediately); user passes `-H -k 1` | run | columns named `a,b,c,…`; matches by 1st column work |
| A18 | A,B prefixed with 2 comment lines | `csvdiff -K 2 -k id A B` | comments skipped; diff correct |

### 4.3 Error flows (E)

| ID | Given | When | Then |
|----|-------|------|------|
| E01 | No args, stdin is a tty (not piped) | `csvdiff </dev/null </dev/tty 2>&1` (or simulated with `script`) | exit=2; stderr matches `error:.*input` (case-insensitive) |
| E02 | One file argument, no stdin pipe | `csvdiff A` | exit=2; stderr says "two" (e.g. "requires exactly two input files") |
| E03 | Three file arguments | `csvdiff A B C` | exit=2; stderr indicates count problem |
| E04 | Path that doesn't exist | `csvdiff -k id A nonexistent.csv` | non-zero exit; stderr or stdout contains a clear error (FileNotFoundError or similar) — **the test asserts a graceful message, not a traceback** |
| E05 | File without read permission (`chmod 000`) | `csvdiff -k id A unreadable.csv` | non-zero exit; clear PermissionError-style message |
| E06 | Bad key name | `csvdiff -k nope A A` | exit=2; stderr contains `csvdiff: error:` and the column name `'nope'` |
| E07 | Bad key index out of range | `csvdiff -k 999 A A` | exit=2; stderr indicates invalid column |
| E08 | First file has duplicate keys in the key column | `csvdiff -k id dup.csv A` | If duplicate-key policy = **error** (probed): exit=2 and stderr explains duplicate. If policy = **allow**: exit reflects diff and a documented disambiguation strategy is observable. (Branched.) |
| E09 | Second file has duplicate keys | mirror of E08 | mirror behavior |
| E10 | `csvdiff -h` and `csvdiff --help` | run | exit=0 for both; stdout includes `usage:` and the key flag |
| E11 | `csvdiff -V` and `csvdiff --version` | run | exit=0 for both; stdout matches `csvdiff \d+\.\d+\.\d+` |
| E12 | Invalid format value | `csvdiff --format yaml A A` | exit=2 (argparse choice rejection); stderr mentions valid choices |
| E13 | Both `-t` and `-d X` together | `csvdiff -t -d ';' A A` | exit=0 (PRD inherits: `-t` overrides `-d`); diff still valid |
| E14 | Pipe stdin but pass two file args | `cat B \| csvdiff A B` | stdin is **ignored** (two files already supplied); exit reflects the A-vs-B diff |
| E15 | Empty `--key` value | `csvdiff -k '' A A` | exit=2 with a meaningful message (not a Python traceback) |

### 4.4 Edge cases (ED)

| ID | Given | When | Then |
|----|-------|------|------|
| ED01 | Both files truly empty (0 bytes) | `csvdiff -k id empty empty` | exit≤1; **no Python traceback** on stderr; output is internally consistent (e.g. all-zeros summary or a clean error) |
| ED02 | Both header-only (no data rows) | `csvdiff -k id hdr hdr` | exit=0; summary shows 0/0/0/0 |
| ED03 | Each file has exactly 1 row, differing in 1 cell | `csvdiff -k id A B` | exit=differences; one `~` row reported |
| ED04 | A uses `\n`, B uses `\r\n`; data otherwise identical | `csvdiff -k id A B` | exit=0 (line endings should not be reported as row differences) |
| ED05 | A or B has a UTF-8 BOM at start | `csvdiff -k id A B` | BOM is transparent; correct diff |
| ED06 | Names contain emoji + CJK characters | `csvdiff -k id A B` (one changed name) | exit=differences; the non-ASCII before/after values appear correctly in stdout (no `?` substitutions, no mojibake) |
| ED07 | A cell contains an embedded newline inside `"…"` | `csvdiff -k id A B` | not misinterpreted as row break; matches B's identical cell as unchanged |
| ED08 | A row whose cell is 100 KB long | `csvdiff -k id A B` (-z bumped if needed) | exit reflects diff; no crash, no truncation visible in output |
| ED09 | id values are `007`, `008`, `009` (leading zeros) | `csvdiff --no-leading-zeroes -k id A B` | matches by string; `007` ≠ `7` |
| ED10 | A and B use `MM/DD/YYYY`; one date changes | `csvdiff --date-format '%m/%d/%Y' -k id A B` | exit=differences; the changed-row line reports the date column |
| ED11 | A has `""`, B has `"NA"` in same cell, with `--blanks` off (default) and on | run both | with default blanks-off, both are NULL → equal → unchanged; with `--blanks`, they are distinct → changed |
| ED12 | A ends with trailing newline; B does not | `csvdiff -k id A B` | exit=0 (trailing newline is not a row difference) |
| ED13 | Delimiter followed by leading spaces inside cells | `csvdiff -S -k id A B` | leading spaces stripped per PRD inheritance; correct diff |
| ED14 | A row has a cell `""`, B has the same | `csvdiff -k id A B` | unchanged |
| ED15 | Mixed schema + row drift: schema differs **and** rows differ | `csvdiff -k id A B` | both sections appear; **schema section precedes row section** in stdout |
| ED16 | A is empty header-only, B has 3 rows | `csvdiff -k id A B` | all 3 in B reported as added; exit=differences |
| ED17 | B is empty header-only, A has 3 rows | mirror | all 3 reported as removed |
| ED18 | A and B have identical key column but no other shared columns | `csvdiff -k id A B` | schema diff lists all non-key A cols as removed and all non-key B cols as added; row section shows 0 changes |
| ED19 | All rows changed (no unchanged) | `csvdiff -k id A B` | summary shows `N changed, 0 unchanged` |
| ED20 | A column name appears twice in headers (e.g. `a,b,a`) | `csvdiff -k 1 A A` | does not crash; result is internally consistent — assertion is **no Python traceback** |
| ED21 | Key column name contains a comma (quoted) | reasonable to skip with documented reason — comma is the `--key` separator | test is marked SKIPPED with note |
| ED22 | Float vs int in same cell (`1` vs `1.0`) | `csvdiff -k id A B` and `csvdiff -I -k id A B` | first is unchanged (typed equal), second is changed (string different) — same as A12/A13 but consolidated assertion |

### 4.5 Performance & determinism (P)

Thresholds are **declared in `perf.config`** and can be tightened by the reviewer. Defaults are intentionally generous.

| ID | Given | When | Then |
|----|-------|------|------|
| P01 | 1 000 rows × 5 cols, ~1 % changed | `csvdiff -k id A B` | wall < 2 s; peak RSS < 200 MB |
| P02 | 10 000 rows × 5 cols, ~1 % changed | same | wall < 5 s; peak RSS < 400 MB |
| P03 | 100 000 rows × 5 cols, ~1 % changed | same | wall < 60 s; peak RSS < 1.5 GB |
| P04 | 10 000 rows × 50 cols, ~1 % changed | same | wall < 15 s; peak RSS < 600 MB |
| P05 | A and B identical (100k rows) | `csvdiff -k id A A` | exit=0; wall < 60 s |
| P06 | Worst case: every row added (A empty header, B 50k rows) | `csvdiff -k id A B` | exit=differences; harness records timing without an upper bound (reported as informational) |
| P07 | Same fixture as P02, run 5 times | timing stability | min/max wall-time variance ≤ 50 %; flag FLAKY otherwise |
| P08 | Same fixture as P02, run 5 times | output stability | byte-identical stdout across runs (determinism) |

### 4.6 Inherited common-arg integration (I)

One narrow happy-path test per inherited flag, just to verify it isn't silently ignored. Identical files unless noted.

| ID | Flag | Test |
|----|------|------|
| I01 | `-V`/`--version` | exits 0 with version string (also E11) |
| I02 | `-h`/`--help` | exits 0 with usage (also E10) |
| I03 | `-d ';'` | semi-colon delimited files compare correctly |
| I04 | `-t` | TSV input compares correctly (also A14) |
| I05 | `-q '\''` | non-default quote char round-trips |
| I06 | `-u 1` (QUOTE_ALL) | input read correctly |
| I07 | `-b` (no-doublequote) | runs without error on an input that doesn't need it |
| I08 | `-p '\\'` | escape char accepted |
| I09 | `-z 1000000` | wide-field limit accepted on a wide-cell fixture |
| I10 | `-e latin1` | latin1 file with non-ASCII parses (also A16) |
| I11 | `-L en_US` | accepted; no behavior change asserted |
| I12 | `-S` | leading spaces inside cells stripped (also ED13) |
| I13 | `--blanks` / `--null-value` | distinguishes empty from sentinel nulls |
| I14 | `--date-format` / `--datetime-format` | accepted on a date-format fixture (also ED10) |
| I15 | `--no-leading-zeroes` | `007` ≠ `7` (also ED09) |
| I16 | `-H` | no-header-row mode works (also A17) |
| I17 | `-K 2` | skip-lines works (also A18) |
| I18 | `-v` | with `-v`, a forced error prints a traceback; without `-v`, it does not |
| I19 | `-l` (linenumbers) | when used with `--format csv`, output gains a line-number column |
| I20 | `--add-bom` | output to a real file starts with the UTF-8 BOM bytes `EF BB BF` |
| I21 | `--zero` | zero-based column index works with `-k 0` |
| I22 | `-I`/`--no-inference` | already covered by A12, included here for traceability |

Total tests (counting branched H02/H09 once): **~80**.

---

## 5. Harness architecture

### 5.1 Filesystem layout

```
test-harness/
├── run_csvdiff_tests.sh         # entry point
├── lib/
│   ├── probe.sh                 # startup discovery (5.2)
│   ├── fixtures.sh              # CSV generators (5.3)
│   ├── assert.sh                # assertion library (5.4)
│   ├── runner.sh                # per-test execution + retries (5.5)
│   ├── perf.sh                  # wall-time + RSS capture (5.6)
│   └── report.sh                # text / JSON / JUnit emitters (5.7)
├── tests/
│   ├── happy.sh                 # H01..H11
│   ├── alternate.sh             # A01..A18
│   ├── error.sh                 # E01..E15
│   ├── edge.sh                  # ED01..ED22
│   ├── perf.sh                  # P01..P08
│   └── inherited.sh             # I01..I22
├── perf.config                  # tweakable thresholds
└── README.md                    # how to run / extend
```

Working files live under `$(mktemp -d)`; cleaned on success, kept on failure unless `--clean`.

### 5.2 CLI probe (run once at startup)

Discovers the *actual* CLI shape so the harness adapts to whichever implementation choices were made.

1. `csvdiff --help` is captured.
2. The probe greps the help text for:
   - **Key flag**: looks for `(-k|--key)` or `(-j|--join-key)` or `(-K|--key-columns)` (the PRD forbids common-flag single letters and `-c`). Stored as `$KEY_FLAG`.
   - **Format flag**: looks for `--format` plus its choices. Stored as `$FMT_FLAG` and `$FMT_CHOICES`.
   - **No-inference flag**: looks for `-I` or `--no-inference`. Stored as `$NOINF_FLAG`.
   - **Epilog memory note**: existence of the substring (matches /memory/i in epilog area) → records pass/fail of H10.
3. **No-key default probe**: runs `csvdiff <tinyA.csv> <tinyA.csv>` (identical inputs, no `--key`).
   - exit=0 → no-key default is **positional** → enable H09a, skip H09b.
   - exit=2 and stderr mentions key flag → no-key default is **require-key** → enable H09b, skip H09a.
   - anything else → FAIL the probe (this is a PRD violation).
4. **Duplicate-key policy probe**: runs `csvdiff $KEY_FLAG id <dup.csv> <ok.csv>`.
   - exit=2 → policy is **error**; E08/E09 assert the error message.
   - exit non-2 and a defined diff produced → policy is **allow**; E08/E09 assert the documented disambiguation (e.g. all-vs-all match, first-match-wins). Probe records which.
5. **Exit-code scheme probe**: runs three scenarios — identical, differing, bad-key — and records the observed codes as `$EXIT_OK`, `$EXIT_DIFF`, `$EXIT_USAGE`. Every assertion in §4 references these variables rather than hard-coded numbers, so the harness is robust to a different (but internally consistent) numbering.

Any probe failure (e.g. no key flag found, ambiguous no-key behavior) is a **FAIL** of a pseudo-test called `probe/00_cli_shape`, and dependent tests are SKIPPED with the probe failure as the reason.

### 5.3 Fixture generation

All fixtures are generated by `lib/fixtures.sh` into the temp dir. No reliance on `examples/`. Examples of generators:

```bash
gen_basic_pair()           # diff_a.csv, diff_b.csv (PRD-spec small fixture)
gen_composite()            # year,quarter,revenue
gen_resorted()             # B = A with shuffled row order
gen_schema_added()         # B = A + extra column
gen_schema_removed()       # B = A − column
gen_schema_reordered()     # B = A with columns in a different order
gen_typed_pair()           # ages as 30 vs 30.0
gen_dup_keys()             # A has duplicate id values
gen_tsv()                  # tab-separated equivalent of basic pair
gen_latin1()               # latin-1 encoded with non-ASCII
gen_unicode()              # emoji + CJK
gen_bom()                  # file starting with EF BB BF
gen_embedded_newline()     # quoted cell with \n inside
gen_long_cell K            # one cell K bytes long
gen_leading_zeros()        # id values 007/008/009
gen_dates()                # MM/DD/YYYY
gen_blanks()               # mix of "", NA, NULL, .
gen_perf_pair N M PCT      # NxM with ~PCT% diff (used by P01..P05)
gen_empty()                # truly empty file
gen_header_only()          # header but 0 data rows
gen_dup_cols()             # repeated header name
```

Each generator is a function that writes to `$WORK/<name>.csv` and is **idempotent** within a run.

Generators for fixtures `gen_perf_pair N M PCT` use awk to keep generation fast (10^5 rows in < 2 s on a laptop). No reliance on Python so the harness can run pre-install.

### 5.4 Assertion library

All assertions take the form `assert_X expected actual_supplier message`. They write to a per-test trace file on failure (used by the report). Listing:

```
assert_exit                EXPECTED CMD…
assert_stdout_eq           EXPECTED CMD…        # full string compare
assert_stdout_contains     SUBSTR CMD…
assert_stdout_not_contains SUBSTR CMD…
assert_stdout_matches      REGEX CMD…
assert_stderr_contains     SUBSTR CMD…
assert_stderr_matches      REGEX CMD…
assert_stdout_is_valid_json CMD…                # pipes to python -m json.tool
assert_json_path           JSONPATH EXPECTED CMD…   # uses python -c
assert_stdout_is_valid_csv CMD…                 # pipes to csvcut -n
assert_no_traceback        CMD…                 # asserts 'Traceback' not in stderr
assert_file_bytes_eq       PATH HEX_PREFIX      # for BOM test
assert_runs_under          SECONDS CMD…         # wall-time wrapper
assert_rss_under           BYTES CMD…           # peak-RSS wrapper (5.6)
```

All assertion helpers return 0/1, never call `exit` themselves. The runner aggregates results.

### 5.5 Runner & flaky detection

`runner.sh` provides:

```bash
run_test "category/NN_name" "description" <function-name>
```

Behavior:
1. Calls the test function `RETRIES` times (default 3; configurable per-test via env).
2. Each call gets a fresh subshell, fresh `$WORK_TEST` scratch dir.
3. Result classification:
   - All N runs pass → **PASS**
   - All N runs fail → **FAIL** (records the failure detail from run 1)
   - Mixed → **FLAKY** (records both: a sample pass and a sample fail)
4. Per-test time is the **median** of the N runs.

Functional tests (everything except `perf/*`) use N=3. Performance tests use N=5 and additionally compute min/max/median/stddev.

### 5.6 Performance measurement

Wall time: `time` (built-in) with `TIMEFORMAT='%R'`.

Peak RSS:
- macOS: `/usr/bin/time -l` and parse the `maximum resident set size` line.
- Linux: `/usr/bin/time -v` and parse `Maximum resident set size (kbytes)`.
- The harness detects platform via `uname` and picks the right invocation.
- If `/usr/bin/time` isn't available (e.g. minimal CI image), RSS tests are SKIPPED with that reason.

Per-test thresholds live in `perf.config` so reviewers can tighten them per-environment:

```bash
PERF_P01_WALL=2
PERF_P01_RSS_MB=200
PERF_P02_WALL=5
PERF_P02_RSS_MB=400
…
PERF_FLAKY_WALL_VAR=0.5      # 50 %
PERF_FLAKY_RSS_VAR=0.25      # 25 %
```

### 5.7 Reporting

Default: human-readable to stdout.

```
================================================================
csvdiff Test Harness — 2026-06-08T18:15:21Z
csvdiff:    /Users/.../.venv/bin/csvdiff
csvdiff -V: csvdiff 2.2.0
Probe:      KEY_FLAG=-k FMT_FLAG=--format NOINF_FLAG=-I
            no-key default = positional
            duplicate-key policy = error
            exit codes: OK=0 DIFF=1 USAGE=2

happy/    11/11  PASS
alternate/18/18  PASS
error/    15/15  PASS
edge/     21/22  PASS (1 SKIPPED: ED21)
perf/      7/ 8  PASS (1 FLAKY: P07 — wall 2.8s..6.1s, var=1.18)
inherited/22/22  PASS

Failures:
  (none)

Flaky:
  perf/07_timing_stability
    runs (wall seconds): 2.8 3.0 3.2 5.9 6.1
    variance 1.18 > threshold 0.50

Skipped:
  edge/21_comma_in_key_name
    reason: comma is the --key value separator; no workaround per PRD

================================================================
TOTAL: 94 tests   PASSED 93   FAILED 0   FLAKY 1   SKIPPED 1
Exit: 0   (use --strict to fail on FLAKY)
================================================================
```

Optional outputs (flags):

- `--report json PATH` — full machine-readable report (per test: status, runs, wall, rss, stdout snippets on failure)
- `--report junit PATH` — JUnit XML for CI ingestion

### 5.8 Configuration / CLI of the harness itself

```
run_csvdiff_tests.sh [options]

  --csvdiff PATH        Path to the csvdiff binary (default: $(command -v csvdiff))
  --filter PATTERN      Run only tests matching glob (e.g. 'happy/*', '*schema*')
  --retries N           Override default retries (functional only)
  --strict              Exit non-zero on FLAKY or SKIPPED
  --keep                Keep $WORK on success
  --report text|json|junit:PATH    Add a report output (can repeat)
  --skip-perf           Skip perf/* category
  --no-color            Plain output
  -h, --help            Show usage
```

Exit status: `0` if all functional tests passed, otherwise `1`. With `--strict`, any FLAKY or SKIPPED also yields `1`.

---

## 6. Bash skeleton (illustrative — what the implementation should look like)

```bash
#!/usr/bin/env bash
set -u -o pipefail                       # not -e; tests may legitimately fail commands

ROOT="$(cd "$(dirname "$0")" && pwd)"
. "$ROOT/lib/probe.sh"
. "$ROOT/lib/fixtures.sh"
. "$ROOT/lib/assert.sh"
. "$ROOT/lib/runner.sh"
. "$ROOT/lib/perf.sh"
. "$ROOT/lib/report.sh"

parse_harness_args "$@"

WORK="$(mktemp -d)"; export WORK
trap 'on_exit' EXIT
generate_all_fixtures "$WORK"

probe_cli                                # sets KEY_FLAG, EXIT_OK, EXIT_DIFF, etc.
report_header

. "$ROOT/tests/happy.sh";     run_section happy
. "$ROOT/tests/alternate.sh"; run_section alternate
. "$ROOT/tests/error.sh";     run_section error
. "$ROOT/tests/edge.sh";      run_section edge
. "$ROOT/tests/perf.sh";      run_section perf
. "$ROOT/tests/inherited.sh"; run_section inherited

report_summary
exit_with_appropriate_code
```

A representative test function:

```bash
test_H05_single_field_changed() {
    local A="$WORK/h05_a.csv" B="$WORK/h05_b.csv"
    gen_basic_pair "$A" "$B" --change "id=2 age=25→26"

    assert_exit "$EXIT_DIFF" csvdiff "$KEY_FLAG" id "$A" "$B" || return 1
    assert_stdout_matches '^~ .*\[2\].* age: 25 -> 26' \
        csvdiff "$KEY_FLAG" id "$A" "$B" || return 1
    # Unchanged column "name" must not appear on the ~ line for id=2.
    assert_stdout_not_matches '^~ .*\[2\].* name:' \
        csvdiff "$KEY_FLAG" id "$A" "$B" || return 1
}
run_test happy/05_single_field_changed test_H05_single_field_changed
```

---

## 7. Running & extending

**Run locally (after `pip install -e .`):**

```bash
cd test-harness
./run_csvdiff_tests.sh
```

**Run in CI:**

```bash
./run_csvdiff_tests.sh --report junit:results.xml --strict
```

**Add a new test:**

1. Pick the category file in `tests/`.
2. Add a `test_XX_name() { … }` function using the assertion library.
3. Register it with `run_test category/XX_name test_XX_name`.
4. (Optional) Add the row to §4 of this document.

---

## 8. Platform notes

- Tested target: **bash 4+**, GNU coreutils OR BSD coreutils (macOS).
- `/usr/bin/time` is required for RSS tests; absent → those tests SKIPPED.
- `python3` is required for JSON validation (`python -m json.tool`).
- `csvcut` (from csvkit itself) is used to validate the CSV output format — acceptable circular dependency since this harness is for csvkit.
