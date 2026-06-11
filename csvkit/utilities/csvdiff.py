#!/usr/bin/env python

import csv
import sys
from dataclasses import dataclass

import agate
import agate.exceptions

from csvkit.cli import CSVKitUtility, isatty, match_column_identifier
from csvkit.exceptions import ColumnIdentifierError

_PARSE_ERRORS = (csv.Error, UnicodeDecodeError, agate.exceptions.FieldSizeLimitError)


@dataclass
class SchemaDelta:
    added: list
    removed: list
    reordered: bool
    common: list


@dataclass
class RowDelta:
    status: str
    key: tuple
    fields: dict


@dataclass
class DiffResult:
    schema: SchemaDelta
    row_diffs: list
    unchanged_count: int
    compared_count: int


def _key_display(key_name, key_tuple):
    val = key_tuple[0]
    return '{}={}'.format(key_name, '' if val is None else str(val))


def _fmt(val):
    return '' if val is None else str(val)


def render_human(result, key_name, output_file):
    changed = [d for d in result.row_diffs if d.status == 'changed']
    added = [d for d in result.row_diffs if d.status == 'added']
    removed = [d for d in result.row_diffs if d.status == 'removed']

    output_file.write('{} changed, {} added, {} removed (of {} rows compared)\n'.format(
        len(changed), len(added), len(removed), result.compared_count,
    ))

    for delta in result.row_diffs:
        key_part = _key_display(key_name, delta.key)
        if delta.status == 'removed':
            field_parts = ['{}={}'.format(col, _fmt(left)) for col, (left, _) in delta.fields.items()]
            output_file.write('- {}   {}\n'.format(key_part, '  '.join(field_parts)))
        elif delta.status == 'changed':
            field_parts = ['{}: {} -> {}'.format(col, _fmt(left), _fmt(right))
                           for col, (left, right) in delta.fields.items()]
            output_file.write('~ {}   {}\n'.format(key_part, '  '.join(field_parts)))
        elif delta.status == 'added':
            field_parts = ['{}={}'.format(col, _fmt(right)) for col, (_, right) in delta.fields.items()]
            output_file.write('+ {}   {}\n'.format(key_part, '  '.join(field_parts)))


def _compute_diff(left_table, right_table, left_key_name, right_key_name, ignore_names):
    left_cols = list(left_table.column_names)
    right_cols = list(right_table.column_names)
    left_set = set(left_cols)
    right_set = set(right_cols)

    schema = SchemaDelta(
        added=[c for c in right_cols if c not in left_set],
        removed=[c for c in left_cols if c not in right_set],
        reordered=[c for c in left_cols if c in right_set] != [c for c in right_cols if c in left_set],
        common=[c for c in left_cols if c in right_set],
    )

    compare_cols = [c for c in schema.common if c != left_key_name and c not in ignore_names]

    left_key_index = {}
    for i, row in enumerate(left_table.rows):
        key = (row[left_key_name],)
        left_key_index[key] = i

    right_key_index = {}
    for i, row in enumerate(right_table.rows):
        key = (row[right_key_name],)
        right_key_index[key] = i

    left_keys = list(left_key_index)
    right_keys = list(right_key_index)
    right_key_set = set(right_key_index)

    removed_diffs = []
    changed_diffs = []
    unchanged_count = 0
    compared_count = 0

    for key in left_keys:
        if key in right_key_set:
            compared_count += 1
            left_row = left_table.rows[left_key_index[key]]
            right_row = right_table.rows[right_key_index[key]]
            field_diffs = {
                col: (left_row[col], right_row[col])
                for col in compare_cols
                if left_row[col] != right_row[col]
            }
            if field_diffs:
                changed_diffs.append(RowDelta(status='changed', key=key, fields=field_diffs))
            else:
                unchanged_count += 1
        else:
            left_row = left_table.rows[left_key_index[key]]
            non_key_cols = [c for c in left_cols if c != left_key_name]
            fields = {col: (left_row[col], None) for col in non_key_cols}
            removed_diffs.append(RowDelta(status='removed', key=key, fields=fields))

    added_diffs = []
    left_key_set = set(left_key_index)
    for key in right_keys:
        if key not in left_key_set:
            right_row = right_table.rows[right_key_index[key]]
            non_key_cols = [c for c in right_cols if c != right_key_name]
            fields = {col: (None, right_row[col]) for col in non_key_cols}
            added_diffs.append(RowDelta(status='added', key=key, fields=fields))

    return DiffResult(
        schema=schema,
        row_diffs=removed_diffs + changed_diffs + added_diffs,
        unchanged_count=unchanged_count,
        compared_count=compared_count,
    )


class CSVDiff(CSVKitUtility):
    description = 'Compare two CSV files semantically, reporting row-level differences.'
    epilog = (
        'Note that csvdiff reads both inputs fully into memory. '
        'With type inference (default), "1" and "1.0" compare equal; use -I to compare raw strings. '
        'Exit codes: 0 = equivalent, 1 = differences found, 2 = usage or parse error. '
        '(Experimental — interface may change.)'
    )
    override_flags = ['f']

    def add_arguments(self):
        self.argparser.add_argument(
            metavar='FILE', nargs='*', dest='input_paths', default=['-'],
            help='The two CSV files to compare. Use "-" for stdin (at most once).')
        self.argparser.add_argument(
            '-c', '--key', dest='key',
            help='Column name or 1-based index identifying each row uniquely.')
        self.argparser.add_argument(
            '--ignore', dest='ignore', default='',
            help='Comma-separated column names or indices to exclude from row comparison.')
        self.argparser.add_argument(
            '-y', '--snifflimit', dest='sniff_limit', type=int, default=1024,
            help='Limit CSV dialect sniffing to the specified number of bytes. '
                 'Specify "0" to disable sniffing entirely, or "-1" to sniff the entire file.')
        self.argparser.add_argument(
            '-I', '--no-inference', dest='no_inference', action='store_true',
            help='Disable type inference when parsing the input. Compare as raw strings.')

    def main(self):
        paths = self.args.input_paths

        if isatty(sys.stdin) and paths == ['-']:
            self.argparser.error('Provide two input files, or one file plus piped data on stdin.')

        if len(paths) == 1 and paths[0] != '-' and not isatty(sys.stdin):
            left_path, right_path = '-', paths[0]
        elif len(paths) == 2:
            left_path, right_path = paths[0], paths[1]
        elif len(paths) > 2:
            self.argparser.error('csvdiff accepts exactly two inputs.')
        else:
            self.argparser.error('Provide two input files, or one file plus piped data on stdin.')

        if left_path == '-' and right_path == '-':
            self.argparser.error('Stdin ("-") may only be used for one input.')

        if not self.args.key:
            self.argparser.error('A key column is required. Use -c/--key to specify it.')

        left_file = self._open_input_file(left_path)
        right_file = self._open_input_file(right_path, opened=(left_path == '-'))

        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        column_types = self.get_column_types()

        left_table = self._read_table(left_file, 'LEFT', left_path, sniff_limit, column_types)
        right_table = self._read_table(right_file, 'RIGHT', right_path, sniff_limit, column_types)

        try:
            left_key_idx = match_column_identifier(
                left_table.column_names, self.args.key, self.get_column_offset())
        except ColumnIdentifierError as e:
            self.argparser.error('LEFT: {}'.format(e))

        try:
            right_key_idx = match_column_identifier(
                right_table.column_names, self.args.key, self.get_column_offset())
        except ColumnIdentifierError as e:
            self.argparser.error('RIGHT: {}'.format(e))

        left_key_name = left_table.column_names[left_key_idx]
        right_key_name = right_table.column_names[right_key_idx]

        ignore_names = self._resolve_ignore_cols(left_table, right_table)

        result = _compute_diff(left_table, right_table, left_key_name, right_key_name, ignore_names)

        render_human(result, left_key_name, self.output_file)

        if result.row_diffs:
            sys.exit(1)

    def _read_table(self, f, label, path, sniff_limit, column_types):
        try:
            table = agate.Table.from_csv(
                f,
                skip_lines=self.args.skip_lines,
                sniff_limit=sniff_limit,
                column_types=column_types,
                **self.reader_kwargs,
            )
            f.close()
            return table
        except _PARSE_ERRORS as e:
            self.argparser.error('{} ({}): {}'.format(label, path, e))

    def _resolve_ignore_cols(self, left_table, right_table):
        ignore_names = set()
        if not self.args.ignore:
            return ignore_names
        offset = self.get_column_offset()
        for part in self.args.ignore.split(','):
            part = part.strip()
            if not part:
                continue
            for table in (left_table, right_table):
                try:
                    idx = match_column_identifier(table.column_names, part, offset)
                    ignore_names.add(table.column_names[idx])
                except ColumnIdentifierError:
                    pass
        return ignore_names


def launch_new_instance():
    utility = CSVDiff()
    utility.run()


if __name__ == '__main__':
    launch_new_instance()
