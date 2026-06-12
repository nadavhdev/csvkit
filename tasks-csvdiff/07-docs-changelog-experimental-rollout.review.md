# Review ledger — task-07

**Task spec:** [done/07-docs-changelog-experimental-rollout.md](done/07-docs-changelog-experimental-rollout.md)
**Reviewer:** tech-lead implementation-review capability (a fresh subagent each round)

---

## Round 1 — REQUEST_CHANGES (2 findings: 0 blocker, 1 major, 1 minor, 0 nit)

**Scope:** full review (all changed/new files in the branch)
**Reviewer summary:** The rst page, CHANGELOG, AUTHORS, and cli.rst updates are well-executed: all required
flags are documented, the experimental banner is present and correct, the exit-code section covers all three
codes, and the Notes section accurately documents every spec-required limitation. One major factual error in
the Exit-0 paragraph will mislead users: the claim "No output is written when both files are identical" is
false — render_human, render_jsonl, and render_summary all unconditionally write a headline/summary line even
when all counts are zero; only --quiet suppresses output. One minor gap: the task spec's Composes section
explicitly lists a schema-drift example among the required examples; the diff includes all others but omits
a concrete schema-drift demonstration.

### Finding 1.1 — [major] docs — Exit-0 section falsely claims "No output is written when both files are identical"

**Anchor:** AC: "The rst page documents the 0/1/2 exit-code contract explicitly, with one paragraph each on … the equivalence → 0 mapping."

**What the reviewer said:** render_human, render_jsonl, and render_summary each unconditionally write a
headline/summary line on every invocation (e.g. "0 changed, 0 added, 0 removed (of 3 rows compared)"). The
only path that truly suppresses all stdout is --quiet (renderer=None). A user running "csvdiff a.csv a.csv"
will see output, directly contradicting this sentence.

**Code it points at:**
```python
# csvkit/utilities/csvdiff.py — render_human (always writes headline)
output_file.write('{} changed, {} added, {} removed (of {} rows compared)\n'.format(
    len(changed), len(added), len(removed), result.compared_count,
))
```

**Challenge:** None — finding holds. render_human unconditionally writes the headline; I verified in the
source. The rst sentence is factually wrong.

**Resolution:** applied
**Fix:**
```diff
-**Exit 0 — files are equivalent.**
-Both the row diff and the schema diff (unless ``--no-schema-check`` is set) are empty.
-No output is written when both files are identical.
+**Exit 0 — files are equivalent.**
+Both the row diff and the schema diff (unless ``--no-schema-check`` is set) are empty.
+The headline still shows all-zero counts (e.g. ``0 changed, 0 added, 0 removed (of 3 rows compared)``).
+Use ``--quiet`` to suppress all output entirely.
```

### Finding 1.2 — [minor] spec-compliance — Missing schema-drift demonstration example

**Anchor:** Composes: "examples for keyed match, no-key positional, composite key, schema-drift, and JSONL output"

**What the reviewer said:** The Composes section lists five required examples including schema-drift. The diff
delivers keyed match, composite key, no-key positional, and JSONL, but no positive worked example showing
what csvdiff emits when schema drift is detected. The Notes section explains the feature in prose, but a
concrete example with expected output gives users a mental model they can verify.

**Challenge:** None — finding holds. The task spec's Composes section explicitly lists schema-drift as one of
the five required examples. The omission is real.

**Resolution:** applied — added a schema-drift example to the Examples section.
**Fix:**
```diff
+Show schema drift when columns are added or removed:
+
+.. code-block:: bash
+
+   csvdiff -c id examples/diff_schema_base.csv examples/diff_schema_added.csv
```

---

## Round 2 — APPROVE — targeted re-review (0 new findings)

**Scope:** targeted re-review — verified prior findings, deep-reviewed round-1 fixes, regression-scanned the rest.

**Prior findings status (reported by reviewer):**
- 1.1 — closed — Exit-0 paragraph now reads "The headline still shows all-zero counts … Use --quiet to suppress all output entirely." — factually correct per render_human/render_jsonl/render_summary source.
- 1.2 — closed — Schema-drift example added; uses diff_schema_base.csv and diff_schema_added.csv which both exist and have an id column, making the command valid.

**Reviewer summary:** Both round-1 findings are cleanly closed. The Exit-0 paragraph now accurately describes
that all renderers unconditionally emit the headline and that --quiet is the suppression path. The schema-drift
example is present and uses fixture files that actually exist. The changed hunks introduce no new issues;
regression risk is zero because no code was touched.

---

## Outcome

**Final verdict:** APPROVE at round 2
**Deferred (nits / accepted rebuttals):** none
