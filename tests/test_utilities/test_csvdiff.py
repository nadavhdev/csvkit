import io
import sys
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import agate

from csvkit.utilities.csvdiff import (CSVDiff, DuplicateKeyError, _build_key_index, _compute_diff, _key_display,
                                      launch_new_instance)
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

    def test_exit_2_missing_key_flag(self):
        self.assertError(
            launch_new_instance,
            ['examples/diff_a.csv', 'examples/diff_b.csv'],
            'A key column is required. Use -c/--key to specify it.',
            args=[],
        )

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
