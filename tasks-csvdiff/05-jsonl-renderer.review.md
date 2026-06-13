# Review ledger — task-05

**Task spec:** [done/05-jsonl-renderer.md](done/05-jsonl-renderer.md)
**Reviewer:** tech-lead implementation-review capability (a fresh subagent each round)

---

## Round 1 — REQUEST_CHANGES (4 findings: 0 blocker, 2 major, 1 minor, 1 nit)

**Scope:** full review (`git diff feat/csvdiff-schema-drift..HEAD`)
**Reviewer summary:** The core implementation is correct and well-structured: render_jsonl honors §4h exactly, the -f/--format flag is wired cleanly, schema gating mirrors render_human, prior decisions from tasks 03 and 04 are all respected, and no new runtime dependencies were introduced. Two majors block the merge: the test class re-implements get_output and _exit_code_for verbatim instead of inheriting from _CSVDiffOutputMixin, and the Decimal/date serialization test uses -I which bypasses type inference so default_str_decimal is never invoked.

### Finding 1.1 — [major] testing — TestCSVDiffJSONL re-implements get_output and _exit_code_for instead of inheriting from _CSVDiffOutputMixin

**Anchor:** task-02 done.md: `_CSVDiffOutputMixin` extracted to avoid `get_output`/`_exit_code_for` copy-paste
**What the reviewer said:** The two methods defined on `TestCSVDiffJSONL` are byte-for-byte identical to those on `_CSVDiffOutputMixin`. That mixin was extracted in task-02 round 1 as the fix for this exact duplication. Every other feature-level test class (`TestCSVDiffCompositeKey`, `TestCSVDiffOnDup`, `TestCSVDiffPositional`, `TestCSVDiffSchema`) inherits from `_CSVDiffOutputMixin, CSVKitTestCase` and declares `Utility = CSVDiff`. `TestCSVDiffJSONL` should do the same.

**Code it points at:**
```python
# tests/test_utilities/test_csvdiff.py (TestCSVDiffJSONL)
def get_output(self, args):
    output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
    utility = CSVDiff(args, output_file)
    try:
        utility.run()
    except SystemExit:
        pass
    output = output_file.buffer.getvalue().decode('utf-8')
    output_file.close()
    return output

def _exit_code_for(self, args):
    output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
    utility = CSVDiff(args, output_file)
    try:
        utility.run()
        return 0
    except SystemExit as exc:
        return exc.code
    finally:
        output_file.close()
```

**Challenge:** None — finding holds. These are identical to `_CSVDiffOutputMixin`.

**Resolution:** applied
**Fix:**
```diff
-class TestCSVDiffJSONL(CSVKitTestCase):
+class TestCSVDiffJSONL(_CSVDiffOutputMixin, CSVKitTestCase):
     """Tests for --format=jsonl (render_jsonl)."""
+    Utility = CSVDiff

-    def get_output(self, args):
-        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
-        utility = CSVDiff(args, output_file)
-        try:
-            utility.run()
-        except SystemExit:
-            pass
-        output = output_file.buffer.getvalue().decode('utf-8')
-        output_file.close()
-        return output
-
-    def _exit_code_for(self, args):
-        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
-        utility = CSVDiff(args, output_file)
-        try:
-            utility.run()
-            return 0
-        except SystemExit as exc:
-            return exc.code
-        finally:
-            output_file.close()
```

### Finding 1.2 — [major] testing — test_decimal_and_date_serialization uses -I, so default_str_decimal is never invoked

**Anchor:** AC5: Decimal and date values round-trip through `default_str_decimal` rather than raising `TypeError` from `json.dumps`
**What the reviewer said:** With `-I` all agate field values are plain Python strings — `json.dumps` serializes them natively without calling `default_str_decimal`. The criterion requires that typed Decimal/date values go through `default_str_decimal`. A correct test must run WITHOUT `-I` on a fixture where a numeric field differs, so agate infers values as `Decimal`. `diff_a.csv` vs `diff_b.csv` (with price change) already produces a changed row with a Decimal price — running without `-I` and asserting the changed event's price field is a string covers the criterion.

**Code it points at:**
```python
# tests/test_utilities/test_csvdiff.py
def test_decimal_and_date_serialization(self):
    output = self.get_output([
        'examples/diff_types_a.csv', 'examples/diff_types_b.csv',
        '-c', 'id', '-I', '--format', 'jsonl',  # -I makes all values strings!
    ])
```

**Challenge:** None — finding holds. `-I` defeats the test's purpose.

**Resolution:** applied — rewrote to use `diff_a.csv` vs `diff_b.csv` without `-I`, asserting price value is a string (agate Decimal → `default_str_decimal` → str).
**Fix:**
```diff
-    def test_decimal_and_date_serialization(self):
-        # diff_types_a vs diff_types_b with -I (raw strings) forces a type mismatch
-        # that exercises non-string values; even with inference, Decimal fields go
-        # through default_str_decimal — verify no TypeError is raised and output parses.
-        output = self.get_output([
-            'examples/diff_types_a.csv', 'examples/diff_types_b.csv',
-            '-c', 'id', '-I', '--format', 'jsonl',
-        ])
-        # Must parse without error — default_str_decimal handles Decimal/date
-        events = self._parse_jsonl(output)
-        self.assertTrue(len(events) >= 1)
+    def test_decimal_serialization_via_default_str_decimal(self):
+        # Without -I, agate infers the price column as Decimal; render_jsonl must
+        # serialize via default_str_decimal (not raise TypeError).
+        output = self.get_output([
+            'examples/diff_a.csv', 'examples/diff_b.csv',
+            '-c', 'id', '--format', 'jsonl',
+        ])
+        events = self._parse_jsonl(output)
+        changed = [e for e in events if e.get('status') == 'changed']
+        self.assertTrue(len(changed) > 0)
+        # price is inferred as Decimal — default_str_decimal serializes it as a string
+        for ev in changed:
+            if 'price' in ev['fields']:
+                self.assertIsInstance(ev['fields']['price']['left'], str)
+                self.assertIsInstance(ev['fields']['price']['right'], str)
```

### Finding 1.3 — [minor] testing — no test asserts the value of the 'compared' field in the summary event

**Anchor:** AC2: first emitted line is always the summary event with fields `compared`, `changed`, `added`, `removed`, `schema_changed`
**What the reviewer said:** `test_equal_files_emits_summary_only` checks `changed`, `added`, `removed`, `schema_changed` but skips `compared`. Adding `assertEqual(ev['compared'], <expected>)` to at least one test closes the gap.

**Code it points at:**
```python
def test_equal_files_emits_summary_only(self):
    ...
    self.assertEqual(ev['changed'], 0)
    self.assertEqual(ev['added'], 0)
    self.assertEqual(ev['removed'], 0)
    self.assertFalse(ev['schema_changed'])
    # 'compared' is never checked
```

**Challenge:** None — finding holds.

**Resolution:** applied — added `self.assertEqual(ev['compared'], 3)` (diff_a.csv has 3 data rows).
**Fix:**
```diff
     self.assertEqual(ev['changed'], 0)
     self.assertEqual(ev['added'], 0)
     self.assertEqual(ev['removed'], 0)
     self.assertFalse(ev['schema_changed'])
+    self.assertEqual(ev['compared'], 3)
```

### Finding 1.4 — [nit] code-quality — render\_jsonl makes three filter passes over row\_diffs to compute counts, then a fourth pass to emit events

**Anchor:** null
**What the reviewer said:** A single counter pass before the emit loop would be cleaner and avoid building three intermediate lists that are discarded immediately.

**Code it points at:**
```python
# csvkit/utilities/csvdiff.py
def render_jsonl(result, key_names, output_file, show_schema=False):
    changed = [d for d in result.row_diffs if d.status == 'changed']
    added = [d for d in result.row_diffs if d.status == 'added']
    removed = [d for d in result.row_diffs if d.status == 'removed']
```

**Challenge:** None — nit is valid; building lists we only len() is wasteful.

**Resolution:** applied — replaced with counter variables.
**Fix:**
```diff
-    changed = [d for d in result.row_diffs if d.status == 'changed']
-    added = [d for d in result.row_diffs if d.status == 'added']
-    removed = [d for d in result.row_diffs if d.status == 'removed']
-    schema_reported = show_schema and _schema_changed(result.schema)
+    n_changed = n_added = n_removed = 0
+    for d in result.row_diffs:
+        if d.status == 'changed':
+            n_changed += 1
+        elif d.status == 'added':
+            n_added += 1
+        else:
+            n_removed += 1
+    schema_reported = show_schema and _schema_changed(result.schema)

     summary = {
         'event': 'summary',
         'compared': result.compared_count,
-        'changed': len(changed),
-        'added': len(added),
-        'removed': len(removed),
+        'changed': n_changed,
+        'added': n_added,
+        'removed': n_removed,
         'schema_changed': schema_reported,
     }
```

---

## Round 2 — APPROVE — targeted re-review (0 new findings)

**Scope:** targeted re-review — verified prior findings, deep-reviewed round-1 fixes, regression-scanned the rest.
**Prior findings status (reported by reviewer):**
- 1.1 — closed — TestCSVDiffJSONL now declares `class TestCSVDiffJSONL(_CSVDiffOutputMixin, CSVKitTestCase)` with `Utility = CSVDiff`; no duplicate methods.
- 1.2 — closed — renamed to `test_decimal_serialization_via_default_str_decimal`; uses `diff_a.csv` vs `diff_b.csv` without `-I`, asserts price fields are `str`.
- 1.3 — closed — `test_equal_files_emits_summary_only` now asserts `assertEqual(ev['compared'], 3)`.
- 1.4 — closed — three list comprehensions replaced with single counter loop; summary dict references `n_changed/n_added/n_removed`.

**Reviewer summary:** All four round-1 findings are genuinely closed. `render_jsonl` is clean, the counter loop's `else` branch is safe (status is controlled entirely by the diff engine), `dict(zip(key_names, delta.key))` produces the correct `{"row": N}` shape in positional mode, and the schema-gating logic mirrors `render_human` exactly. No regressions from the fixes.

---

## Outcome

**Final verdict:** APPROVE at round 2
**Deferred (nits / accepted rebuttals):** none
