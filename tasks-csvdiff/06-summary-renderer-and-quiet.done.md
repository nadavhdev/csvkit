# task-06 — done

**Task spec:** [done/06-summary-renderer-and-quiet.md](done/06-summary-renderer-and-quiet.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/10
**Commit:** d4e382d
**Completed:** 2026-06-12
**Branch:** feat/csvdiff-summary-quiet (off feat/csvdiff-jsonl-renderer)

## What was built

`csvdiff` now has two "less output" modes for CI use. `--format=summary` (added to the existing
`--format {human,jsonl}` choices) emits only the headline counts line plus the schema banner when
applicable — no per-row diff lines. `--quiet` suppresses all stdout output while preserving the
0/1/2 exit-code contract; stderr diagnostics (parse errors, key errors) are unaffected. The `-q`
short form is intentionally absent — it is the inherited `-q/--quotechar` flag — documented in
both the flag help text and the epilog.

## Files changed

- `csvkit/utilities/csvdiff.py` — added `render_summary(result, key_names, output_file,
  show_schema=False)` after `render_jsonl`; extended `--format` choices to `['human', 'jsonl',
  'summary']`; added `--quiet` (`store_true`, no `-q`); updated epilog; updated renderer dispatch
  in `main()` to `if quiet → renderer=None; elif jsonl; elif summary; else human` with
  `if renderer is not None:` guards at both call sites
- `tests/test_utilities/test_csvdiff.py` — added `render_summary` to import; added
  `TestCSVDiffSummary` (11 tests) and `TestCSVDiffQuiet` (8 tests) inheriting from
  `_CSVDiffOutputMixin, CSVKitTestCase`

## Decisions & departures from spec

- **`render_summary` calls `_render_schema_banner`** (the full banner with added/removed/reordered
  sub-lines), not just the `! schema changed:` marker line. The TDD §4h says "emits just the
  headline (and `! schema changed` marker if applicable)" — "marker" was interpreted as the full
  banner block (identical to `render_human`), because `render_summary` replaces only the per-row
  lines, not the schema context. This is the more useful behavior and consistent with `render_human`.
- **`renderer = None` for `--quiet`** — rather than redirecting to a discard buffer, the dispatch
  sets `renderer = None` and guards both call sites with `if renderer is not None:`. This is
  cleaner, avoids any write to `self.output_file`, and keeps the code path explicit.
- **All acceptance criteria matched spec exactly.** No other departures.

## Test coverage

- ✓ `--format summary` emits no per-row diff lines (`-`, `~`, `+`)
- ✓ `--format summary` headline counts correct (1 changed, 1 added, 1 removed)
- ✓ `--format summary` equal files: all-zero counts, single line
- ✓ `--format summary` with schema drift: banner + headline, no row lines
- ✓ `--format summary` + `--no-schema-check` suppresses banner
- ✓ Exit codes 0/1/2 under `--format summary`; schema-only diff exits 1
- ✓ `render_summary` engine unit test (direct DiffResult call, with and without schema)
- ✓ `--quiet` produces zero stdout bytes for equal files, row diffs, schema-only diffs
- ✓ `--quiet` exit codes 0/1/2 including schema-only diff
- ✓ `--quiet` does NOT suppress stderr: real malformed-CSV temp file produces `LEFT (<path>):` on
  stderr and exits 2 (per spec's exact format requirement)
- ✓ `-q` without value exits 2 (argparse missing-argument error for `--quotechar`)

## Review findings & resolutions

**Full ledger:** [06-summary-renderer-and-quiet.review.md](06-summary-renderer-and-quiet.review.md)

- Round 1 (APPROVE): 0 blockers, 0 majors, 1 minor, 2 nits. All applied.
  - Minor 1.1: `test_quiet_stderr_on_error` used bad-key path (no path in parens in error message),
    not malformed CSV as spec requires. Fixed: replaced with real UnicodeDecodeError temp-file test
    asserting `'LEFT (' in stderr`.
  - Nit 1.2: Vacuous per-row check in `test_summary_with_schema_change_shows_banner` (fixture has
    no row diffs so assertion never fired; also omitted `-`). Fixed: clean `line[0] in ('-', '~',
    '+')` check matching `test_summary_emits_headline_only`.
  - Nit 1.3: Missing `--quiet` + schema-only diff test. Fixed: added
    `test_quiet_schema_only_diff_exits_1_zero_stdout`.
- Deferred nits: none.

## Things the next task should know

- **`render_summary` signature is `(result, key_names, output_file, show_schema=False)`** —
  identical to `render_human` and `render_jsonl`. The dispatch in `main()` is now:
  `if quiet → None; elif jsonl; elif summary; else human`. Task-07 (docs) documents all three
  non-human formats in the rst page.
- **`--format` choices are now `['human', 'jsonl', 'summary']`** — task-07 should document all
  three in the rst file and man page if applicable.
- **`--quiet` short-form collision** is documented in the epilog. Task-07's rst page should also
  document it so users who try `-q` get a clear hint in the docs.
- **`_render_schema_banner` is shared** by `render_human` and `render_summary`. If task-07 or a
  follow-up task changes the schema banner format, both renderers are affected.
- **`TestCSVDiffSummary` and `TestCSVDiffQuiet`** both inherit from `_CSVDiffOutputMixin`. This is
  now the established pattern for all feature-level test classes in `test_csvdiff.py`.

## Open questions surfaced

None — spec and TDD were unambiguous.
