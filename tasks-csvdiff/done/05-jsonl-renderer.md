### Machine-readable `--format=jsonl` renderer

**One-liner:** Add a JSONL output mode that emits one JSON object per event (summary header, optional schema event, then one row event per diff) for downstream tooling.

**Composes:**
- New `-f/--format jsonl` value triggering `render_jsonl(DiffResult, output_file)` per TDD §4h, using stdlib `json.dumps(..., default=csvkit.cli.default_str_decimal)` so Decimal / date types serialize the same way csvjson already serializes them — no new runtime dependency, consistent with the CLAUDE.md "no new heavyweight runtime dep" rule and §4i.
- Event sequence per §4h: first a `{"event":"summary", ...}` line, then a `{"event":"schema", ...}` line iff the schema delta is non-empty, then one `{"event":"row", "status":..., "key":..., "fields":...}` line per row diff in `DiffResult`'s stable order.
- Row events match the §4h shape: `key` is a JSON object keyed by key-column name for keyed mode (a `{"row": <index>}` object in no-key positional mode from [[03-no-key-positional-fallback]]); `fields` for `changed` carries `{col: {"left": ..., "right": ...}}`; for `added`/`removed` carries the full row keyed by column name with the missing side implicit.
- Output is single-line-per-event (no embedded newlines), so consumers can read line-by-line — JSONL chosen for streamability per the TDD's resolved triage question.
- `--quiet` (added by [[06-summary-renderer-and-quiet]]) must suppress JSONL stdout the same way it suppresses human output; this task does not implement `--quiet` but its renderer must not bypass the stdout pipe.

**TDD sections addressed:** §4a (`--format jsonl`), §4h `render_jsonl` (event grammar), §4i External dependencies (stdlib `json`, `default_str_decimal` reuse), §0 (no new heavyweight dep).

**Depends on:** [[01-walking-skeleton-keyed-csvdiff]], [[04-schema-drift-detection]].

**Acceptance criteria:**
- `csvdiff a.csv b.csv -c id --format jsonl` emits one JSON object per line on stdout, parseable line-by-line by stdlib `json.loads` without buffering the whole output first.
- The first emitted line is always the `summary` event with fields `compared`, `changed`, `added`, `removed`, `schema_changed`.
- When the schema delta is non-empty, exactly one `schema` event follows the summary with `added_columns`, `removed_columns`, and `reordered` fields.
- Each row diff produces one `row` event: `status` is one of `added`/`removed`/`changed`; `key` is a JSON object keyed by key-column name (a `{"row": <index>}` object in no-key positional mode); `fields` matches the §4h shape for each status.
- Decimal and date values round-trip through `default_str_decimal` rather than raising `TypeError` from `json.dumps`.
- Exit codes 0/1/2 match the human renderer's contract for the same inputs.
- Tests cover: equal-files (summary event with all-zero counts only), row-only diff, schema-only diff, combined, composite-key event shape, no-key positional event shape, and Decimal/date serialization.
