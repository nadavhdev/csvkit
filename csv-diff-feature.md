# Master One-Shot Prompt — `csvdiff`

> **Purpose of this file (for the facilitator, not for Claude):**
> This is the *contrast* artifact for the session. It is a deliberately
> high-quality, comprehensive single prompt — the best "do the whole thing at
> once" instruction we can write. We run it **in the background, ungated**,
> while the session proceeds through the disciplined phased flow. Later we
> compare: even this top-notch prompt, run as a one-shot without phase gates
> and human review, yields lower-quality, less-aligned output than the staged
> path. The point is NOT that the prompt is bad — it is that *discipline beats
> one-shotting*, even with an excellent prompt.
>
> Everything below the line is the prompt to paste into a fresh Claude Code
> session at the csvkit repo root.

---

You are implementing a new feature, end to end, in the **csvkit** repository
(a suite of CLI tools for working with CSV, built on the **agate** data
library). Your task is to add a new command, **`csvdiff`**, that compares two
CSV files semantically and ships at production quality — code, tests, and docs
— consistent with the rest of the suite.

Work autonomously and completely. Produce a single coherent implementation that
a maintainer could merge.

## 1. Ground yourself in the codebase first

Before writing anything, study the existing code and mirror it exactly.
Consistency with the suite is a hard requirement, not a preference.

- Read `csvkit/cli.py` to understand the base class `CSVKitUtility`: how
  `__init__`/`run()` work, what `main()` and `add_arguments()` are for, and the
  full set of **common arguments** the base class already provides
  (`-d/--delimiter`, `-t/--tabs`, `-q/--quotechar`, `-u/--quoting`,
  `-b/--no-doublequote`, `-p/--escapechar`, `-z/--maxfieldsize`,
  `-e/--encoding`, `-L/--locale`, `-S/--skipinitialspace`, `--blanks`,
  `--null-value`, `--date-format`, `--datetime-format`, `--no-leading-zeroes`,
  `-H/--no-header-row`, `-K/--skip-lines`, `-v/--verbose`, `-l/--linenumbers`,
  `--add-bom`, `--zero`, `-V/--version`). **Do not redefine any of these.**
- Read `csvkit/utilities/csvjoin.py` as the closest analog: it is the canonical
  **two-file** tool. Note how it sets `override_flags = ['f']`, takes positional
  `input_paths` (default `['-']`), guards the interactive-tty/no-input case,
  reads each table with `agate.Table.from_csv(...)`, uses
  `match_column_identifier(...)` to resolve user-supplied columns, and writes
  with `table.to_csv(self.output_file, **self.writer_kwargs)`.
- Read `csvkit/utilities/csvsort.py` for the single-file read idiom and how
  `sniff_limit`, `skip_lines`, `column_types=self.get_column_types()`, and
  `**self.reader_kwargs` are passed to `agate.Table.from_csv`.
- Note how values are typed: **agate infers types by default**, so `1` and `1.0`
  compare equal as typed values unless `-I/--no-inference` is set. Decide how
  this affects what counts as "changed" and state your choice.
- Determine csvkit's current exit-code behavior: tools exit 0 on success and use
  `self.argparser.error(...)` (which exits 2) for usage errors. csvkit has **no**
  existing convention for a non-zero "a data condition was found" exit code — so
  if you add one, design it explicitly and document it.

## 2. Implement the feature (full PRD scope)

Create `csvkit/utilities/csvdiff.py` as a `CSVKitUtility` subclass following the
exact pattern (`description`, optional `epilog`, `override_flags`,
`add_arguments()`, `main()`, `launch_new_instance()`). `main()` must follow the
suite's control flow: **validate args → open/read inputs → transform → write.**

Functional scope:

1. **Two-file input.** Accept exactly two positional CSV inputs; support
   STDIN/pipe for one of them as `csvjoin` does; guard the no-input tty case.
2. **Key matching (`--key`).** Accept one or more key columns (resolve via
   `match_column_identifier`). Match rows across the two files by key so the
   diff survives re-sorting and row insertion. Choose a flag that does **not**
   collide with the inherited common flags or csvjoin's `-c`.
3. **Row classification.** Classify every row as **added**, **removed**,
   **changed**, or **unchanged**. For **changed** rows, identify *which columns*
   differ and report before → after per field.
4. **No-key default.** When no key is supplied, do something useful and
   defensible (positional compare, or require a key) — decide and document it.
5. **Schema drift.** Detect and report column-set differences (added / removed /
   reordered) **distinctly** from row differences, surfaced before row diffs.
6. **Exit codes.** Exit 0 when the files are equivalent, a distinct non-zero
   when differences are found, and a separate error exit for misuse (e.g. a key
   column that doesn't exist). Define and document the scheme; account for the
   fact that argparse already uses exit code 2.
7. **Human-readable output** by default: a summary headline (counts) followed by
   marked rows (`~` changed, `+` added, `-` removed), each leading with the key.
8. **Machine-readable output** via a format flag (e.g. JSON and/or CSV) emitting
   a structured record per change.
9. **Inherit all standard input handling** (encoding, delimiter, quoting,
   header options, etc.) from the base class — do not reimplement.
10. **Memory.** If you hold a file in memory (e.g. index file B by key), state
    the tradeoff in the `epilog`, as `csvjoin` does.

Then **register** the command: add the `[project.scripts]` line in
`pyproject.toml`
(`csvdiff = "csvkit.utilities.csvdiff:launch_new_instance"`).

## 3. Test thoroughly — this is not optional

Mirror the existing test conventions exactly. Tests live in
`tests/test_utilities/test_csvdiff.py`, use **`unittest`** (classes, not bare
pytest functions), and subclass the shared helpers in `tests/utils.py`:

```python
from csvkit.utilities.csvdiff import CSVDiff, launch_new_instance
from tests.utils import CSVKitTestCase, EmptyFileTests, stdin_as_string

class TestCSVDiff(CSVKitTestCase, EmptyFileTests):
    Utility = CSVDiff
    default_args = ['examples/dummy.csv', 'examples/dummy.csv']

    def test_launch_new_instance(self): ...   # every tool has this
```

Use the base helpers (`get_output`, `get_output_as_io`, `get_output_as_list`,
`assertRows`, `assertError`) — do not hand-roll stdout capture. Use
`stdin_as_string(...)` to test piped input.

Cover, at minimum, all of the following with dedicated fixtures (add small CSVs
to `examples/`, following the naming style of `join_a.csv`):

- **Identical files** → exit 0, no differences reported.
- **Added rows** → classified as added; correct count; correct exit code.
- **Removed rows** → classified as removed.
- **Changed rows** → classified as changed; correct **per-field** before/after;
  unchanged fields not reported.
- **Unchanged rows** → not reported as changed.
- **Composite key** (two or more key columns).
- **Re-sorted file** → identical data in different row order reports no row
  differences (proves identity-based matching).
- **Schema drift** → added column, removed column, reordered columns, each
  surfaced distinctly from row diffs.
- **Typed vs string** → `1` vs `1.0` (and with `--no-inference`), to pin down
  your "what counts as changed" decision.
- **No-key invocation** → exercises your documented default behavior.
- **Duplicate key within a file** → exercises your documented policy.
- **Bad key** (column that doesn't exist) → correct error via
  `argparser.error`, correct error exit code.
- **Empty file** → via the `EmptyFileTests` mixin.
- **STDIN / pipe** invocation for one input, in addition to named files.
- **Machine-readable output** format → structurally valid, correct content.
- **Exit codes** → assert the exact code for identical / differences / misuse.

Run the full suite with `pytest --cov csvkit` and ensure it passes. Ensure lint
is clean: `flake8 .` (max line length **119**, per `setup.cfg`) and
`isort . --check-only`.

## 4. Document and finalize (definition of done)

- Add per-tool docs at `docs/scripts/csvdiff.rst`, matching the format of
  `docs/scripts/csvjoin.rst`, and link it where the other tools are listed
  (e.g. the tools index/TOC).
- Add a top-of-file entry to `CHANGELOG.rst` in the existing style:
  `-  feat: Add :doc:`/scripts/csvdiff`. ...`.
- Add yourself/contributors to `AUTHORS.rst` if appropriate.
- If you ship a man page, add `man/csvdiff.1` and list it under
  `[tool.setuptools.data-files]` in `pyproject.toml`; otherwise ensure
  `check-manifest` still passes.

## 5. Constraints

- Do **not** add a new heavyweight runtime dependency — build on agate and the
  standard library only.
- Do **not** change the public CLI or behavior of any existing tool.
- Target Python **3.10+**. License is MIT.
- The tool must work from named files **and** from STDIN/pipe, and pass on
  Linux, macOS, and Windows.

Deliver the complete change: new module, registration, tests, fixtures, docs,
and changelog — all consistent with the existing suite, all passing.
