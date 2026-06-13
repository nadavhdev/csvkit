# task-07 — done

**Task spec:** [done/07-docs-changelog-experimental-rollout.md](done/07-docs-changelog-experimental-rollout.md)
**PR:** https://github.com/nadavhdev/csvkit/pull/12
**Commit:** 11298fd
**Completed:** 2026-06-13
**Branch:** docs/csvdiff-docs-rollout (off feat/csvdiff-summary-quiet)

## What was built

All user-facing release artifacts that no single feature task owned are now in place.
`docs/scripts/csvdiff.rst` documents every flag, the three-exit-code contract (new for
csvkit), all five spec-required limitation topics, and five worked examples including a
schema-drift demonstration. `docs/cli.rst` registers csvdiff in the Processing toctree
and replaces the "consider daff" pointer with one that leads with the built-in tool.
`CHANGELOG.rst` gets a 2.3.0 TBD entry with an explicit callout about the exit-code
contract change. `AUTHORS.rst` adds `nhoze`. No Python code was touched.

## Files changed

- `docs/scripts/csvdiff.rst` — created; full tool docs: experimental warning banner, synopsis
  (usage block), per-flag reference with help text, Exit codes section (three paragraphs,
  one per code), Notes section (typed comparison, in-memory bound, rename-as-removed+added,
  single-encoding limitation, -H schema suppression, no-key positional footgun), Examples section
  (keyed match, composite key, no-key positional, schema-drift, JSONL, CI script pattern)
- `docs/cli.rst` — modified; added `scripts/csvdiff` to Processing toctree (alphabetically between
  csvcut and csvgrep); updated the Output section's "To diff CSVs" bullet to reference csvdiff first
- `CHANGELOG.rst` — modified; prepended 2.3.0 TBD section with feat entry and exit-code callout
- `AUTHORS.rst` — modified; appended `* nhoze`
- `tasks-csvdiff/07-docs-changelog-experimental-rollout.review.md` — review ledger (2 rounds)
- `tasks-csvdiff/07-docs-changelog-experimental-rollout.state.json` — pipeline state

## Decisions & departures from spec

- **`.. warning::` over `.. note::`**: chose `warning` for the experimental banner to match the
  higher urgency of "this may break your CI scripts." csvkit uses both directives; `warning` is
  the stronger one and is appropriate here since the exit-code contract is new and scripts may
  depend on it.
- **"consider daff" bullet updated rather than removed**: the bullet in docs/cli.rst was changed
  to "use csvdiff (built-in) or daff for a patch-based approach." Removing daff entirely would
  break existing external links to that bullet; updating it points users to the built-in first
  while preserving the reference for the patch-generation use case csvdiff does not cover.
- **Five examples not four**: the CI-script pattern ("if ! csvdiff --quiet; then…") was added as
  a sixth example beyond the spec's five because it directly demonstrates the exit-code contract
  in a real-world shell pattern — the most important new behavior for downstream script authors.
  This is additive and does not deviate from spec.
- **Epilog reconciliation**: the existing epilog in `csvdiff.py` already covers all required
  topics (experimental status, typed comparison, in-memory bound, positional footgun, schema
  banner, -H suppression, --on-dup=all warning, --quiet/-q collision). No epilog changes were
  needed; the rst page is the expanded version of the same content.

## Test coverage

Not applicable — this task is docs-only. No test files added or modified.

The round-1 review caught one factual error:
- ✗ (pre-fix) Exit-0 paragraph claimed "No output is written when both files are identical" — false;
  all renderers unconditionally write the headline counts line.
- ✓ (post-fix) Corrected to "The headline still shows all-zero counts … Use --quiet to suppress
  all output entirely."

## Review findings & resolutions

**Full ledger:** [07-docs-changelog-experimental-rollout.review.md](07-docs-changelog-experimental-rollout.review.md)

- Round 1 (REQUEST_CHANGES): 0 blockers, 1 major, 1 minor. Both applied.
  - Major 1.1: Exit-0 paragraph falsely claimed "No output is written when both files are identical."
    Fixed: replaced with accurate description of the all-zero headline + reference to --quiet.
  - Minor 1.2: Missing schema-drift example (task spec Composes lists it among five required).
    Fixed: added `csvdiff -c id examples/diff_schema_base.csv examples/diff_schema_added.csv`.
- Round 2 (APPROVE): 0 new findings; both prior findings confirmed closed.
- Deferred nits: none.

## Things the next task should know

- **`docs/scripts/csvdiff.rst` is the canonical user reference for the csvdiff contract.** If any
  flag changes, output format changes, or exit-code semantics change in a follow-up task, update
  this file. The Notes section is the place for behavioral caveats.
- **The `.. warning::` experimental banner** (lines 3–8 of csvdiff.rst) should be removed when
  csvdiff is stabilized per TDD §8 Phase 3. At that point also update CHANGELOG with a "stable"
  entry and remove the epilog's "(Experimental - interface may change.)" sentence.
- **CHANGELOG version is 2.3.0 TBD** — fill in the release date when the release is cut.
- **The daff bullet in docs/cli.rst** now says "use csvdiff (built-in) or daff." Once csvdiff is
  GA and stabilized, consider removing the daff reference entirely.
- **Authors list**: `nhoze` is now in `AUTHORS.rst`. No further ACTION needed there.

## Open questions surfaced

None.
