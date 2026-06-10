# csvdiff — task breakdown

**Source TDD:** `../TDD-csvdiff.md` (in this repo root)
**Date of breakdown:** 2026-06-10
**Task count:** 7

## Tasks (in dependency order)

1. [Walking-skeleton `csvdiff`: keyed match, human output, full exit-code contract](01-walking-skeleton-keyed-csvdiff.md) — minimal end-to-end tool that retires the riskiest unknowns (new 0/1/2 exit-code pattern incl. parse-error→2 wrap, all four invocation styles, typed-vs-raw comparison, `--ignore`). **Depends on:** none.
2. [Composite-key matching with `--on-dup={error,first,all}`](02-composite-key-and-duplicate-handling.md) — composite-tuple keys and the duplicate-key policy. **Depends on:** 1.
3. [No-key positional row-by-row comparison](03-no-key-positional-fallback.md) — the PRD OD1 fallback when `-c` is omitted. **Depends on:** 1.
4. [Schema-drift detection: added / removed / reordered columns](04-schema-drift-detection.md) — `SchemaDelta`, the `! schema changed:` banner, `--no-schema-check`, and `-H` suppression (resolves OQ7). **Depends on:** 1.
5. [Machine-readable `--format=jsonl` renderer](05-jsonl-renderer.md) — JSONL event stream (summary → optional schema → row events). **Depends on:** 1, 4.
6. [`--format=summary` headline-only and `--quiet` (exit-code-only)](06-summary-renderer-and-quiet.md) — the two "less output" modes for CI use. **Depends on:** 1.
7. [Documentation, changelog entry, AUTHORS update, and experimental rollout](07-docs-changelog-experimental-rollout.md) — release-wide cross-cutting closer (rst page, CHANGELOG, AUTHORS, experimental banner). **Depends on:** 1, 2, 3, 4, 5, 6.

## Dependency graph

```
              ┌─> 02 (composite key + --on-dup) ──┐
              │                                    │
              ├─> 03 (no-key positional) ──────────┤
              │                                    │
01 (skeleton)─┼─> 04 (schema-drift) ──┬────────────┤
              │                       │            │
              │                       └─> 05 ──────┤  (JSONL needs 1 + 4)
              │                                    │
              └─> 06 (summary + --quiet) ──────────┤
                                                   │
                                                   v
                                              07 (docs + rollout)
```

Tasks 2, 3, 4, 6 are fully independent and can be picked up in parallel after task 1 lands. Task 5 fans in on tasks 1 and 4. Task 7 closes the release once features have stabilized.

## Open questions from the TDD

Per the skill's rules, unresolved open questions do **not** become tasks — they either block the affected sections or are folded into acceptance criteria where the TDD itself recommended a behavior. **No task is blocked by an open question for this breakdown.** Specifically:

- **OQ1 — Exit-code parity audit across csvkit.** Deferred follow-up after csvdiff lands; not a csvdiff task. Track separately.
- **OQ2 — Whitespace/unicode normalization.** Deferred follow-up; v1 ships with no normalization, documented behavior. Track separately.
- **OQ3 — Key-value formatting in human output.** Folded into task 1's acceptance criteria (agate string-cast verified for int/decimal/date).
- **OQ4 — Streaming / sorted-merge backend.** Out of scope for v1 per §2; not a task.
- **OQ5 — Long changed-row line wrapping.** Deferred follow-up; v1 ships single-line. Track separately.
- **OQ6 — Per-file encoding override.** Out of scope per the TDD's recommendation; documented as a limitation in task 4 / task 7.
- **OQ7 — Schema diff under `-H/--no-header-row`.** TDD recommends "suppress schema diff entirely under `-H`"; folded into task 4's acceptance criteria.
- **OQ8 — `_open_input_file` reconfigure called twice.** TDD recommends "verify safe + add a test"; folded into task 1's acceptance criteria via the four-invocation-style suite.

## Notes for the engineer picking this up

- **Task 1 is non-trivial.** It's deliberately the largest task because the walking-skeleton mindset (per the breakdown skill) front-loads the riskiest unknowns — for this TDD that means the new exit-code contract, the parse-error→exit-2 edge case, and the full four-invocation-style stdin matrix. Resist the urge to split task 1 into "scaffolding" and "behavior"; that would produce a non-shippable scaffolding ticket.
- **The "if only task 1 ships" test passes.** After task 1, csvkit gets a working keyed `csvdiff` with the full exit-code contract — usable in CI as a row-equivalence gate. Everything after broadens coverage.
- **`--ignore` is folded into task 1** rather than being its own task — it's a small filter on the comparison set that the engine has to know about up front, and pulling it out would create a stub task.
- **Perf-smoke (the §6 scalability NFR) is folded into task 1** rather than being a standalone task — per the breakdown skill, NFRs ride with the feature that owns them.
- **Task 7 is genuinely cross-cutting** (one rst page that spans every flag, one CHANGELOG entry, one banner) and earns its own slot; per-feature help/epilog wording lives in the feature tasks.
