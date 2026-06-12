# Review ledger — task-07

**Task spec:** [done/07-docs-changelog-experimental-rollout.md](done/07-docs-changelog-experimental-rollout.md)
**Reviewer:** tech-lead implementation-review capability (a fresh subagent each round)

---

## Round 1 — APPROVE (2 findings: 0 blocker, 0 major, 0 minor, 2 nit)

**Scope:** full review (`git diff feat/csvdiff-summary-quiet..HEAD`)
**Reviewer summary:** Task-07 delivers all required release artifacts cleanly: the csvdiff.rst page exists, follows the csvjoin.rst structural template, documents all five required design choices and limitations, carries the experimental Sphinx warning banner, and includes all required examples. The CHANGELOG entry correctly calls out the new 0/1/2 exit-code contract, AUTHORS is updated, the docs toctree and daff bullet in cli.rst are correctly updated, and all verify checks pass. Two nits are filed; no blockers or majors.

### Finding 1.1 — [nit] docs — Epilog experimental notice less specific than RST banner
**Anchor:** AC7: 'any drift between rst and epilog is reconciled before merge'
**What the reviewer said:** The RST warning says "flags, output format, and exit codes may change in 2.4.x based on user feedback," while the epilog said only "(Experimental - interface may change.)" — no mention of 2.4.x or what specifically may change. The two are consistent in spirit but the epilog lacks the specificity the RST provides.

**Code it points at:**
```python
# csvkit/utilities/csvdiff.py:354
        '(Experimental - interface may change.) '
```

**Challenge:** None — finding holds. AC7 explicitly requires epilog/rst reconciliation.

**Resolution:** applied
**Fix:**
```diff
-        '(Experimental - interface may change.) '
+        '(Experimental — flags, output format, and exit codes may change in 2.4.x.) '
```

### Finding 1.2 — [nit] docs — Example description 'ignoring row-level differences' is ambiguous
**Anchor:** Task spec Composes: 'examples for … schema-drift'
**What the reviewer said:** "Detect schema drift only, ignoring row-level differences that involve a new column" is misleading — it implies the user is actively suppressing something, when in fact this is the default behavior (row comparison narrows to the common column intersection by design).

**Code it points at:**
```rst
# docs/scripts/csvdiff.rst (schema-drift example)
Detect schema drift only, ignoring row-level differences that involve a new column:
```

**Challenge:** None — finding holds. The wording would confuse a first-time user looking for a flag to suppress row diffs.

**Resolution:** applied
**Fix:**
```diff
-Detect schema drift only, ignoring row-level differences that involve a new column:
+Detect a schema change (added or removed columns) — new columns appear in the schema banner,
+not as per-row differences, because row comparison narrows to the common column intersection:
```

---

## Round 2 — APPROVE — targeted re-review (1 new finding)

**Scope:** targeted re-review — verified prior findings, deep-reviewed round-1 fixes, regression-scanned the rest.
**Prior findings status (reported by reviewer):**
- 1.1 — closed — csvdiff.py line 354 now reads '(Experimental — flags, output format, and exit codes may change in 2.4.x.) '
- 1.2 — closed — docs/scripts/csvdiff.rst lines 165-166 read the two-line revised description

**Reviewer summary:** Both round-1 nits are cleanly closed. All task-07 acceptance criteria are delivered. One new minor finding: man/csvdiff.1 not committed or listed in pyproject.toml, inconsistent with the project's 14-for-14 pattern across all other tools.

### Finding 2.1 — [minor] conventions — man/csvdiff.1 not committed or listed in pyproject.toml
**Anchor:** CLAUDE.md DoD item 8; project pattern: all 14 existing tools have pre-built man pages
**What the reviewer said:** Every existing csvkit tool has a pre-built man page committed to man/ and listed in pyproject.toml [tool.setuptools.data-files]. Users who install from a wheel or sdist would not have `man csvdiff`, unlike all peer tools.

**Code it points at:**
```toml
# pyproject.toml [tool.setuptools.data-files]
"share/man/man1" = [
    "man/csvclean.1",
    "man/csvcut.1",
    # csvdiff.1 absent
    "man/csvformat.1",
    ...
```

**Challenge:** None — finding holds. The project convention is clear: all tools have man pages distributed.

**Resolution:** applied
**Fix:** Created `man/csvdiff.1` (hand-written following csvjoin.1 format — Sphinx unavailable in this environment); added `"man/csvdiff.1"` to pyproject.toml data-files in alphabetical position.

---

## Outcome

**Final verdict:** APPROVE at round 2
**Deferred (nits / accepted rebuttals):** none
