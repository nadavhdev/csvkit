import io
import json
import sys
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import agate

from csvkit.utilities.csvdiff import (CSVDiff, DiffResult, DuplicateKeyError, RowDelta, SchemaDelta, _build_key_index,
                                      _compute_diff, _compute_positional_diff, _compute_schema_delta, _key_display,
                                      _schema_changed, launch_new_instance, render_human, render_jsonl)
from tests.utils import CSVKitTestCase, EmptyFileTests, stdin_as_string


class TestCSVDiff(CSVKitTestCase, EmptyFileTests):
    Utility = CSVDiff
    default_args = ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id']

    # Override to swallow SystemExit so get_output works on diffs-found runs.
    def get_output(self, args):
        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
        utility = self.Utility(args, output_file)
        try:
            utility.run()
        except SystemExit:
            pass
        output = output_file.buffer.getvalue().decode('utf-8')
        output_file.close()
        return output

    # Override EmptyFileTests.test_empty to handle the exit-1 the tool emits.
    def test_empty(self):
        with open('examples/empty.csv', 'rb') as f, stdin_as_string(f):
            utility = self.Utility(getattr(self, 'default_args', []))
            try:
                utility.run()
            except SystemExit:
                pass

    def _exit_code_for(self, args):
        """Run the utility and return its exit code (0 for normal return, else code)."""
        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
        utility = CSVDiff(args, output_file)
        try:
            utility.run()
            return 0
        except SystemExit as exc:
            return exc.code
        finally:
            output_file.close()

    def test_launch_new_instance(self):
        with patch.object(sys, 'argv', ['csvdiff', 'examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id']):
            with self.assertRaises(SystemExit) as cm:
                launch_new_instance()
        self.assertEqual(cm.exception.code, 1)

    # ── Exit code contract ────────────────────────────────────────────────

    def test_exit_0_when_no_differences(self):
        code = self._exit_code_for(['examples/diff_a.csv', 'examples/diff_a.csv', '-c', 'id'])
        self.assertEqual(code, 0)

    def test_exit_1_when_differences(self):
        code = self._exit_code_for(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        self.assertEqual(code, 1)

    def test_exit_2_key_not_in_left(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv',
                              ['csvdiff', 'examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'nonexistent']):
                with self.assertRaises(SystemExit) as cm:
                    launch_new_instance()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('LEFT', f.getvalue())

    def test_exit_2_key_not_in_right(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv',
                              ['csvdiff', 'examples/diff_a.csv', 'examples/diff_types_a.csv', '-c', 'name']):
                with self.assertRaises(SystemExit) as cm:
                    launch_new_instance()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('RIGHT', f.getvalue())

    def test_exit_2_stdin_used_twice(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv', ['csvdiff', '-', '-', '-c', 'id']):
                with self.assertRaises(SystemExit) as cm:
                    launch_new_instance()
        self.assertEqual(cm.exception.code, 2)

    def test_exit_2_interactive_tty(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv', ['csvdiff', '-c', 'id']):
                with patch('csvkit.utilities.csvdiff.isatty', return_value=True):
                    with self.assertRaises(SystemExit) as cm:
                        launch_new_instance()
        self.assertEqual(cm.exception.code, 2)

    def test_parse_error_exits_2_not_1(self):
        """Parse failures must exit 2, not the uncaught-exception default of 1."""
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv',
                              ['csvdiff', 'examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id']):
                def bad_read(self_inner, f_arg, label, path, sniff_limit, column_types):
                    self_inner.argparser.error('{} ({}): CSV parse error'.format(label, path))

                with patch.object(CSVDiff, '_read_table', bad_read):
                    with self.assertRaises(SystemExit) as cm:
                        launch_new_instance()
        self.assertEqual(cm.exception.code, 2)
        stderr = f.getvalue()
        self.assertIn('LEFT', stderr)

    def test_parse_error_right_label_in_stderr(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv',
                              ['csvdiff', 'examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id']):
                original_read = CSVDiff._read_table

                def bad_right_read(self_inner, f_arg, label, path, sniff_limit, column_types):
                    if label == 'RIGHT':
                        self_inner.argparser.error('{} ({}): bad quoting'.format(label, path))
                    return original_read(self_inner, f_arg, label, path, sniff_limit, column_types)

                with patch.object(CSVDiff, '_read_table', bad_right_read):
                    with self.assertRaises(SystemExit) as cm:
                        launch_new_instance()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('RIGHT', f.getvalue())

    def test_parse_error_real_unicode_error_exits_2(self):
        """Real UnicodeDecodeError in _read_table must be caught and exit 2 — not bypass the handler."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as bad_f:
            bad_f.write(b'id,name\n1,\xff\xfe\n')  # \xff\xfe is invalid UTF-8
            bad_path = bad_f.name
        try:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                with patch.object(sys, 'argv',
                                  ['csvdiff', bad_path, 'examples/diff_b.csv', '-c', 'id']):
                    with self.assertRaises(SystemExit) as cm:
                        launch_new_instance()
            self.assertEqual(cm.exception.code, 2)
            self.assertIn('LEFT', stderr.getvalue())
        finally:
            os.unlink(bad_path)

    # ── Human output format ───────────────────────────────────────────────

    def test_headline_format(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        first_line = output.splitlines()[0]
        self.assertEqual(first_line, '1 changed, 1 added, 1 removed (of 2 rows compared)')

    def test_removed_line_prefix_and_key(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        lines = output.splitlines()
        removed_lines = [ln for ln in lines if ln.startswith('-')]
        self.assertEqual(len(removed_lines), 1)
        self.assertIn('id=3', removed_lines[0])
        self.assertIn('name=cherry', removed_lines[0])

    def test_changed_line_prefix_and_delta(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        lines = output.splitlines()
        changed_lines = [ln for ln in lines if ln.startswith('~')]
        self.assertEqual(len(changed_lines), 1)
        self.assertIn('id=1', changed_lines[0])
        self.assertIn('price: 1 -> 10', changed_lines[0])

    def test_added_line_prefix_and_key(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        lines = output.splitlines()
        added_lines = [ln for ln in lines if ln.startswith('+')]
        self.assertEqual(len(added_lines), 1)
        self.assertIn('id=4', added_lines[0])
        self.assertIn('name=date', added_lines[0])

    def test_output_ordering(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        diff_lines = [ln for ln in output.splitlines() if ln and ln[0] in ('-', '~', '+')]
        prefixes = [ln[0] for ln in diff_lines]
        # removed first, then changed, then added
        self.assertEqual(prefixes, ['-', '~', '+'])

    def test_identical_files_headline_zero_diffs(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_a.csv', '-c', 'id'])
        self.assertIn('0 changed, 0 added, 0 removed', output)

    # ── Column name and 1-based index key resolution ──────────────────────

    def test_key_by_name(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        self.assertIn('id=', output)

    def test_key_by_index(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', '1'])
        self.assertIn('id=', output)

    # ── Typed vs raw-string comparison (-I) ──────────────────────────────

    def test_typed_equality_exits_0(self):
        # With inference on, Decimal('1') == Decimal('1.0') — no diff
        code = self._exit_code_for(
            ['examples/diff_types_a.csv', 'examples/diff_types_b.csv', '-c', 'id'])
        self.assertEqual(code, 0)

    def test_raw_string_inequality_exits_1(self):
        # With -I, '1' != '1.0' as raw strings — diff found
        code = self._exit_code_for(
            ['examples/diff_types_a.csv', 'examples/diff_types_b.csv', '-c', 'id', '-I'])
        self.assertEqual(code, 1)

    def test_no_inference_output_shows_diff(self):
        output = self.get_output(
            ['examples/diff_types_a.csv', 'examples/diff_types_b.csv', '-c', 'id', '-I'])
        self.assertIn('value: 1 -> 1.0', output)

    # ── --ignore ──────────────────────────────────────────────────────────

    def test_ignore_price_marks_row_unchanged(self):
        output = self.get_output(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--ignore', 'price'])
        first_line = output.splitlines()[0]
        self.assertEqual(first_line, '0 changed, 1 added, 1 removed (of 2 rows compared)')

    def test_ignore_does_not_hide_added_removed(self):
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--ignore', 'price'])
        self.assertEqual(code, 1)

    def test_ignore_nonexistent_column_is_silent(self):
        output = self.get_output(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--ignore', 'bogus'])
        self.assertIn('1 changed', output)

    # ── Key value formatting (OQ3) ────────────────────────────────────────

    def test_key_format_integer(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        self.assertIn('id=3', output)
        self.assertIn('id=1', output)
        self.assertIn('id=4', output)

    def test_key_format_date(self):
        output = self.get_output(
            ['examples/diff_key_types.csv', 'examples/diff_key_types_b.csv', '-c', 'date_key'])
        self.assertIn('date_key=2024-01-01', output)

    def test_key_format_decimal(self):
        output = self.get_output(
            ['examples/diff_key_types.csv', 'examples/diff_key_types_b.csv', '-c', 'dec_key'])
        self.assertIn('dec_key=1.5', output)

    # ── All four invocation styles ────────────────────────────────────────

    def test_invocation_named_named(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        self.assertIn('1 changed', output)

    def test_invocation_named_stdin(self):
        with open('examples/diff_b.csv', 'rb') as f:
            with stdin_as_string(f):
                output = self.get_output(['examples/diff_a.csv', '-', '-c', 'id'])
        self.assertIn('1 changed', output)

    def test_invocation_stdin_named(self):
        with open('examples/diff_a.csv', 'rb') as f:
            with stdin_as_string(f):
                output = self.get_output(['-', 'examples/diff_b.csv', '-c', 'id'])
        self.assertIn('1 changed', output)

    def test_invocation_redirect_named(self):
        # 1 positional path + piped stdin → stdin is LEFT, path is RIGHT
        with open('examples/diff_a.csv', 'rb') as f:
            with stdin_as_string(f):
                output = self.get_output(['examples/diff_b.csv', '-c', 'id'])
        self.assertIn('1 changed', output)

    def test_invocation_all_four_produce_identical_output(self):
        baseline = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])

        with open('examples/diff_b.csv', 'rb') as f:
            with stdin_as_string(f):
                named_stdin = self.get_output(['examples/diff_a.csv', '-', '-c', 'id'])

        with open('examples/diff_a.csv', 'rb') as f:
            with stdin_as_string(f):
                stdin_named = self.get_output(['-', 'examples/diff_b.csv', '-c', 'id'])

        with open('examples/diff_a.csv', 'rb') as f:
            with stdin_as_string(f):
                redirect = self.get_output(['examples/diff_b.csv', '-c', 'id'])

        self.assertEqual(baseline, named_stdin)
        self.assertEqual(baseline, stdin_named)
        self.assertEqual(baseline, redirect)

    # ── Perf smoke (§6 scalability, 200k × 10 columns, ≤30 s) ───────────

    def test_perf_smoke_200k_rows(self):
        import csv as csv_mod
        import os
        import tempfile

        n_rows = 200_000
        cols = ['id'] + ['col{}'.format(i) for i in range(1, 10)]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as fa:
            writer = csv_mod.writer(fa)
            writer.writerow(cols)
            for i in range(n_rows):
                writer.writerow([i] + [str(i + j) for j in range(1, 10)])
            left_path = fa.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as fb:
            writer = csv_mod.writer(fb)
            writer.writerow(cols)
            for i in range(n_rows):
                # Row 50000 has a changed non-key column; all other rows are identical to LEFT
                col_vals = [str(i + j + (99 if i == 50_000 else 0)) for j in range(1, 10)]
                writer.writerow([i] + col_vals)
            right_path = fb.name

        try:
            start = time.time()
            code = self._exit_code_for([left_path, right_path, '-c', 'id'])
            elapsed = time.time() - start
            self.assertEqual(code, 1, '1 changed row expected → exit 1')
            self.assertLess(elapsed, 30, 'perf-smoke exceeded 30s CI bound: {:.1f}s'.format(elapsed))
        finally:
            os.unlink(left_path)
            os.unlink(right_path)


class _CSVDiffOutputMixin:
    """Shared helpers for capturing csvdiff output and exit codes across test classes.

    Overrides CSVKitTestCase.get_output so that the SystemExit csvdiff emits on exit-1
    (differences found) is absorbed rather than propagated as a test failure.
    Subclasses must declare Utility = CSVDiff.
    """

    def get_output(self, args):
        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
        utility = self.Utility(args, output_file)
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


class TestCSVDiffCompositeKey(_CSVDiffOutputMixin, CSVKitTestCase):
    """Tests for composite -c/--key (arity 2+) and index-based key resolution."""
    Utility = CSVDiff

    def test_composite_key_arity2_matches_by_tuple(self):
        """Same order_id but different line_no are distinct rows (no cross-match)."""
        output = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        # A001,1 price changed; A001,2 removed; A001,3 added; A002,1 unchanged
        self.assertIn('1 changed, 1 added, 1 removed', output)

    def test_composite_key_display_format(self):
        """Composite key rows appear as key=(v1,v2) in the output."""
        output = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        self.assertIn('key=(', output)

    def test_composite_key_changed_row_shows_key_tuple(self):
        output = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        changed_lines = [ln for ln in output.splitlines() if ln.startswith('~')]
        self.assertEqual(len(changed_lines), 1)
        self.assertIn('key=(A001,1)', changed_lines[0])

    def test_composite_key_removed_row_shows_key_tuple(self):
        output = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        removed_lines = [ln for ln in output.splitlines() if ln.startswith('-')]
        self.assertEqual(len(removed_lines), 1)
        self.assertIn('key=(A001,2)', removed_lines[0])

    def test_composite_key_added_row_shows_key_tuple(self):
        output = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        added_lines = [ln for ln in output.splitlines() if ln.startswith('+')]
        self.assertEqual(len(added_lines), 1)
        self.assertIn('key=(A001,3)', added_lines[0])

    def test_composite_key_same_tuple_different_columns_are_distinct(self):
        """Rows sharing one key component but differing in the other are never conflated."""
        code = self._exit_code_for(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        self.assertEqual(code, 1)

    def test_composite_key_identical_files_exit_0(self):
        code = self._exit_code_for(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_a.csv', '-c', 'order_id,line_no'])
        self.assertEqual(code, 0)

    def test_composite_key_by_index(self):
        """Key columns resolved by 1-based index produce same result as by name."""
        output_name = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', 'order_id,line_no'])
        output_index = self.get_output(
            ['examples/diff_composite_a.csv', 'examples/diff_composite_b.csv', '-c', '1,2'])
        self.assertEqual(output_name, output_index)

    def test_composite_key_bad_column_exits_2(self):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv',
                              ['csvdiff', 'examples/diff_composite_a.csv',
                               'examples/diff_composite_b.csv', '-c', 'order_id,no_such_col']):
                with self.assertRaises(SystemExit) as cm:
                    launch_new_instance()
        self.assertEqual(cm.exception.code, 2)


class TestCSVDiffOnDup(_CSVDiffOutputMixin, CSVKitTestCase):
    """Tests for --on-dup={error,first,all} with single- and double-sided duplicates."""
    Utility = CSVDiff

    def _stderr_for(self, args):
        f = io.StringIO()
        with redirect_stderr(f):
            with patch.object(sys, 'argv', ['csvdiff'] + args):
                try:
                    launch_new_instance()
                except SystemExit:
                    pass
        return f.getvalue()

    # ── --on-dup=error (default) ──────────────────────────────────────────

    def test_on_dup_error_default_exits_2_left_dup(self):
        """Default --on-dup=error exits 2 when LEFT has duplicate keys."""
        code = self._exit_code_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id'])
        self.assertEqual(code, 2)

    def test_on_dup_error_explicit_exits_2_left_dup(self):
        code = self._exit_code_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'error'])
        self.assertEqual(code, 2)

    def test_on_dup_error_stderr_names_left_side(self):
        stderr = self._stderr_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id'])
        self.assertIn('LEFT', stderr)

    def test_on_dup_error_stderr_names_duplicate_key(self):
        stderr = self._stderr_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id'])
        self.assertIn('id=1', stderr)

    def test_on_dup_error_stderr_names_offending_rows(self):
        """Error message must include at least one row indicator with specific row numbers."""
        stderr = self._stderr_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id'])
        # id=1 first appears at row 1, repeated at row 2 (1-based)
        self.assertIn('row 1', stderr)
        self.assertIn('row 2', stderr)

    def test_on_dup_error_exits_2_right_dup(self):
        """--on-dup=error exits 2 and names RIGHT when RIGHT has duplicate keys."""
        stderr = self._stderr_for(
            ['examples/diff_dup_b.csv', 'examples/diff_dup_a.csv', '-c', 'id'])
        self.assertIn('RIGHT', stderr)

    def test_on_dup_error_no_dup_exits_normally(self):
        """Files without duplicates pass through --on-dup=error without error."""
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--on-dup', 'error'])
        self.assertIn(code, (0, 1))  # either no-diff or diffs-found, both are normal

    # ── --on-dup=first ────────────────────────────────────────────────────

    def test_on_dup_first_does_not_exit_2_on_dup(self):
        code = self._exit_code_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'first'])
        self.assertIn(code, (0, 1))

    def test_on_dup_first_compares_first_occurrence(self):
        """With --on-dup=first, only the first row per key is used; alice vs carol → changed."""
        output = self.get_output(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'first'])
        # id=1 first in LEFT is 'alice'; id=1 in RIGHT is 'carol' → changed
        self.assertIn('1 changed', output)

    def test_on_dup_first_discards_later_occurrences(self):
        """The second row for a duplicate key is silently discarded."""
        output = self.get_output(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'first'])
        # alice_dup should not appear in output (it was discarded)
        self.assertNotIn('alice_dup', output)

    def test_on_dup_first_both_sides_keeps_first_each(self):
        """With duplicates on both sides, --on-dup=first keeps first on each side independently."""
        code = self._exit_code_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_a.csv', '-c', 'id', '--on-dup', 'first'])
        # Same file, first occurrences match → exit 0
        self.assertEqual(code, 0)

    def test_on_dup_first_right_side_dup_proceeds(self):
        """--on-dup=first handles right-side duplicates without error."""
        # diff_dup_b.csv is LEFT (no dups), diff_dup_a.csv is RIGHT (has id=1 dup)
        code = self._exit_code_for(
            ['examples/diff_dup_b.csv', 'examples/diff_dup_a.csv', '-c', 'id', '--on-dup', 'first'])
        self.assertIn(code, (0, 1))

    def test_on_dup_first_right_side_compares_first_occurrence(self):
        """With RIGHT duplicate, --on-dup=first uses first RIGHT occurrence for comparison."""
        output = self.get_output(
            ['examples/diff_dup_b.csv', 'examples/diff_dup_a.csv', '-c', 'id', '--on-dup', 'first'])
        # RIGHT id=1 first occurrence is 'alice'; LEFT id=1 is 'carol' → changed
        self.assertIn('1 changed', output)

    # ── --on-dup=all ──────────────────────────────────────────────────────

    def test_on_dup_all_does_not_exit_2_on_dup(self):
        code = self._exit_code_for(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'all'])
        self.assertIn(code, (0, 1))

    def test_on_dup_all_cartesian_left_two_right_one(self):
        """LEFT has 2 rows for key id=1, RIGHT has 1 → 2 compared pairs, 2 changed rows."""
        output = self.get_output(
            ['examples/diff_dup_a.csv', 'examples/diff_dup_b.csv', '-c', 'id', '--on-dup', 'all'])
        # id=1: 2 left × 1 right = 2 comparisons (alice vs carol, alice_dup vs carol) — both changed
        # id=2: 1 left × 1 right = 1 comparison (bob vs bob) — unchanged
        self.assertIn('2 changed', output)

    def test_on_dup_all_cartesian_right_two_left_one(self):
        """RIGHT has 2 rows for key id=1, LEFT has 1 → 2 comparison pairs."""
        output = self.get_output(
            ['examples/diff_dup_b.csv', 'examples/diff_dup_a.csv', '-c', 'id', '--on-dup', 'all'])
        # diff_dup_b LEFT: id=1→carol; diff_dup_a RIGHT: id=1→alice, id=1→alice_dup
        # id=1: 1×2=2 comparisons (carol vs alice, carol vs alice_dup) — both changed
        self.assertIn('2 changed', output)

    def test_on_dup_all_no_dup_behaves_like_error(self):
        """When there are no duplicates, --on-dup=all produces same output as --on-dup=error."""
        output_all = self.get_output(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--on-dup', 'all'])
        output_err = self.get_output(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--on-dup', 'error'])
        self.assertEqual(output_all, output_err)

    # ── --on-dup=all epilog/help mentions O(n*m) hazard ──────────────────

    def test_on_dup_all_help_mentions_cartesian_hazard(self):
        """--on-dup flag's help text must warn about the O(n*m) Cartesian product risk."""
        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
        utility = CSVDiff(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'], output_file)
        help_text = utility.argparser.format_help()
        self.assertIn('n*m', help_text)

    def test_on_dup_all_epilog_mentions_cartesian_hazard(self):
        """Epilog must explicitly name the O(n*m) hazard for --on-dup=all."""
        self.assertIn('n*m', CSVDiff.epilog)


class TestCSVDiffEngine(unittest.TestCase):
    """Unit tests for the diff engine, independent of the CLI."""

    def test_schema_delta_added_removed(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'value'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertEqual(result.schema.added, ['value'])
        self.assertEqual(result.schema.removed, ['name'])

    def test_schema_delta_reordered(self):
        left = agate.Table([('1', 'a', '1')], column_names=['id', 'name', 'price'])
        right = agate.Table([('1', '1', 'a')], column_names=['id', 'price', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertTrue(result.schema.reordered)

    def test_schema_no_reorder_when_order_same(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertFalse(result.schema.reordered)

    def test_unchanged_count_and_zero_diffs(self):
        left = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        right = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertEqual(result.unchanged_count, 2)
        self.assertEqual(result.compared_count, 2)
        self.assertEqual(result.row_diffs, [])

    def test_diff_ordering(self):
        """Removed in LEFT order → changed in LEFT order → added in RIGHT order."""
        left = agate.Table([('1', 'a'), ('2', 'b'), ('3', 'c')], column_names=['id', 'name'])
        right = agate.Table([('2', 'b'), ('3', 'X'), ('4', 'd')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        statuses = [d.status for d in result.row_diffs]
        self.assertEqual(statuses, ['removed', 'changed', 'added'])
        self.assertEqual(str(result.row_diffs[0].key[0]), '1')
        self.assertEqual(str(result.row_diffs[1].key[0]), '3')
        self.assertEqual(str(result.row_diffs[2].key[0]), '4')

    def test_ignore_cols_suppresses_diff(self):
        left = agate.Table([('1', 'a', '10')], column_names=['id', 'name', 'ts'])
        right = agate.Table([('1', 'a', '99')], column_names=['id', 'name', 'ts'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', {'ts'})
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.unchanged_count, 1)

    def test_ignore_key_col_name_is_noop(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'name'])
        result_with = _compute_diff(left, right, ['id'], ['id'], 'error', {'id'})
        result_without = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        # ignoring the key column is a no-op on changed detection
        self.assertEqual(len(result_with.row_diffs), len(result_without.row_diffs))

    def test_added_and_removed_counts(self):
        left = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        right = agate.Table([('2', 'b'), ('3', 'c')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        removed = [d for d in result.row_diffs if d.status == 'removed']
        added = [d for d in result.row_diffs if d.status == 'added']
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(added), 1)
        self.assertEqual(result.compared_count, 1)
        self.assertEqual(result.unchanged_count, 1)

    # ── Composite key engine tests ─────────────────────────────────────────

    def test_composite_key_arity2_distinguishes_rows(self):
        """(k1=A,k2=1) and (k1=A,k2=2) are treated as distinct keys."""
        left = agate.Table(
            [('A', '1', 'v1'), ('A', '2', 'v2')], column_names=['k1', 'k2', 'val'])
        right = agate.Table(
            [('A', '1', 'v1'), ('A', '2', 'v9')], column_names=['k1', 'k2', 'val'])
        result = _compute_diff(left, right, ['k1', 'k2'], ['k1', 'k2'], 'error', set())
        self.assertEqual(len(result.row_diffs), 1)
        self.assertEqual(result.row_diffs[0].status, 'changed')
        # agate infers '2' as Decimal; compare via str to stay type-agnostic
        self.assertEqual(tuple(str(v) for v in result.row_diffs[0].key), ('A', '2'))

    def test_composite_key_arity3(self):
        """Composite key of arity 3 is supported."""
        left = agate.Table([('A', 'B', 'C', 'v1')], column_names=['k1', 'k2', 'k3', 'val'])
        right = agate.Table([('A', 'B', 'C', 'v2')], column_names=['k1', 'k2', 'k3', 'val'])
        result = _compute_diff(left, right, ['k1', 'k2', 'k3'], ['k1', 'k2', 'k3'], 'error', set())
        self.assertEqual(len(result.row_diffs), 1)
        self.assertEqual(result.row_diffs[0].status, 'changed')
        self.assertEqual(result.row_diffs[0].key, ('A', 'B', 'C'))

    def test_composite_key_columns_excluded_from_fields(self):
        """Key columns must not appear in the fields dict of a changed RowDelta."""
        left = agate.Table([('A', '1', 'old')], column_names=['k1', 'k2', 'val'])
        right = agate.Table([('A', '1', 'new')], column_names=['k1', 'k2', 'val'])
        result = _compute_diff(left, right, ['k1', 'k2'], ['k1', 'k2'], 'error', set())
        delta = result.row_diffs[0]
        self.assertNotIn('k1', delta.fields)
        self.assertNotIn('k2', delta.fields)
        self.assertIn('val', delta.fields)

    def test_composite_key_removed_row_fields_exclude_key_cols(self):
        left = agate.Table([('A', '1', 'v')], column_names=['k1', 'k2', 'val'])
        right = agate.Table([], column_names=['k1', 'k2', 'val'])
        result = _compute_diff(left, right, ['k1', 'k2'], ['k1', 'k2'], 'error', set())
        delta = result.row_diffs[0]
        self.assertEqual(delta.status, 'removed')
        self.assertNotIn('k1', delta.fields)
        self.assertNotIn('k2', delta.fields)

    def test_composite_key_added_row_fields_exclude_key_cols(self):
        left = agate.Table([], column_names=['k1', 'k2', 'val'])
        right = agate.Table([('A', '1', 'v')], column_names=['k1', 'k2', 'val'])
        result = _compute_diff(left, right, ['k1', 'k2'], ['k1', 'k2'], 'error', set())
        delta = result.row_diffs[0]
        self.assertEqual(delta.status, 'added')
        self.assertNotIn('k1', delta.fields)
        self.assertNotIn('k2', delta.fields)

    # ── on_dup engine tests ────────────────────────────────────────────────

    def test_on_dup_error_raises_on_left_dup(self):
        left = agate.Table([('K1', 'a'), ('K1', 'b')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'c')], column_names=['id', 'name'])
        with self.assertRaises(DuplicateKeyError) as cm:
            _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertIn('LEFT', str(cm.exception))
        self.assertIn('id=K1', str(cm.exception))

    def test_on_dup_error_raises_on_right_dup(self):
        left = agate.Table([('K1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'c'), ('K1', 'd')], column_names=['id', 'name'])
        with self.assertRaises(DuplicateKeyError) as cm:
            _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertIn('RIGHT', str(cm.exception))

    def test_on_dup_error_message_includes_row_indicators(self):
        left = agate.Table([('K1', 'a'), ('K1', 'b'), ('K2', 'c')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'x')], column_names=['id', 'name'])
        with self.assertRaises(DuplicateKeyError) as cm:
            _compute_diff(left, right, ['id'], ['id'], 'error', set())
        msg = str(cm.exception)
        self.assertIn('row 1', msg)  # first seen at row 1 (1-based)
        self.assertIn('row 2', msg)  # repeated at row 2 (1-based)

    def test_on_dup_first_keeps_first_occurrence(self):
        left = agate.Table([('K1', 'first'), ('K1', 'second')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'other')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'first', set())
        # Only first row compared — 'first' vs 'other' → changed
        self.assertEqual(len(result.row_diffs), 1)
        self.assertEqual(result.row_diffs[0].status, 'changed')
        self.assertEqual(result.row_diffs[0].fields['name'], ('first', 'other'))

    def test_on_dup_first_discards_subsequent_occurrences(self):
        left = agate.Table([('K1', 'v1'), ('K1', 'v2'), ('K2', 'v3')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'v1'), ('K2', 'v3')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'first', set())
        # First of K1 in LEFT is 'v1', RIGHT is 'v1' → unchanged; K2 unchanged
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.unchanged_count, 2)

    def test_on_dup_all_cartesian_both_sides(self):
        """LEFT has [L0,L1] for key K1, RIGHT has [R0,R1] → 4 comparison pairs."""
        left = agate.Table([('K1', 'a'), ('K1', 'b'), ('K2', 'c')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'x'), ('K1', 'y'), ('K2', 'c')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'all', set())
        # K1: 2×2=4 compared; K2: 1×1=1 compared → total 5
        self.assertEqual(result.compared_count, 5)
        # All 4 K1 pairs are changed (a≠x, a≠y, b≠x, b≠y); K2 unchanged
        changed = [d for d in result.row_diffs if d.status == 'changed']
        self.assertEqual(len(changed), 4)

    def test_on_dup_all_cartesian_left_dup_right_single(self):
        """LEFT has 2 for key K1, RIGHT has 1 → 2 comparison pairs."""
        left = agate.Table([('K1', 'a'), ('K1', 'b')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'x')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'all', set())
        self.assertEqual(result.compared_count, 2)

    def test_on_dup_all_cartesian_right_dup_left_single(self):
        """RIGHT has 2 for key K1, LEFT has 1 → 2 comparison pairs (symmetric)."""
        left = agate.Table([('K1', 'x')], column_names=['id', 'name'])
        right = agate.Table([('K1', 'a'), ('K1', 'b')], column_names=['id', 'name'])
        result = _compute_diff(left, right, ['id'], ['id'], 'all', set())
        self.assertEqual(result.compared_count, 2)

    def test_on_dup_all_no_dup_matches_error_behavior(self):
        left = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        right = agate.Table([('1', 'a'), ('2', 'x')], column_names=['id', 'name'])
        result_all = _compute_diff(left, right, ['id'], ['id'], 'all', set())
        result_err = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertEqual(result_all.row_diffs, result_err.row_diffs)
        self.assertEqual(result_all.compared_count, result_err.compared_count)

    # ── _key_display tests ─────────────────────────────────────────────────

    def test_key_display_single_key(self):
        self.assertEqual(_key_display(['id'], ('5',)), 'id=5')

    def test_key_display_single_key_none(self):
        self.assertEqual(_key_display(['id'], (None,)), 'id=')

    def test_key_display_composite_key(self):
        self.assertEqual(_key_display(['k1', 'k2'], ('A', '1')), 'key=(A,1)')

    def test_key_display_composite_key_arity3(self):
        self.assertEqual(_key_display(['a', 'b', 'c'], ('x', 'y', 'z')), 'key=(x,y,z)')

    def test_key_display_composite_key_none_value(self):
        self.assertEqual(_key_display(['k1', 'k2'], (None, '1')), 'key=(,1)')

    # ── _compute_positional_diff unit tests ────────────────────────────────

    def test_positional_equal_length_identical_no_diffs(self):
        left = agate.Table([('alice', '10'), ('bob', '20')], column_names=['name', 'score'])
        right = agate.Table([('alice', '10'), ('bob', '20')], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, set())
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.unchanged_count, 2)
        self.assertEqual(result.compared_count, 2)

    def test_positional_equal_length_with_change(self):
        left = agate.Table([('alice', '10'), ('bob', '20')], column_names=['name', 'score'])
        right = agate.Table([('alice', '10'), ('bob', '99')], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, set())
        self.assertEqual(len(result.row_diffs), 1)
        self.assertEqual(result.row_diffs[0].status, 'changed')
        self.assertEqual(result.row_diffs[0].key, (2,))

    def test_positional_row_key_is_1based(self):
        left = agate.Table([('a', 'x')], column_names=['name', 'val'])
        right = agate.Table([('a', 'y')], column_names=['name', 'val'])
        result = _compute_positional_diff(left, right, set())
        self.assertEqual(result.row_diffs[0].key, (1,))

    def test_positional_left_longer_surplus_is_removed(self):
        left = agate.Table([('a', '1'), ('b', '2'), ('c', '3')], column_names=['name', 'score'])
        right = agate.Table([('a', '1'), ('b', '2')], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, set())
        removed = [d for d in result.row_diffs if d.status == 'removed']
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0].key, (3,))
        self.assertEqual(removed[0].fields['name'], ('c', None))

    def test_positional_right_longer_surplus_is_added(self):
        left = agate.Table([('a', '1'), ('b', '2')], column_names=['name', 'score'])
        right = agate.Table([('a', '1'), ('b', '2'), ('c', '3')], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, set())
        added = [d for d in result.row_diffs if d.status == 'added']
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].key, (3,))
        self.assertEqual(added[0].fields['name'], (None, 'c'))

    def test_positional_both_empty_no_diffs(self):
        left = agate.Table([], column_names=['name', 'score'])
        right = agate.Table([], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, set())
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.compared_count, 0)
        self.assertEqual(result.unchanged_count, 0)

    def test_positional_ignore_names_suppresses_field_diff(self):
        left = agate.Table([('alice', '10')], column_names=['name', 'score'])
        right = agate.Table([('alice', '99')], column_names=['name', 'score'])
        result = _compute_positional_diff(left, right, {'score'})
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.unchanged_count, 1)

    def test_positional_schema_delta_computed(self):
        left = agate.Table([('a',)], column_names=['name'])
        right = agate.Table([('a', '1')], column_names=['name', 'extra'])
        result = _compute_positional_diff(left, right, set())
        self.assertEqual(result.schema.added, ['extra'])
        self.assertEqual(result.schema.removed, [])

    def test_positional_ordering_changed_rows_in_position_order(self):
        """Changed rows appear in ascending position order within the changed category."""
        left = agate.Table([('a', '1'), ('b', '2'), ('c', '3')], column_names=['k', 'v'])
        right = agate.Table([('a', '9'), ('b', '2'), ('c', '4')], column_names=['k', 'v'])
        result = _compute_positional_diff(left, right, set())
        statuses = [d.status for d in result.row_diffs]
        self.assertEqual(statuses, ['changed', 'changed'])
        self.assertEqual(result.row_diffs[0].key, (1,))
        self.assertEqual(result.row_diffs[1].key, (3,))

    # ── _compute_schema_delta / _schema_changed unit tests ─────────────────

    def test_compute_schema_delta_added_removed(self):
        delta = _compute_schema_delta(['id', 'name'], ['id', 'value'])
        self.assertEqual(delta.added, ['value'])      # in RIGHT order
        self.assertEqual(delta.removed, ['name'])      # in LEFT order
        self.assertEqual(delta.common, ['id'])
        self.assertFalse(delta.reordered)

    def test_compute_schema_delta_added_in_right_order(self):
        """Added columns are listed in RIGHT's column order, not sorted."""
        delta = _compute_schema_delta(['id'], ['id', 'zeta', 'alpha'])
        self.assertEqual(delta.added, ['zeta', 'alpha'])

    def test_compute_schema_delta_removed_in_left_order(self):
        """Removed columns are listed in LEFT's column order, not sorted."""
        delta = _compute_schema_delta(['id', 'zeta', 'alpha'], ['id'])
        self.assertEqual(delta.removed, ['zeta', 'alpha'])

    def test_compute_schema_delta_reordered(self):
        delta = _compute_schema_delta(['id', 'name', 'price'], ['id', 'price', 'name'])
        self.assertTrue(delta.reordered)
        self.assertEqual(delta.added, [])
        self.assertEqual(delta.removed, [])

    def test_compute_schema_delta_identical_not_reordered(self):
        delta = _compute_schema_delta(['id', 'name'], ['id', 'name'])
        self.assertFalse(delta.reordered)
        self.assertEqual(delta.added, [])
        self.assertEqual(delta.removed, [])

    def test_compute_schema_delta_reorder_ignores_non_common_columns(self):
        """Adding/removing a column does not by itself count as a reorder of the common set."""
        delta = _compute_schema_delta(['id', 'name', 'price'], ['id', 'name'])
        self.assertEqual(delta.removed, ['price'])
        self.assertFalse(delta.reordered)

    def test_schema_changed_true_on_added(self):
        self.assertTrue(_schema_changed(SchemaDelta(added=['x'], removed=[], reordered=False, common=[])))

    def test_schema_changed_true_on_removed(self):
        self.assertTrue(_schema_changed(SchemaDelta(added=[], removed=['x'], reordered=False, common=[])))

    def test_schema_changed_true_on_reordered(self):
        self.assertTrue(_schema_changed(SchemaDelta(added=[], removed=[], reordered=True, common=[])))

    def test_schema_changed_false_when_identical(self):
        self.assertFalse(_schema_changed(SchemaDelta(added=[], removed=[], reordered=False, common=['id'])))

    def test_added_column_excluded_from_changed_row_fields(self):
        """A column present only in RIGHT is never compared, so it never appears in a changed row's fields."""
        left = agate.Table([('1', 'old')], column_names=['id', 'name'])
        right = agate.Table([('1', 'new', 'west')], column_names=['id', 'name', 'region'])
        result = _compute_diff(left, right, ['id'], ['id'], 'error', set())
        self.assertEqual(result.schema.added, ['region'])
        delta = result.row_diffs[0]
        self.assertEqual(delta.status, 'changed')
        self.assertIn('name', delta.fields)
        self.assertNotIn('region', delta.fields)

    # ── render_human schema banner unit tests ──────────────────────────────

    def _render(self, schema, show_schema):
        result = DiffResult(schema=schema, row_diffs=[], unchanged_count=0, compared_count=0)
        buf = io.StringIO()
        render_human(result, ['id'], buf, show_schema=show_schema)
        return buf.getvalue()

    def test_render_human_emits_banner_when_show_schema(self):
        out = self._render(SchemaDelta(added=['region'], removed=[], reordered=False, common=['id']), True)
        self.assertTrue(out.startswith('! schema changed:'))
        self.assertIn('added: region', out)

    def test_render_human_no_banner_when_show_schema_false(self):
        out = self._render(SchemaDelta(added=['region'], removed=[], reordered=False, common=['id']), False)
        self.assertNotIn('! schema changed', out)

    def test_render_human_no_banner_when_schema_unchanged(self):
        out = self._render(SchemaDelta(added=[], removed=[], reordered=False, common=['id']), True)
        self.assertNotIn('! schema changed', out)

    def test_render_human_banner_lists_all_three_deltas(self):
        out = self._render(
            SchemaDelta(added=['region'], removed=['legacy'], reordered=True, common=['id']), True)
        self.assertIn('added: region', out)
        self.assertIn('removed: legacy', out)
        self.assertIn('reordered: true', out)


class TestCSVDiffPositional(_CSVDiffOutputMixin, CSVKitTestCase):
    """Tests for no-key positional row-by-row comparison (task-03)."""
    Utility = CSVDiff

    # ── Exit code contract ────────────────────────────────────────────────

    def test_positional_equal_length_identical_exits_0(self):
        code = self._exit_code_for(['examples/diff_pos_a.csv', 'examples/diff_pos_a.csv'])
        self.assertEqual(code, 0)

    def test_positional_equal_length_with_change_exits_1(self):
        code = self._exit_code_for(['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv'])
        self.assertEqual(code, 1)

    def test_positional_left_longer_exits_1(self):
        code = self._exit_code_for(['examples/diff_pos_a.csv', 'examples/diff_pos_short.csv'])
        self.assertEqual(code, 1)

    def test_positional_right_longer_exits_1(self):
        code = self._exit_code_for(['examples/diff_pos_short.csv', 'examples/diff_pos_a.csv'])
        self.assertEqual(code, 1)

    def test_positional_both_empty_exits_0(self):
        code = self._exit_code_for(['examples/diff_pos_empty.csv', 'examples/diff_pos_empty.csv'])
        self.assertEqual(code, 0)

    # ── Row-index key format ──────────────────────────────────────────────

    def test_positional_changed_row_key_is_row_index(self):
        """Changed row key slot must show row=N (1-based)."""
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv'])
        changed_lines = [ln for ln in output.splitlines() if ln.startswith('~')]
        self.assertEqual(len(changed_lines), 1)
        self.assertIn('row=2', changed_lines[0])

    def test_positional_removed_row_key_is_row_index(self):
        """Surplus LEFT row's key slot must show row=N (1-based)."""
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_short.csv'])
        removed_lines = [ln for ln in output.splitlines() if ln.startswith('-')]
        self.assertEqual(len(removed_lines), 1)
        self.assertIn('row=3', removed_lines[0])

    def test_positional_added_row_key_is_row_index(self):
        """Surplus RIGHT row's key slot must show row=N (1-based)."""
        output = self.get_output(['examples/diff_pos_short.csv', 'examples/diff_pos_a.csv'])
        added_lines = [ln for ln in output.splitlines() if ln.startswith('+')]
        self.assertEqual(len(added_lines), 1)
        self.assertIn('row=3', added_lines[0])

    # ── Field values in output ────────────────────────────────────────────

    def test_positional_changed_row_shows_field_delta(self):
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv'])
        changed_lines = [ln for ln in output.splitlines() if ln.startswith('~')]
        self.assertIn('score: 20 -> 99', changed_lines[0])

    def test_positional_removed_row_shows_field_values(self):
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_short.csv'])
        removed_lines = [ln for ln in output.splitlines() if ln.startswith('-')]
        self.assertIn('name=carol', removed_lines[0])
        self.assertIn('score=30', removed_lines[0])

    def test_positional_added_row_shows_field_values(self):
        output = self.get_output(['examples/diff_pos_short.csv', 'examples/diff_pos_a.csv'])
        added_lines = [ln for ln in output.splitlines() if ln.startswith('+')]
        self.assertIn('name=carol', added_lines[0])
        self.assertIn('score=30', added_lines[0])

    # ── Headline counts ───────────────────────────────────────────────────

    def test_positional_left_longer_headline(self):
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_short.csv'])
        first_line = output.splitlines()[0]
        self.assertEqual(first_line, '0 changed, 0 added, 1 removed (of 2 rows compared)')

    def test_positional_right_longer_headline(self):
        output = self.get_output(['examples/diff_pos_short.csv', 'examples/diff_pos_a.csv'])
        first_line = output.splitlines()[0]
        self.assertEqual(first_line, '0 changed, 1 added, 0 removed (of 2 rows compared)')

    def test_positional_equal_with_change_headline(self):
        output = self.get_output(['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv'])
        first_line = output.splitlines()[0]
        self.assertEqual(first_line, '1 changed, 0 added, 0 removed (of 3 rows compared)')

    # ── Warning text ──────────────────────────────────────────────────────

    def test_positional_warning_in_epilog(self):
        """Epilog must warn about positional mode's re-sorted-file footgun."""
        self.assertIn('positional', CSVDiff.epilog)
        self.assertIn('-c', CSVDiff.epilog)

    def test_positional_warning_in_help_text(self):
        output_file = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', newline='', write_through=True)
        utility = CSVDiff(['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv'], output_file)
        help_text = utility.argparser.format_help()
        self.assertIn('positional', help_text)
        self.assertIn('re-sorted', help_text)

    def test_positional_with_ignore_suppresses_change(self):
        """--ignore works in positional mode: suppressed column does not trigger a diff."""
        code = self._exit_code_for(
            ['examples/diff_pos_a.csv', 'examples/diff_pos_b.csv', '--ignore', 'score'])
        # diff_pos_a row 2: bob/20; diff_pos_b row 2: bob/99 — only score differs; suppressed → exit 0
        self.assertEqual(code, 0)

    def test_positional_ignore_does_not_hide_fields_in_surplus_rows(self):
        """--ignore suppresses comparison but surplus removed/added rows still display the ignored column."""
        output = self.get_output(
            ['examples/diff_pos_a.csv', 'examples/diff_pos_short.csv', '--ignore', 'score'])
        removed_lines = [ln for ln in output.splitlines() if ln.startswith('-')]
        self.assertEqual(len(removed_lines), 1)
        # score is ignored for comparison but must still appear in the removed row display
        self.assertIn('score=30', removed_lines[0])


class TestBuildKeyIndex(unittest.TestCase):
    """Unit tests for _build_key_index helper."""

    def _make_table(self, rows):
        return agate.Table(rows, column_names=['id', 'name'])

    def test_no_duplicates_builds_index(self):
        table = self._make_table([('Ka', 'a'), ('Kb', 'b')])
        index = _build_key_index(table, ['id'], 'error', 'LEFT')
        self.assertEqual(index[('Ka',)], [0])
        self.assertEqual(index[('Kb',)], [1])

    def test_on_dup_error_raises_on_duplicate(self):
        table = self._make_table([('Ka', 'a'), ('Ka', 'b')])
        with self.assertRaises(DuplicateKeyError):
            _build_key_index(table, ['id'], 'error', 'LEFT')

    def test_on_dup_first_stores_only_first(self):
        table = self._make_table([('Ka', 'a'), ('Ka', 'b'), ('Ka', 'c')])
        index = _build_key_index(table, ['id'], 'first', 'LEFT')
        self.assertEqual(index[('Ka',)], [0])

    def test_on_dup_all_stores_all(self):
        table = self._make_table([('Ka', 'a'), ('Ka', 'b'), ('Ka', 'c')])
        index = _build_key_index(table, ['id'], 'all', 'LEFT')
        self.assertEqual(index[('Ka',)], [0, 1, 2])

    def test_composite_key_uses_tuple(self):
        table = agate.Table([('A', 'X', 'v')], column_names=['k1', 'k2', 'val'])
        index = _build_key_index(table, ['k1', 'k2'], 'error', 'LEFT')
        self.assertIn(('A', 'X'), index)


class TestCSVDiffSchema(_CSVDiffOutputMixin, CSVKitTestCase):
    """CLI-level tests for schema-drift detection (task-04)."""
    Utility = CSVDiff

    BASE = 'examples/diff_schema_base.csv'
    ADDED = 'examples/diff_schema_added.csv'
    ADDED_CHANGED = 'examples/diff_schema_added_changed.csv'
    REORDERED = 'examples/diff_schema_reordered.csv'
    ALL_RIGHT = 'examples/diff_schema_all_right.csv'
    RENAME_L = 'examples/diff_schema_rename_left.csv'
    RENAME_R = 'examples/diff_schema_rename_right.csv'

    def _row_diff_lines(self, output):
        return [ln for ln in output.splitlines() if ln[:1] in ('-', '~', '+')]

    # ── Identical schema: no banner, unchanged behavior ───────────────────

    def test_identical_schema_emits_no_banner(self):
        output = self.get_output([self.BASE, self.BASE, '-c', 'id'])
        self.assertNotIn('! schema changed', output)

    def test_identical_schema_exits_0(self):
        code = self._exit_code_for([self.BASE, self.BASE, '-c', 'id'])
        self.assertEqual(code, 0)

    def test_identical_schema_row_diff_unchanged(self):
        """With identical columns the row-diff section matches the pre-schema behavior."""
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id'])
        self.assertNotIn('! schema changed', output)
        self.assertEqual(output.splitlines()[0], '1 changed, 1 added, 1 removed (of 2 rows compared)')

    # ── Added column (criterion 2) ────────────────────────────────────────

    def test_added_column_banner_begins_output(self):
        output = self.get_output([self.BASE, self.ADDED, '-c', 'id'])
        self.assertTrue(output.startswith('! schema changed:'))
        self.assertIn('added: region', output)

    def test_added_column_not_reported_in_row_diffs(self):
        """The added column appears only in the banner, never as per-row noise."""
        # ADDED_CHANGED differs from BASE on a common column (price) AND adds `region`,
        # so a real '~' changed line exists — the added column must not leak into it.
        output = self.get_output([self.BASE, self.ADDED_CHANGED, '-c', 'id'])
        row_lines = self._row_diff_lines(output)
        self.assertTrue(any(ln.startswith('~') for ln in row_lines))
        for line in row_lines:
            self.assertNotIn('region', line)

    def test_added_column_exits_1(self):
        code = self._exit_code_for([self.BASE, self.ADDED, '-c', 'id'])
        self.assertEqual(code, 1)

    # ── Removed column (criterion 3) ──────────────────────────────────────

    def test_removed_column_banner(self):
        output = self.get_output([self.ADDED, self.BASE, '-c', 'id'])
        self.assertTrue(output.startswith('! schema changed:'))
        self.assertIn('removed: region', output)

    # ── Reordered common columns (criterion 4) ────────────────────────────

    def test_reordered_banner(self):
        output = self.get_output([self.BASE, self.REORDERED, '-c', 'id'])
        self.assertIn('reordered: true', output)

    # ── All three at once ─────────────────────────────────────────────────

    def test_all_three_deltas_in_banner(self):
        output = self.get_output([self.BASE, self.ALL_RIGHT, '-c', 'id'])
        self.assertIn('added: region', output)
        self.assertIn('removed: name', output)
        self.assertIn('reordered: true', output)

    # ── Schema-only difference exits 1, not 0 (criterion 5) ───────────────

    def test_schema_only_difference_exits_1(self):
        """Zero row diffs but a reordered schema must exit 1, not 0."""
        output = self.get_output([self.BASE, self.REORDERED, '-c', 'id'])
        self.assertEqual(output.splitlines()[-1], '0 changed, 0 added, 0 removed (of 2 rows compared)')
        code = self._exit_code_for([self.BASE, self.REORDERED, '-c', 'id'])
        self.assertEqual(code, 1)

    # ── --no-schema-check (criterion 6) ───────────────────────────────────

    def test_no_schema_check_suppresses_banner(self):
        output = self.get_output([self.BASE, self.ADDED, '-c', 'id', '--no-schema-check'])
        self.assertNotIn('! schema changed', output)

    def test_no_schema_check_schema_only_diff_exits_0(self):
        """With --no-schema-check, a schema-only difference no longer drives the exit code."""
        code = self._exit_code_for([self.BASE, self.REORDERED, '-c', 'id', '--no-schema-check'])
        self.assertEqual(code, 0)

    def test_no_schema_check_row_diff_still_exits_1(self):
        """--no-schema-check only mutes schema; genuine row diffs still exit 1."""
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--no-schema-check'])
        self.assertEqual(code, 1)

    # ── -H/--no-header-row suppression (criterion 7) ──────────────────────

    def test_header_row_off_suppresses_banner(self):
        output = self.get_output([self.BASE, self.ADDED, '-H'])
        self.assertNotIn('! schema changed', output)

    def test_header_row_off_suppresses_schema_in_exit_code(self):
        """Under -H the column-count difference must not drive the exit code to 1."""
        code = self._exit_code_for([self.BASE, self.ADDED, '-H'])
        self.assertEqual(code, 0)

    def test_header_row_off_overrides_no_schema_check_flag(self):
        """-H suppresses the schema section regardless of --no-schema-check."""
        output = self.get_output([self.BASE, self.ADDED, '-H', '--no-schema-check'])
        self.assertNotIn('! schema changed', output)

    # ── Rename surfaces as removed + added (criterion 8) ──────────────────

    def test_rename_reported_as_removed_plus_added(self):
        output = self.get_output([self.RENAME_L, self.RENAME_R, '-c', 'id'])
        self.assertIn('removed: qty', output)
        self.assertIn('added: quantity', output)

    # ── Schema banner also works in positional (no-key) mode ──────────────

    def test_schema_banner_in_positional_mode(self):
        output = self.get_output([self.BASE, self.ADDED])
        self.assertTrue(output.startswith('! schema changed:'))
        self.assertIn('added: region', output)

    # ── Documentation of -H suppression in epilog ─────────────────────────

    def test_epilog_documents_header_row_suppression(self):
        self.assertIn('--no-schema-check', CSVDiff.epilog)
        self.assertIn('-H', CSVDiff.epilog)
        self.assertIn('schema', CSVDiff.epilog)


class TestCSVDiffJSONL(_CSVDiffOutputMixin, CSVKitTestCase):
    """Tests for --format=jsonl (render_jsonl)."""

    Utility = CSVDiff

    def _parse_jsonl(self, output):
        """Parse each non-empty line of output as a JSON object."""
        return [json.loads(line) for line in output.splitlines() if line.strip()]

    # ── Equal-files: summary only, all-zero counts ──────────────────────

    def test_equal_files_emits_summary_only(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_a.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev['event'], 'summary')
        self.assertEqual(ev['compared'], 3)
        self.assertEqual(ev['changed'], 0)
        self.assertEqual(ev['added'], 0)
        self.assertEqual(ev['removed'], 0)
        self.assertFalse(ev['schema_changed'])

    # ── Every line independently parseable ──────────────────────────────

    def test_every_line_parseable(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        for line in output.splitlines():
            if line.strip():
                self.assertIsInstance(json.loads(line), dict)

    # ── Row-only diff: summary + row events, no schema event ────────────

    def test_row_diff_emits_summary_and_row_events(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        self.assertEqual(events[0]['event'], 'summary')
        self.assertFalse(any(e['event'] == 'schema' for e in events))
        self.assertTrue(any(e['event'] == 'row' for e in events))

    def test_summary_counts_match_row_events(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        summary = events[0]
        row_events = [e for e in events if e['event'] == 'row']
        self.assertEqual(summary['changed'], sum(1 for e in row_events if e['status'] == 'changed'))
        self.assertEqual(summary['added'], sum(1 for e in row_events if e['status'] == 'added'))
        self.assertEqual(summary['removed'], sum(1 for e in row_events if e['status'] == 'removed'))

    # ── changed row: fields shape {col: {left: ..., right: ...}} ────────

    def test_changed_row_fields_shape(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        changed = [e for e in events if e['event'] == 'row' and e['status'] == 'changed']
        self.assertTrue(len(changed) > 0)
        for ev in changed:
            for col, val in ev['fields'].items():
                self.assertIn('left', val)
                self.assertIn('right', val)

    # ── added row: fields shape {col: value} (flat) ─────────────────────

    def test_added_row_fields_shape(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        added = [e for e in events if e['event'] == 'row' and e['status'] == 'added']
        self.assertTrue(len(added) > 0)
        for ev in added:
            for col, val in ev['fields'].items():
                self.assertNotIsInstance(val, dict)

    # ── removed row: fields shape {col: value} (flat) ───────────────────

    def test_removed_row_fields_shape(self):
        output = self.get_output(['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        events = self._parse_jsonl(output)
        removed = [e for e in events if e['event'] == 'row' and e['status'] == 'removed']
        self.assertTrue(len(removed) > 0)
        for ev in removed:
            for col, val in ev['fields'].items():
                self.assertNotIsInstance(val, dict)

    # ── Schema-only diff: summary + schema event, no row events ─────────

    def test_schema_only_diff_emits_schema_event(self):
        # diff_schema_base vs diff_schema_reordered: reordered common columns, no row diffs
        output = self.get_output([
            'examples/diff_schema_base.csv', 'examples/diff_schema_reordered.csv',
            '-c', 'id', '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        self.assertEqual(events[0]['event'], 'summary')
        self.assertTrue(events[0]['schema_changed'])
        schema_events = [e for e in events if e['event'] == 'schema']
        self.assertEqual(len(schema_events), 1)
        self.assertIn('added_columns', schema_events[0])
        self.assertIn('removed_columns', schema_events[0])
        self.assertIn('reordered', schema_events[0])
        self.assertFalse(any(e['event'] == 'row' for e in events))

    def test_schema_event_fields(self):
        # diff_schema_base (id,name,price) vs diff_schema_added (id,name,price,region)
        output = self.get_output([
            'examples/diff_schema_base.csv', 'examples/diff_schema_added.csv',
            '-c', 'id', '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        schema_ev = next(e for e in events if e['event'] == 'schema')
        self.assertIn('region', schema_ev['added_columns'])
        self.assertEqual(schema_ev['removed_columns'], [])

    # ── Combined row + schema diff ───────────────────────────────────────

    def test_combined_schema_and_row_diff(self):
        output = self.get_output([
            'examples/diff_schema_base.csv', 'examples/diff_schema_added_changed.csv',
            '-c', 'id', '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        event_types = [e['event'] for e in events]
        self.assertEqual(event_types[0], 'summary')
        self.assertIn('schema', event_types)
        self.assertIn('row', event_types)
        # schema event must come before row events
        schema_idx = event_types.index('schema')
        first_row_idx = event_types.index('row')
        self.assertLess(schema_idx, first_row_idx)

    # ── --no-schema-check suppresses schema event ────────────────────────

    def test_no_schema_check_suppresses_schema_event(self):
        output = self.get_output([
            'examples/diff_schema_base.csv', 'examples/diff_schema_added_changed.csv',
            '-c', 'id', '--format', 'jsonl', '--no-schema-check',
        ])
        events = self._parse_jsonl(output)
        self.assertFalse(events[0]['schema_changed'])
        self.assertFalse(any(e['event'] == 'schema' for e in events))

    # ── Composite key shape ──────────────────────────────────────────────

    def test_composite_key_shape(self):
        output = self.get_output([
            'examples/diff_composite_a.csv', 'examples/diff_composite_b.csv',
            '-c', 'order_id,line_no', '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        row_events = [e for e in events if e['event'] == 'row']
        self.assertTrue(len(row_events) > 0)
        for ev in row_events:
            self.assertIn('order_id', ev['key'])
            self.assertIn('line_no', ev['key'])

    # ── No-key positional key shape: {"row": N} ─────────────────────────

    def test_positional_key_shape(self):
        output = self.get_output([
            'examples/diff_pos_a.csv', 'examples/diff_pos_b.csv',
            '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        row_events = [e for e in events if e['event'] == 'row']
        self.assertTrue(len(row_events) > 0)
        for ev in row_events:
            self.assertIn('row', ev['key'])
            self.assertIsInstance(ev['key']['row'], int)

    # ── Decimal / date serialization via default_str_decimal ────────────

    def test_decimal_serialization_via_default_str_decimal(self):
        # Without -I, agate infers the price column as Decimal; render_jsonl must
        # serialize it via default_str_decimal (not raise TypeError from json.dumps).
        output = self.get_output([
            'examples/diff_a.csv', 'examples/diff_b.csv',
            '-c', 'id', '--format', 'jsonl',
        ])
        events = self._parse_jsonl(output)
        changed = [e for e in events if e.get('status') == 'changed']
        self.assertTrue(len(changed) > 0)
        for ev in changed:
            if 'price' in ev['fields']:
                self.assertIsInstance(ev['fields']['price']['left'], str)
                self.assertIsInstance(ev['fields']['price']['right'], str)

    # ── Exit codes unchanged ─────────────────────────────────────────────

    def test_exit_code_0_equal_files(self):
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_a.csv', '-c', 'id', '--format', 'jsonl'])
        self.assertEqual(code, 0)

    def test_exit_code_1_differences(self):
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'id', '--format', 'jsonl'])
        self.assertEqual(code, 1)

    def test_exit_code_2_bad_key(self):
        code = self._exit_code_for(
            ['examples/diff_a.csv', 'examples/diff_b.csv', '-c', 'nonexistent', '--format', 'jsonl'])
        self.assertEqual(code, 2)

    # ── render_jsonl unit test: engine independence ──────────────────────

    def test_render_jsonl_engine_unit(self):
        """render_jsonl can be called directly on a DiffResult without the CLI."""
        schema = SchemaDelta(added=[], removed=[], reordered=False, common=['name', 'score'])
        row_diffs = [
            RowDelta(status='changed', key=(1,), fields={'score': (10, 20)}),
            RowDelta(status='added', key=(2,), fields={'name': (None, 'Bob'), 'score': (None, 30)}),
            RowDelta(status='removed', key=(3,), fields={'name': ('Alice', None), 'score': (5, None)}),
        ]
        result = DiffResult(schema=schema, row_diffs=row_diffs, unchanged_count=0, compared_count=2)
        buf = io.StringIO()
        render_jsonl(result, ['id'], buf, show_schema=False)
        events = [json.loads(line) for line in buf.getvalue().splitlines() if line]
        self.assertEqual(events[0]['event'], 'summary')
        self.assertEqual(events[0]['changed'], 1)
        self.assertEqual(events[0]['added'], 1)
        self.assertEqual(events[0]['removed'], 1)
        changed_ev = next(e for e in events if e.get('status') == 'changed')
        self.assertEqual(changed_ev['fields']['score'], {'left': 10, 'right': 20})
        added_ev = next(e for e in events if e.get('status') == 'added')
        self.assertEqual(added_ev['fields']['name'], 'Bob')
        removed_ev = next(e for e in events if e.get('status') == 'removed')
        self.assertEqual(removed_ev['fields']['name'], 'Alice')
