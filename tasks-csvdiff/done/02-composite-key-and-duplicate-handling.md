### Composite-key matching with `--on-dup={error,first,all}`

**One-liner:** Extend `csvdiff` to accept composite keys (comma-separated columns) and resolve duplicate-key behavior within a single file via the new `--on-dup` flag.

**Composes:**
- `-c/--key` accepts a comma-separated list parsed identically to csvjoin's `-c/--columns` (names or 1-based indices, resolved via `match_column_identifier`), producing a tuple key per row in both LEFT and RIGHT indices.
- New `--on-dup` flag with values `error` (default), `first`, and `all`, controlling behavior when the chosen key is not unique within a single file: `error` fails the run via `argparser.error` (exit 2); `first` keeps the first occurrence and discards later ones; `all` records every occurrence and compares the Cartesian product when the same key appears on both sides.
- `--on-dup=all` carries an O(n·m) blast-radius warning surfaced both in `--help` (next to the flag) and in `epilog`, per TDD §7's "Cartesian explodes" risk.
- Human renderer renders composite keys as `(<v1>,<v2>,…)` per §4h, including in the `~ + -` line prefixes.
- Duplicate keys in `--on-dup=error` mode produce a stderr message naming the file side (LEFT or RIGHT), the duplicated key value, and at least one offending row indicator so the operator can find the row.

**TDD sections addressed:** §4a Command surface (`-c` composite + `--on-dup`), §4g Comparison semantics (composite key, duplicate-key behavior, PRD OD2 resolution), §4h Human renderer (composite key formatting), §7 (`--on-dup=all` blast-radius risk).

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]].

**Acceptance criteria:**
- `csvdiff a.csv b.csv -c "order_id,line_no"` matches rows by the `(order_id, line_no)` tuple; rows with the same `order_id` but different `line_no` are distinct matches.
- Default `--on-dup=error` exits 2 when LEFT or RIGHT contains duplicate key tuples; stderr identifies the side, the duplicated key, and at least one source-row indicator.
- `--on-dup=first` retains the first occurrence per key on each side and proceeds; the diff result reflects only those first occurrences and exits 0 or 1 by the difference state.
- `--on-dup=all` records every occurrence and emits one diff row per Cartesian pair when the same key tuple has duplicates on both sides.
- Human-output row prefixes for composite-key inputs read `key=(<v1>,<v2>)` in the same `~ + -` line format as the single-key case.
- `--help` and `epilog` both name the O(n·m) hazard of `--on-dup=all`.
- Tests cover all three `--on-dup` values, single- and double-sided duplicates, composite keys of arity 2 and 3, and key resolution via both column name and 1-based index.
