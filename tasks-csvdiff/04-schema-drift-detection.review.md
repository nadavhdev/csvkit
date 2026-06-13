# Review ledger — task-04

**Task spec:** [done/04-schema-drift-detection.md](done/04-schema-drift-detection.md)
**Reviewer:** tech-lead implementation-review capability (a fresh subagent each round)

---

## Round 1 — APPROVE (1 finding: 0 blocker, 0 major, 1 minor, 0 nit)

**Scope:** full review (working-tree diff vs `feat/csvdiff-positional-fallback` + 6 untracked fixtures)
**Reviewer summary:** Schema-drift detection is implemented cleanly and matches the task spec and cited TDD sections. The `_compute_schema_delta` extraction deduplicates the block both compute functions previously copied, directly closing task-03's deferred nit; `schema_active = not no_schema_check and not no_header_row` is threaded consistently into both the banner rendering and the exit-code decision. Every acceptance criterion has at least one test, the tdd_correlation map audits clean, and added/removed column ordering and -H/--no-schema-check interactions all behave as specified. The only issue is one CLI test that passes vacuously; the behavior it targets is robustly covered elsewhere, so it does not block.

### Finding 1.1 — [minor] testing — `test_added_column_not_reported_in_row_diffs` asserts nothing
**Anchor:** Acceptance criterion 2 — "that column is not reported in row diffs (rows differ only on the intersection)"
**What the reviewer said:** BASE (id,name,price) and ADDED (id,name,price,region) share identical values on the common columns, so with `-c id` there are zero changed/added/removed row-diff lines. `_row_diff_lines(output)` returns `[]` and the `for line in ...: assertNotIn('region', line)` body never executes, so the test passes regardless of whether the added column leaks into row diffs. The criterion is genuinely exercised by the engine test `test_added_column_excluded_from_changed_row_fields`, so this is not a coverage gap — but the CLI-level test gives false confidence. Use a fixture pair where the common columns also differ on a row so the assertion actually runs.

**Code it points at:**
```python
# tests/test_utilities/test_csvdiff.py
def test_added_column_not_reported_in_row_diffs(self):
    """The added column appears only in the banner, never as per-row noise."""
    output = self.get_output([self.BASE, self.ADDED, '-c', 'id'])
    for line in self._row_diff_lines(output):
        self.assertNotIn('region', line)
```

**Challenge:** None — finding holds. Simulated per Step A: BASE and ADDED match on every common column under `-c id`, so the diff has 0 row-diff lines; `_row_diff_lines` is empty and the assertion loop never runs. The test passes vacuously.

**Resolution:** applied
**Fix:**
```diff
+ # examples/diff_schema_added_changed.csv  (new fixture: extra `region` col AND a changed price on row 2)
+ id,name,price,region
+ 1,apple,1,west
+ 2,banana,9,east

  def test_added_column_not_reported_in_row_diffs(self):
      """The added column appears only in the banner, never as per-row noise."""
-     output = self.get_output([self.BASE, self.ADDED, '-c', 'id'])
-     for line in self._row_diff_lines(output):
-         self.assertNotIn('region', line)
+     output = self.get_output([self.BASE, self.ADDED_CHANGED, '-c', 'id'])
+     row_lines = self._row_diff_lines(output)
+     # A common column changed → a real '~' line exists; the added column must not appear in it.
+     self.assertTrue(any(ln.startswith('~') for ln in row_lines))
+     for line in row_lines:
+         self.assertNotIn('region', line)
```

---

## Round 2 — APPROVE — targeted re-review (0 new findings)

**Scope:** targeted re-review — verified prior finding 1.1, deep-reviewed the changed hunk (fixture + test rewrite), regression-scanned the rest.
**Prior findings status (reported by reviewer):**
- 1.1 — closed — Test now uses BASE vs ADDED_CHANGED (price differs on id=2) and asserts a '~' line exists, making the loop non-vacuous; criterion genuinely exercised at CLI level.

**Reviewer summary:** Round 1's sole finding (1.1, vacuous test) is properly closed: the rewritten test_added_column_not_reported_in_row_diffs now diffs BASE against the new diff_schema_added_changed.csv fixture, which differs on the common 'price' column for id=2, producing a real '~' changed line. The added assertTrue(any(ln.startswith('~'))) guards against vacuity, and the renderer confirms changed rows use the '~' prefix, so the assertion is sound. The added 'region' column is added-only and never enters compare_cols, so it cannot appear in any row-diff line. No production code changed; the delta is fixture + test only and is clean.

(No new findings.)

---

## Outcome

**Final verdict:** APPROVE at round 2
**Deferred (nits / accepted rebuttals):** none
