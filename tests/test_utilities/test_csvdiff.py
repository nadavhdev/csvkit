import io
import sys
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import agate

from csvkit.utilities.csvdiff import CSVDiff, _compute_diff, launch_new_instance
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


class TestCSVDiffEngine(unittest.TestCase):
    """Unit tests for the diff engine, independent of the CLI."""

    def test_schema_delta_added_removed(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'value'])
        result = _compute_diff(left, right, 'id', 'id', set())
        self.assertEqual(result.schema.added, ['value'])
        self.assertEqual(result.schema.removed, ['name'])

    def test_schema_delta_reordered(self):
        left = agate.Table([('1', 'a', '1')], column_names=['id', 'name', 'price'])
        right = agate.Table([('1', '1', 'a')], column_names=['id', 'price', 'name'])
        result = _compute_diff(left, right, 'id', 'id', set())
        self.assertTrue(result.schema.reordered)

    def test_schema_no_reorder_when_order_same(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'name'])
        result = _compute_diff(left, right, 'id', 'id', set())
        self.assertFalse(result.schema.reordered)

    def test_unchanged_count_and_zero_diffs(self):
        left = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        right = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        result = _compute_diff(left, right, 'id', 'id', set())
        self.assertEqual(result.unchanged_count, 2)
        self.assertEqual(result.compared_count, 2)
        self.assertEqual(result.row_diffs, [])

    def test_diff_ordering(self):
        """Removed in LEFT order → changed in LEFT order → added in RIGHT order."""
        left = agate.Table([('1', 'a'), ('2', 'b'), ('3', 'c')], column_names=['id', 'name'])
        right = agate.Table([('2', 'b'), ('3', 'X'), ('4', 'd')], column_names=['id', 'name'])
        result = _compute_diff(left, right, 'id', 'id', set())
        statuses = [d.status for d in result.row_diffs]
        self.assertEqual(statuses, ['removed', 'changed', 'added'])
        self.assertEqual(str(result.row_diffs[0].key[0]), '1')
        self.assertEqual(str(result.row_diffs[1].key[0]), '3')
        self.assertEqual(str(result.row_diffs[2].key[0]), '4')

    def test_ignore_cols_suppresses_diff(self):
        left = agate.Table([('1', 'a', '10')], column_names=['id', 'name', 'ts'])
        right = agate.Table([('1', 'a', '99')], column_names=['id', 'name', 'ts'])
        result = _compute_diff(left, right, 'id', 'id', {'ts'})
        self.assertEqual(result.row_diffs, [])
        self.assertEqual(result.unchanged_count, 1)

    def test_ignore_key_col_name_is_noop(self):
        left = agate.Table([('1', 'a')], column_names=['id', 'name'])
        right = agate.Table([('1', 'b')], column_names=['id', 'name'])
        result_with = _compute_diff(left, right, 'id', 'id', {'id'})
        result_without = _compute_diff(left, right, 'id', 'id', set())
        # ignoring the key column is a no-op on changed detection
        self.assertEqual(len(result_with.row_diffs), len(result_without.row_diffs))

    def test_added_and_removed_counts(self):
        left = agate.Table([('1', 'a'), ('2', 'b')], column_names=['id', 'name'])
        right = agate.Table([('2', 'b'), ('3', 'c')], column_names=['id', 'name'])
        result = _compute_diff(left, right, 'id', 'id', set())
        removed = [d for d in result.row_diffs if d.status == 'removed']
        added = [d for d in result.row_diffs if d.status == 'added']
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(added), 1)
        self.assertEqual(result.compared_count, 1)
        self.assertEqual(result.unchanged_count, 1)
