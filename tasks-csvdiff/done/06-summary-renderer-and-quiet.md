### `--format=summary` headline-only and `--quiet` (exit-code-only)

**One-liner:** Add the headline-only renderer and the silent mode so callers can use `csvdiff` as a pure CI gate.

**Composes:**
- `-f/--format summary` triggers `render_summary(DiffResult, output_file)` per TDD §4h, emitting only the headline (`"<n> changed, <a> added, <r> removed (of <c> rows compared)"`) and the `! schema changed:` marker when applicable, without per-row lines.
- `--quiet` (long form only — the short `-q` collides with the inherited `-q/--quotechar` and is excluded per the §4a flag-collision audit) suppresses all stdout output; stderr diagnostics still print on errors and `-v/--verbose` tracebacks are unaffected.
- Both modes preserve the 0/1/2 exit-code contract identically to the human renderer.
- `--help` and `epilog` document the `-q` collision and the `--quiet`-only spelling, so users coming from other CLIs don't expect a short form.

**TDD sections addressed:** §4a Command surface (`--format summary`, `--quiet`, `-q` collision resolution), §4b Exit codes (preserved across renderers), §4h `render_summary`.

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]].

**Acceptance criteria:**
- `csvdiff a.csv b.csv -c id --format summary` prints only the headline line (and, if applicable, the `! schema changed:` marker) and exits with the same code as the human renderer would for the same inputs.
- `csvdiff a.csv b.csv -c id --quiet` produces zero bytes on stdout regardless of input, while preserving the 0/1/2 exit-code contract.
- `--quiet` does not suppress stderr; a malformed CSV still produces the `LEFT (<path>): <detail>` (or `RIGHT (<path>): <detail>`) message on stderr and exits 2.
- Attempting `csvdiff ... -q` (short form) is rejected by argparse since `-q` remains bound to the inherited `--quotechar`.
- Tests assert exit codes 0/1/2, stdout content for `--format=summary`, empty stdout for `--quiet`, and the `-q` short-form behavior.
