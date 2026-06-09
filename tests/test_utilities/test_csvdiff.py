import io
import json
import sys
from unittest.mock import patch

from csvkit.utilities.csvdiff import CSVDiff, launch_new_instance
from tests.utils import CSVKitTestCase, EmptyFileTests, stdin_as_string


class TestCSVDiff(CSVKitTestCase, EmptyFileTests):
    Utility = CSVDiff
    default_args = ['examples/dummy.csv', 'examples/dummy.csv']

    def test_launch_new_instance(self):
        with patch.object(
            sys, 'argv',
            [self.Utility.__name__.lower(), 'examples/diff_a.csv', 'examples/diff_a.csv'],
        ):
            launch_new_instance()

    def _run(self, args):
        output_file = io.StringIO()
        utility = CSVDiff(args, output_file)
        exit_code = 0
        try:
            utility.run()
        except SystemExit as e:
            exit_code = e.code
        return output_file.getvalue(), exit_code

    def test_identical_files_exit_zero(self):
        output, code = self._run(['examples/diff_a.csv', 'examples/diff_a.csv'])
        self.assertEqual(code, 0)
        self.assertIn('0 added, 0 removed, 0 changed, 3 unchanged', output)
        self.assertNotIn('Row differences', output)
        self.assertNotIn('Schema differences', output)

    def test_added_rows(self):
        output, code = self._run(['-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
        self.assertIn('1 added', output)
        self.assertIn('+ [4]', output)
        self.assertIn('name=Dave', output)

    def test_removed_rows(self):
        output, code = self._run(['-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
        self.assertIn('1 removed', output)
        self.assertIn('- [3]', output)
        self.assertIn('name=Carol', output)

    def test_changed_rows_per_field(self):
        output, code = self._run(['-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
        self.assertIn('1 changed', output)
        self.assertIn('~ [2] age: 25 -> 26', output)
        # Unchanged fields are NOT reported as part of the changed row.
        changed_line = next(line for line in output.splitlines() if line.startswith('~ [2]'))
        self.assertNotIn('name:', changed_line)

    def test_unchanged_rows_not_reported(self):
        output, code = self._run(['-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
        # Alice (id=1) is unchanged; her row should not appear under "Row differences".
        diff_section = output.split('Row differences:', 1)[1] if 'Row differences:' in output else ''
        self.assertNotIn('Alice', diff_section)
        self.assertIn('1 unchanged', output)

    def test_composite_key(self):
        output, code = self._run([
            '-k', 'year,quarter', 'examples/diff_composite_a.csv', 'examples/diff_composite_b.csv',
        ])
        self.assertEqual(code, 1)
        self.assertIn('1 added', output)
        self.assertIn('1 changed', output)
        self.assertIn('~ [2024 | Q2] revenue: 150 -> 155', output)
        self.assertIn('[2024 | Q4]', output)

    def test_resorted_file_no_row_differences(self):
        output, code = self._run([
            '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_resorted.csv',
        ])
        self.assertEqual(code, 0)
        self.assertIn('0 added, 0 removed, 0 changed, 3 unchanged', output)

    def test_schema_added_column(self):
        output, code = self._run([
            '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_added_col.csv',
        ])
        self.assertEqual(code, 1)
        self.assertIn('Schema differences:', output)
        self.assertIn('+ column: city', output)
        # All three rows match on key + remaining common columns, so no row-level diff.
        self.assertIn('0 added, 0 removed, 0 changed, 3 unchanged', output)

    def test_schema_removed_column(self):
        output, code = self._run([
            '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_removed_col.csv',
        ])
        self.assertEqual(code, 1)
        self.assertIn('- column: age', output)

    def test_schema_reordered_columns(self):
        output, code = self._run([
            '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_reordered_col.csv',
        ])
        self.assertEqual(code, 1)
        self.assertIn('shared columns appear in a different order', output)
        # Reordering alone should not produce row-level diffs: data is matched by column name.
        self.assertIn('0 added, 0 removed, 0 changed, 3 unchanged', output)

    def test_typed_equality_default(self):
        # With default type inference, "30" and "30.0" compare equal as numbers.
        output, code = self._run([
            '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_typed.csv',
        ])
        self.assertEqual(code, 0)
        self.assertIn('3 unchanged', output)

    def test_no_inference_string_compare(self):
        # With --no-inference, "30" vs "30.0" are different strings.
        output, code = self._run([
            '-I', '-k', 'id', 'examples/diff_a.csv', 'examples/diff_a_typed.csv',
        ])
        self.assertEqual(code, 1)
        self.assertIn('3 changed', output)
        self.assertIn('age: 30 -> 30.0', output)

    def test_no_key_positional_default(self):
        # No --key: rows are compared positionally. diff_b changes row 2 (Bob's age) and
        # row 3 (Carol → Dave).
        output, code = self._run(['examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
        self.assertIn('2 changed', output)
        self.assertIn('0 added, 0 removed', output)

    def test_duplicate_key_within_file(self):
        self.assertError(
            launch_new_instance,
            ['-k', 'id'],
            'Duplicate key (1) found in the first input file; csvdiff requires keys to be unique.',
            args=['examples/diff_a_dup_keys.csv', 'examples/diff_a.csv'],
        )

    def test_bad_key_column(self):
        self.assertError(
            launch_new_instance,
            ['-k', 'nonexistent'],
            "Key column 'nonexistent' was not found in the first input file.",
            args=['examples/diff_a.csv', 'examples/diff_a.csv'],
        )

    def test_requires_two_files(self):
        self.assertError(
            launch_new_instance,
            [],
            'csvdiff requires exactly two input files.',
            args=['examples/diff_a.csv'],
        )

    def test_stdin_input(self):
        with open('examples/diff_b.csv', 'rb') as f, stdin_as_string(f):
            output, code = self._run(['-k', 'id', 'examples/diff_a.csv', '-'])
        self.assertEqual(code, 1)
        self.assertIn('1 added', output)
        self.assertIn('1 removed', output)
        self.assertIn('1 changed', output)

    def test_json_format(self):
        output, code = self._run([
            '--format', 'json', '-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv',
        ])
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload['summary'], {
            'added': 1, 'removed': 1, 'changed': 1, 'unchanged': 1,
        })
        self.assertEqual(payload['mode'], 'keyed')
        self.assertEqual(payload['key_columns'], ['id'])
        self.assertEqual(len(payload['rows']['added']), 1)
        self.assertEqual(payload['rows']['added'][0]['key'], ['4'])
        self.assertEqual(payload['rows']['removed'][0]['key'], ['3'])
        change = payload['rows']['changed'][0]
        self.assertEqual(change['key'], ['2'])
        self.assertEqual(change['changes'], [{'column': 'age', 'a': '25', 'b': '26'}])

    def test_csv_format(self):
        output, code = self._run([
            '--format', 'csv', '-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv',
        ])
        self.assertEqual(code, 1)
        lines = [line for line in output.splitlines() if line]
        self.assertEqual(lines[0], 'status,key,column,a,b')
        # A row for the changed field with the correct before/after values.
        self.assertIn('changed,2,age,25,26', lines)
        # Removed row emits one record per column.
        removed_lines = [line for line in lines if line.startswith('removed,3,')]
        self.assertEqual(len(removed_lines), 3)
        added_lines = [line for line in lines if line.startswith('added,4,')]
        self.assertEqual(len(added_lines), 3)

    def test_csv_format_schema(self):
        output, code = self._run([
            '--format', 'csv', '-k', 'id',
            'examples/diff_a.csv', 'examples/diff_a_added_col.csv',
        ])
        self.assertEqual(code, 1)
        lines = output.splitlines()
        self.assertIn('schema_added,,city,,', lines)

    def test_exit_code_identical(self):
        _, code = self._run(['examples/diff_a.csv', 'examples/diff_a.csv'])
        self.assertEqual(code, 0)

    def test_exit_code_differences(self):
        _, code = self._run(['-k', 'id', 'examples/diff_a.csv', 'examples/diff_b.csv'])
        self.assertEqual(code, 1)
