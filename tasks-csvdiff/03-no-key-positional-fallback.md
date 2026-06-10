### No-key positional row-by-row comparison

**One-liner:** When `-c` is omitted, compare LEFT row N to RIGHT row N positionally, with surplus rows on the longer side classified as added or removed.

**Composes:**
- When `-c` is absent, the diff engine bypasses the key-index path entirely and walks the two row sequences in parallel by position, comparing on the common column intersection.
- Surplus rows on the longer side: if RIGHT has more rows, the tail is classified `added`; if LEFT has more rows, the tail is classified `removed`.
- Row "key" for output purposes in positional mode is the row index (1-based, matching csvkit's `-l/--linenumbers` convention) so the §8 `key=` slot stays populated and the human grammar stays uniform.
- `--help` and `epilog` warn explicitly about the footgun in TDD §7 ("user runs without `--key` on a re-sorted file"): positional mode will report wide diffs against a re-sorted RIGHT, and `-c` is the fix.
- Schema diff (added in [[04-schema-drift-detection]]) still needs to run in no-key mode; this task does not implement schema diff but must not preclude it (no-key mode and schema diff are orthogonal in the `DiffResult` model from §4f).

**TDD sections addressed:** §4g Comparison semantics (no-key mode / PRD OD1 resolution), §7 (re-sorted-without-key footgun), §8 (positional row key in human grammar).

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]].

**Acceptance criteria:**
- `csvdiff a.csv b.csv` (no `-c`) compares row 1 to row 1, row 2 to row 2, etc., producing per-row `~ + -` lines whose `key=` slot is the 1-based row index.
- When LEFT has more rows than RIGHT, the surplus LEFT rows are reported as `removed`; when RIGHT has more, the surplus is reported as `added`.
- When LEFT and RIGHT have equal length and all rows match on the column intersection, exit code is 0; any field difference or length mismatch exits 1.
- `--help` text and `epilog` warn that positional mode reports spurious diffs against re-sorted input and recommend `-c`.
- Tests cover: equal-length identical, equal-length with mid-stream field changes, LEFT longer, RIGHT longer, both empty, the documented warning text is present, and the row-index key formatting is asserted.
