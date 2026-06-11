#!/usr/bin/env python

import csv
import sys
from dataclasses import dataclass

import agate
import agate.exceptions

from csvkit.cli import CSVKitUtility, isatty, match_column_identifier
from csvkit.exceptions import ColumnIdentifierError

_PARSE_ERRORS = (csv.Error, UnicodeDecodeError, agate.exceptions.FieldSizeLimitError)


class DuplicateKeyError(Exception):
    """Raised when on_dup='error' and a key tuple appears more than once in a file."""
    def __init__(self, side, key_names, key_tuple, first_idx, dup_idx):
        key_str = _key_display(key_names, key_tuple)
        super().__init__(
            '{}: duplicate key {} first seen at row {}, repeated at row {}'.format(
                side, key_str, first_idx + 1, dup_idx + 1)
        )


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


def _compute_schema_delta(left_cols, right_cols):
    """Build a SchemaDelta from two column-name lists.

    added:     columns in RIGHT not in LEFT, in RIGHT's order.
    removed:   columns in LEFT not in RIGHT, in LEFT's order.
    reordered: True when the shared columns appear in a different relative order.
    common:    shared columns in LEFT's order — the column set row diffs run on.
    """
    left_col_set = set(left_cols)
    right_col_set = set(right_cols)
    common_left_order = [c for c in left_cols if c in right_col_set]
    common_right_order = [c for c in right_cols if c in left_col_set]
    return SchemaDelta(
        added=[c for c in right_cols if c not in left_col_set],
        removed=[c for c in left_cols if c not in right_col_set],
        reordered=common_left_order != common_right_order,
        common=common_left_order,
    )


def _schema_changed(schema):
    """True when columns were added, removed, or reordered between the two files."""
    return bool(schema.added or schema.removed or schema.reordered)


def _key_display(key_names, key_tuple):
    """Format a key tuple for human output. Single key: name=val. Composite: key=(v1,v2)."""
    if len(key_names) == 1:
        val = key_tuple[0]
        return '{}={}'.format(key_names[0], '' if val is None else str(val))
    parts = ','.join('' if v is None else str(v) for v in key_tuple)
    return 'key=({})'.format(parts)


def _fmt(val):
    return '' if val is None else str(val)


def _render_schema_banner(schema, output_file):
    """Emit the '! schema changed:' block. Only non-empty deltas produce a line."""
    output_file.write('! schema changed:\n')
    if schema.added:
        output_file.write('  added: {}\n'.format(', '.join(schema.added)))
    if schema.removed:
        output_file.write('  removed: {}\n'.format(', '.join(schema.removed)))
    if schema.reordered:
        output_file.write('  reordered: true\n')


def render_human(result, key_names, output_file, show_schema=False):
    if show_schema and _schema_changed(result.schema):
        _render_schema_banner(result.schema, output_file)

    changed = [d for d in result.row_diffs if d.status == 'changed']
    added = [d for d in result.row_diffs if d.status == 'added']
    removed = [d for d in result.row_diffs if d.status == 'removed']

    output_file.write('{} changed, {} added, {} removed (of {} rows compared)\n'.format(
        len(changed), len(added), len(removed), result.compared_count,
    ))

    for delta in result.row_diffs:
        key_part = _key_display(key_names, delta.key)
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


def _build_key_index(table, key_names, on_dup, side):
    """Build dict[key_tuple -> list[row_index]], applying the on_dup policy.

    Raises DuplicateKeyError immediately if on_dup='error' and a duplicate is found.
    With on_dup='first', only the first occurrence per key is stored.
    With on_dup='all', all occurrences are stored.
    """
    index = {}
    for i, row in enumerate(table.rows):
        key = tuple(row[name] for name in key_names)
        if key in index:
            if on_dup == 'error':
                raise DuplicateKeyError(side, key_names, key, index[key][0], i)
            elif on_dup == 'first':
                continue
            else:  # 'all'
                index[key].append(i)
        else:
            index[key] = [i]
    return index


def _compute_positional_diff(left_table, right_table, ignore_names):
    """Compare rows positionally (no key) when -c/--key is absent.

    Row N of LEFT is compared to row N of RIGHT. Surplus rows on the longer
    side are classified as removed (LEFT longer) or added (RIGHT longer). The
    row key in each RowDelta is the 1-based row index.
    """
    left_cols = list(left_table.column_names)
    right_cols = list(right_table.column_names)
    schema = _compute_schema_delta(left_cols, right_cols)

    compare_cols = [c for c in schema.common if c not in ignore_names]
    left_rows = list(left_table.rows)
    right_rows = list(right_table.rows)
    n_left, n_right = len(left_rows), len(right_rows)
    compared_count = min(n_left, n_right)

    changed_diffs = []
    unchanged_count = 0
    for i in range(compared_count):
        key = (i + 1,)
        left_row, right_row = left_rows[i], right_rows[i]
        field_diffs = {
            col: (left_row[col], right_row[col])
            for col in compare_cols
            if left_row[col] != right_row[col]
        }
        if field_diffs:
            changed_diffs.append(RowDelta(status='changed', key=key, fields=field_diffs))
        else:
            unchanged_count += 1

    # Surplus rows show all columns, matching keyed-mode behavior where --ignore
    # suppresses comparison but does not hide fields from removed/added display.
    removed_diffs = [
        RowDelta(
            status='removed',
            key=(i + 1,),
            fields={col: (left_rows[i][col], None) for col in left_cols},
        )
        for i in range(compared_count, n_left)
    ]

    added_diffs = [
        RowDelta(
            status='added',
            key=(i + 1,),
            fields={col: (None, right_rows[i][col]) for col in right_cols},
        )
        for i in range(compared_count, n_right)
    ]

    return DiffResult(
        schema=schema,
        row_diffs=removed_diffs + changed_diffs + added_diffs,
        unchanged_count=unchanged_count,
        compared_count=compared_count,
    )


def _compute_diff(left_table, right_table, left_key_names, right_key_names, on_dup, ignore_names):
    """Compute the diff between two agate tables keyed by the given column name lists.

    left_key_names / right_key_names: lists of resolved column names forming the composite key.
    on_dup: 'error' | 'first' | 'all' — controls duplicate-key behavior.
    ignore_names: set of column names to exclude from row comparison.

    Raises DuplicateKeyError (exit-2 class) when on_dup='error' and duplicates are found.
    """
    left_cols = list(left_table.column_names)
    right_cols = list(right_table.column_names)
    schema = _compute_schema_delta(left_cols, right_cols)

    all_key_names = set(left_key_names) | set(right_key_names)
    compare_cols = [c for c in schema.common if c not in all_key_names and c not in ignore_names]

    left_non_key_cols = [c for c in left_cols if c not in all_key_names]
    right_non_key_cols = [c for c in right_cols if c not in all_key_names]

    left_key_index = _build_key_index(left_table, left_key_names, on_dup, 'LEFT')
    right_key_index = _build_key_index(right_table, right_key_names, on_dup, 'RIGHT')

    left_keys = list(left_key_index)
    right_keys = list(right_key_index)
    right_keys_present = set(right_key_index)

    removed_diffs = []
    changed_diffs = []
    unchanged_count = 0
    compared_count = 0

    for key in left_keys:
        if key in right_keys_present:
            for li in left_key_index[key]:
                for ri in right_key_index[key]:
                    compared_count += 1
                    left_row = left_table.rows[li]
                    right_row = right_table.rows[ri]
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
            for li in left_key_index[key]:
                left_row = left_table.rows[li]
                fields = {col: (left_row[col], None) for col in left_non_key_cols}
                removed_diffs.append(RowDelta(status='removed', key=key, fields=fields))

    added_diffs = []
    left_keys_present = set(left_key_index)
    for key in right_keys:
        if key not in left_keys_present:
            for ri in right_key_index[key]:
                right_row = right_table.rows[ri]
                fields = {col: (None, right_row[col]) for col in right_non_key_cols}
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
        'Without -c/--key, rows are compared positionally (row N vs row N). '
        'A re-sorted file will produce wide spurious diffs in positional mode — use -c to compare by row identity. '
        'Added, removed, or reordered columns are reported in a "! schema changed:" banner before the row diff '
        'and count as a difference (exit 1); pass --no-schema-check to skip the banner and compare only the '
        'shared columns. With -H/--no-header-row the schema banner is suppressed entirely, because synthetic '
        'column names (a, b, c, ...) make schema drift meaningless. '
        'With --on-dup=all, duplicate keys on both sides produce a Cartesian product of comparisons, '
        'which can be O(n*m) per key with large duplicate groups — use with caution. '
        '(Experimental - interface may change.)'
    )
    override_flags = ['f']

    def add_arguments(self):
        self.argparser.add_argument(
            metavar='FILE', nargs='*', dest='input_paths', default=['-'],
            help='The two CSV files to compare. Use "-" for stdin (at most once).')
        self.argparser.add_argument(
            '-c', '--key', dest='key',
            help='Column name(s) or 1-based index(es) identifying each row uniquely. '
                 'Comma-separated for composite keys (e.g. -c "order_id,line_no").')
        self.argparser.add_argument(
            '--on-dup', dest='on_dup', default='error',
            choices=['error', 'first', 'all'],
            help='Behavior when --key is not unique within a file. '
                 '"error" (default): exit 2 naming the duplicate key and rows. '
                 '"first": keep only the first occurrence of each key. '
                 '"all": compare the Cartesian product of all matching duplicate rows '
                 '(warning: O(n*m) per key; large duplicate groups can produce enormous output).')
        self.argparser.add_argument(
            '--ignore', dest='ignore', default='',
            help='Comma-separated column names or indices to exclude from row comparison.')
        self.argparser.add_argument(
            '--no-schema-check', dest='no_schema_check', action='store_true',
            help='Skip the schema-drift section. Added, removed, or reordered columns are '
                 'no longer reported in a banner or counted toward the exit code; rows are '
                 'compared on the shared columns as if the schemas were identical.')
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

        left_file = self._open_input_file(left_path)
        right_file = self._open_input_file(right_path, opened=(left_path == '-'))

        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        column_types = self.get_column_types()

        left_table = self._read_table(left_file, 'LEFT', left_path, sniff_limit, column_types)
        right_table = self._read_table(right_file, 'RIGHT', right_path, sniff_limit, column_types)

        ignore_names = self._resolve_ignore_cols(left_table, right_table)

        # Schema drift is checked unless opted out, or suppressed under -H, where
        # synthetic headers (a, b, c, ...) make the comparison meaningless (TDD OQ7).
        schema_active = not self.args.no_schema_check and not self.args.no_header_row

        if self.args.key:
            left_key_names = self._resolve_key_names(left_table, 'LEFT')
            right_key_names = self._resolve_key_names(right_table, 'RIGHT')
            try:
                result = _compute_diff(
                    left_table, right_table, left_key_names, right_key_names,
                    self.args.on_dup, ignore_names,
                )
            except DuplicateKeyError as e:
                self.argparser.error(str(e))
            render_human(result, left_key_names, self.output_file, show_schema=schema_active)
        else:
            result = _compute_positional_diff(left_table, right_table, ignore_names)
            render_human(result, ['row'], self.output_file, show_schema=schema_active)

        if result.row_diffs or (schema_active and _schema_changed(result.schema)):
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

    def _resolve_key_names(self, table, side):
        """Parse the -c/--key value as comma-separated identifiers and resolve each to a column name."""
        offset = self.get_column_offset()
        key_names = []
        for part in self.args.key.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                idx = match_column_identifier(table.column_names, part, offset)
                key_names.append(table.column_names[idx])
            except ColumnIdentifierError as e:
                self.argparser.error('{}: {}'.format(side, e))
        if not key_names:
            self.argparser.error('A key column is required. Use -c/--key to specify it.')
        return key_names

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
