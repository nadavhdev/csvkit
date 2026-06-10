# csvkit — working agreement for Claude

csvkit is a suite of CLI tools for working with CSV, built on the **agate** data
library. **One tool = one command = one module** in `csvkit/utilities/`. When
adding or changing a tool, mirror the existing tools exactly; consistency across
the suite is a hard requirement, not a preference.

## Architecture — how a tool is built

Every tool is a subclass of `CSVKitUtility` (in `csvkit/cli.py`) and lives in
`csvkit/utilities/<toolname>.py`. The pattern, copied from every existing tool:

```python
import agate
from csvkit.cli import CSVKitUtility

class CSVMytool(CSVKitUtility):
    description = 'One-line description shown in --help.'
    epilog = 'Optional notes (e.g. memory caveats).'        # optional
    override_flags = ['f']                                   # only if NOT a single-input tool

    def add_arguments(self):
        # Tool-specific argparse args ONLY. Common args are added by the base class.
        self.argparser.add_argument(...)

    def main(self):
        # Read input via agate, do the work, write to self.output_file.
        ...

def launch_new_instance():
    utility = CSVMytool()
    utility.run()

if __name__ == '__main__':
    launch_new_instance()
```

- **Never call `main()` yourself or implement argument parsing or file
  opening** — the base class `__init__`/`run()` does that. You implement
  `add_arguments()` and `main()` only.
- `run()` opens `self.input_file` and calls `main()`. For multi-file tools,
  set `override_flags = ['f']` and read paths from a positional arg yourself
  (see `csvjoin.py` — it is the closest template for any two-file tool).

## Standard arguments come for free — DO NOT re-add them

`CSVKitUtility._init_common_parser()` already provides: input file(s),
`-d/--delimiter`, `-t/--tabs`, `-q/--quotechar`, `-u/--quoting`,
`-b/--no-doublequote`, `-p/--escapechar`, `-z/--maxfieldsize`, `-e/--encoding`,
`-L/--locale`, `-S/--skipinitialspace`, `--blanks`, `--null-value`,
`--date-format`, `--datetime-format`, `--no-leading-zeroes`,
`-H/--no-header-row`, `-K/--skip-lines`, `-v/--verbose`, `-l/--linenumbers`,
`--add-bom`, `--zero`, `-V/--version`.

**Do not redefine any of these.** Adding a tool-specific flag that collides with
a single-letter common flag is a bug. Check this list (and `csvjoin`'s use of
`-c`) before choosing a flag. To suppress an inherited flag, add its letter to
`override_flags`.

## Reading CSV with agate — the one idiom

Always read input through agate with the inherited kwargs, exactly like every
tool does:

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

- Use `match_column_identifier(table.column_names, name)` (from `csvkit.cli`) to
  resolve a user-supplied column name/index to a column — same as `csvjoin`.
- Write output with `table.to_csv(self.output_file, **self.writer_kwargs)`.
- **agate infers types by default.** Values are typed (a number `1` and `1.0`
  compare equal as typed values), unless `-I/--no-inference` is set. Know which
  you're comparing; do not assume raw strings.

## How `main()` is structured — the control-flow convention

Every tool's `main()` follows the same order (see `csvjoin.py`):

1. **Validate first.** Check arg combinations at the top and reject bad input via
   `self.argparser.error(...)` *before* doing any work (e.g. csvjoin rejects an
   outer join with no join column up front).
2. **Open / read.** Open input file(s); read into agate `Table`(s) with the
   idiom above; `close()` each file after reading.
3. **Transform.** Do the actual work on the table(s) in memory.
4. **Write.** Emit via `table.to_csv(self.output_file, **self.writer_kwargs)`
   (or, for non-CSV output tools, write to `self.output_file` directly).

Do not interleave reading and writing, and do not do work before validation.

## STDIN / pipe behavior — required for every tool

CI exercises **every** tool both as `tool < file` and `printf ... | tool`. A new
tool must work from piped/redirected STDIN, not only named-file arguments. For a
**multi-input** tool, follow `csvjoin`: positional `input_paths` with
`default=['-']`, set `override_flags = ['f']`, and guard the
interactive-tty-with-no-input case:

```python
if isatty(sys.stdin) and self.args.input_paths == ['-']:
    self.argparser.error('You must provide an input file or piped data.')
```

How a two-input tool resolves "one input came from stdin" is a real design point
— decide it explicitly and test both invocation styles.

## Errors and exit codes

- Validate args inside `main()` and report user errors via
  `self.argparser.error('message')` — it prints to stderr and exits **2**.
- Normal success exits **0** implicitly. csvkit tools do **not** currently use a
  non-zero "result" exit code to signal a data condition; if a task requires one
  (e.g. "differences found"), that is a **new pattern** — call it out, design it
  explicitly via `sys.exit(code)`, and document the codes. Do not invent it
  silently.
- Raise the existing exceptions in `csvkit/exceptions.py` where they fit
  (`ColumnIdentifierError`, `RequiredHeaderError`).

## Registering the tool

A new tool is not usable until registered. Add a line to **`[project.scripts]`
in `pyproject.toml`**:

```
csvmytool = "csvkit.utilities.csvmytool:launch_new_instance"
```

If shipping a man page, also add `man/csvmytool.1` to
`[tool.setuptools.data-files]`.

## Testing — required, mirror the existing tests

Tests live in `tests/test_utilities/test_<toolname>.py` and use **`unittest`**
(classes, not bare pytest functions). Subclass the helpers in `tests/utils.py`:

```python
from csvkit.utilities.csvmytool import CSVMytool, launch_new_instance
from tests.utils import CSVKitTestCase, EmptyFileTests

class TestCSVMytool(CSVKitTestCase, EmptyFileTests):
    Utility = CSVMytool
    default_args = ['examples/dummy.csv', '-']

    def test_launch_new_instance(self): ...   # include this; every tool has it
```

- Use the base helpers: `get_output`, `get_output_as_io`, `assertRows`,
  `assertError` — do not hand-roll stdout capture.
- Put test fixtures (small CSVs) in **`examples/`**, following names like
  `join_a.csv`. Reuse existing fixtures where possible.
- Cover the empty-file case via the `EmptyFileTests` mixin and add cases for
  every new behavior and every error path.

## Commands — the exact toolchain (no Makefile; CI is the source of truth)

Install for development: `pip install .[test]`

| Purpose | Command |
|---------|---------|
| Run tests with coverage | `pytest --cov csvkit` |
| Lint | `flake8 .` |
| Import order | `isort . --check-only` (apply with `isort .`) |
| Packaging manifest | `check-manifest` |

Style: **flake8 with `max-line-length = 119`** (in `setup.cfg`); isort line
length 119 (in `pyproject.toml`). CI runs `flake8 .`, `isort . --check-only`,
and `check-manifest` (the **Lint** workflow) and `pytest --cov csvkit` across
**macOS / Windows / Linux** on **Python 3.10–3.14 and pypy-3.11** (the **CI**
workflow). Coverage is uploaded to codecov with `fail_ci_if_error: true`.

## Definition of done (the PR checklist)

A change is done only when ALL hold:

1. Tool follows the `CSVKitUtility` pattern and `main()` flow above; no re-added
   common flags; works from named files **and** STDIN/pipe.
2. Registered in `pyproject.toml` `[project.scripts]`.
3. Tests added in `tests/test_utilities/`, mirroring existing tests; the full
   suite passes locally: `pytest --cov csvkit`. Add fixtures to `examples/`.
4. Lint clean: `flake8 .` and `isort . --check-only` both pass (line length
   119); `check-manifest` passes (update `MANIFEST.in` if you add data files).
5. Per-tool docs added at `docs/scripts/<toolname>.rst` matching
   `docs/scripts/csvjoin.rst`, and linked where the other tools are listed.
6. A `CHANGELOG.rst` entry at the top in the existing style:
   `-  feat: :doc:`/scripts/csvmytool` ...` (or `fix:`).
7. New contributors added to `AUTHORS.rst`.
8. If a man page is shipped, `man/csvmytool.1` is added and listed in
   `pyproject.toml` `[tool.setuptools.data-files]`.

## Guardrails — do not

- Do **not** add a new heavyweight runtime dependency. Build on agate and the
  standard library. (Test-only deps go under `[project.optional-dependencies]`.)
- Do **not** change the public CLI/behavior of any existing tool while adding a
  new one.
- Do **not** load whole files into memory silently for a tool that claims to
  scale; if memory is bounded by a design choice, state it in `epilog` (see
  `csvjoin`'s epilog as precedent).
- Do **not** guess at conventions — if unsure how something is done, read the
  nearest existing tool (`csvjoin` for multi-file, `csvsort` for single-file)
  and match it.

Target Python is **3.10+**. License is **MIT**.
