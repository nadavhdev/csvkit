# Review ledger — task-06

**Task spec:** [done/06-summary-renderer-and-quiet.md](done/06-summary-renderer-and-quiet.md)
**Reviewer:** tech-lead implementation-review capability (a fresh subagent each round)

---

## Round 1 — APPROVE (3 findings: 0 blocker, 0 major, 1 minor, 2 nit)

**Scope:** full review (`git diff feat/csvdiff-jsonl-renderer..HEAD`)
**Reviewer summary:** The task-06 implementation is clean and complete. Both `render_summary` and `--quiet` are delivered correctly: `render_summary` follows the established renderer signature and schema-gating pattern from prior tasks; `--quiet` takes the correct `renderer = None` approach with `if renderer is not None:` guards at both call sites. All acceptance criteria have tests, exit-code parity is preserved format-independently, and the `-q` flag-collision is documented in both epilog and help text. Two nit-level test concerns noted; no blockers or majors.

### Finding 1.1 — [minor] testing — test_quiet_stderr_on_error uses bad-key path, not malformed CSV

**Anchor:** Acceptance criterion 3: "a malformed CSV still produces the `LEFT (<path>): <detail>` message on stderr and exits 2"

**What the reviewer said:** The test uses `-c nonexistent`, which routes through `_resolve_key_names → argparser.error('{}: {}'.format(side, e))` producing `LEFT: ...` (no path in parentheses), not the parse-error format `LEFT (somefile.csv): ...`. Both paths use `argparser.error()` so the stdout-suppression guarantee is verified, but the spec's specific error trigger (malformed CSV) and format are not tested. Task-01's `test_parse_error_real_unicode_error_exits_2` shows the pattern.

**Code it points at:**
```python
# tests/test_utilities/test_csvdiff.py:1639
def test_quiet_stderr_on_error(self):
    """Error message must still appear on stderr even with --quiet."""
    code, stdout_bytes, stderr = self._capture_stderr_for(
        ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'nonexistent', '--quiet'])
    self.assertEqual(code, 2)
    self.assertEqual(stdout_bytes, b'')
    self.assertIn('LEFT', stderr)
```

**Challenge:** None — finding holds. The spec requires the `LEFT (<path>):` format and malformed CSV trigger; the current test exercises a different code path.

**Resolution:** applied  
**Fix:**
```diff
-    def test_quiet_stderr_on_error(self):
-        """Error message must still appear on stderr even with --quiet."""
-        code, stdout_bytes, stderr = self._capture_stderr_for(
-            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'nonexistent', '--quiet'])
-        self.assertEqual(code, 2)
-        self.assertEqual(stdout_bytes, b'')
-        self.assertIn('LEFT', stderr)
+    def test_quiet_stderr_on_error(self):
+        """--quiet must not suppress stderr; malformed CSV produces LEFT (<path>): detail on stderr."""
+        import os
+        import tempfile
+        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as bad_f:
+            bad_f.write(b'id,name\n1,\xff\xfe\n')  # \xff\xfe is invalid UTF-8
+            bad_path = bad_f.name
+        try:
+            code, stdout_bytes, stderr = self._capture_stderr_for(
+                [bad_path, 'examples/diff_b.csv', '--quiet'])
+            self.assertEqual(code, 2)
+            self.assertEqual(stdout_bytes, b'')
+            self.assertIn('LEFT (', stderr)  # LEFT (<path>): <detail> format
+        finally:
+            os.unlink(bad_path)
```

### Finding 1.2 — [nit] testing — per-row check in test_summary_with_schema_change_shows_banner is vacuous

**Anchor:** Acceptance criterion 1: "--format summary prints only the headline line (and schema marker) — no per-row lines"

**What the reviewer said:** The fixture pair (diff_schema_base.csv vs diff_schema_added.csv) has no row diffs, so the assertion `assertFalse(line and line[0] in ('~', '+') and 'id=' in line)` never fires. It also omits `-` and adds an `'id=' in line` guard. Should use the same clean check from `test_summary_emits_headline_only`.

**Code it points at:**
```python
# tests/test_utilities/test_csvdiff.py:1518
        for line in output.splitlines():
            self.assertFalse(line and line[0] in ('~', '+') and 'id=' in line,
                             'Unexpected per-row diff line: {!r}'.format(line))
```

**Challenge:** None — finding holds. The vacuous assertion gives false confidence.

**Resolution:** applied  
**Fix:**
```diff
-            self.assertFalse(line and line[0] in ('~', '+') and 'id=' in line,
-                             'Unexpected per-row diff line: {!r}'.format(line))
+            self.assertFalse(line and line[0] in ('-', '~', '+'),
+                             'Unexpected per-row diff line: {!r}'.format(line))
```

### Finding 1.3 — [nit] testing — no test for --quiet + schema-only diff (exit 1, zero stdout)

**Anchor:** Acceptance criterion: "--quiet preserves the 0/1/2 exit-code contract"; TDD §4b: "--quiet still exits 0/1/2"

**What the reviewer said:** The existing quiet tests cover row diffs (exit 1) and a key error (exit 2). A schema-only diff is the third distinct exit-1 path. The exit-code logic runs after the renderer guard, but a test would make the guarantee explicit.

**Code it points at:** (no existing code — missing test)

**Challenge:** None — holding. Straightforward gap to close.

**Resolution:** applied  
**Fix:** Added `test_quiet_schema_only_diff_exits_1_zero_stdout`.

---

## Outcome

**Final verdict:** APPROVE at round 1  
**Deferred (nits / accepted rebuttals):** none
