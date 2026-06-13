#!/usr/bin/env python

import json
import sys

import agate

from csvkit.cli import CSVKitUtility, isatty, match_column_identifier
from csvkit.exceptions import ColumnIdentifierError

EXIT_DIFFERENT = 1


class CSVDiff(CSVKitUtility):
    description = 'Semantically diff two CSV files: report added, removed, and changed rows.'
    epilog = (
        "Both files are read fully into memory and (when --key is given) indexed by key. "
        "Don't try this on very large files. Values are compared as inferred (typed) data by "
        "default, so \"1\" and \"1.0\" are equal; pass --no-inference to compare cells as raw "
        "strings. Exits 0 when the files are equivalent, 1 when differences are found, and 2 "
        "on usage errors (including duplicate keys within an input, which are not supported)."
    )
    # Override 'f' because the utility accepts two files.
    override_flags = ['f']

    def add_arguments(self):
        self.argparser.add_argument(
            metavar='FILE', nargs='*', dest='input_paths', default=['-'],
            help='The two CSV files to compare. Use "-" to read one of them from STDIN.')
        self.argparser.add_argument(
            '-k', '--key', dest='key',
            help='A comma-separated list of column names or indices that uniquely identify a row. '
                 'When omitted, rows are compared positionally: row N of the first file against row N '
                 'of the second.')
        self.argparser.add_argument(
            '--format', dest='format', choices=('text', 'json', 'csv'), default='text',
            help='Output format for the diff. Defaults to "text", a human-readable summary. '
                 '"json" and "csv" emit structured, machine-readable output.')
        self.argparser.add_argument(
            '-y', '--snifflimit', dest='sniff_limit', type=int, default=1024,
            help='Limit CSV dialect sniffing to the specified number of bytes. '
                 'Specify "0" to disable sniffing entirely, or "-1" to sniff the entire file.')
        self.argparser.add_argument(
            '-I', '--no-inference', dest='no_inference', action='store_true',
            help='Disable type inference (and --locale, --date-format, --datetime-format, '
                 '--no-leading-zeroes) when parsing the input. With this flag, "1" and "1.0" '
                 'compare as different strings.')

    def main(self):
        if isatty(sys.stdin) and self.args.input_paths == ['-']:
            self.argparser.error('You must provide two input files (or one file and piped data).')

        if len(self.args.input_paths) != 2:
            self.argparser.error('csvdiff requires exactly two input files.')

        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        column_types = self.get_column_types()

        tables = []
        for path in self.args.input_paths:
            f = self._open_input_file(path)
            try:
                tables.append(agate.Table.from_csv(
                    f,
                    skip_lines=self.args.skip_lines,
                    sniff_limit=sniff_limit,
                    column_types=column_types,
                    **self.reader_kwargs,
                ))
            finally:
                f.close()

        table_a, table_b = tables
        cols_a = list(table_a.column_names)
        cols_b = list(table_b.column_names)

        schema_diff = self._compute_schema_diff(cols_a, cols_b)
        common_cols = [c for c in cols_a if c in cols_b]

        if self.args.key:
            key_names = [c.strip() for c in self.args.key.split(',')]
            key_ids_a = self._resolve_key_ids(cols_a, key_names, 'first')
            key_ids_b = self._resolve_key_ids(cols_b, key_names, 'second')
            row_diff = self._diff_keyed(
                table_a, table_b, key_ids_a, key_ids_b, key_names, common_cols,
            )
        else:
            row_diff = self._diff_positional(table_a, table_b, common_cols)

        has_diffs = (
            bool(schema_diff['added'])
            or bool(schema_diff['removed'])
            or schema_diff['reordered']
            or bool(row_diff['added'])
            or bool(row_diff['removed'])
            or bool(row_diff['changed'])
        )

        fmt = self.args.format
        if fmt == 'json':
            self._write_json(schema_diff, row_diff)
        elif fmt == 'csv':
            self._write_csv(schema_diff, row_diff)
        else:
            self._write_text(schema_diff, row_diff)

        if has_diffs:
            sys.exit(EXIT_DIFFERENT)

    def _resolve_key_ids(self, column_names, key_names, label):
        ids = []
        offset = self.get_column_offset()
        for name in key_names:
            try:
                ids.append(match_column_identifier(column_names, name, offset))
            except ColumnIdentifierError:
                self.argparser.error(
                    f"Key column '{name}' was not found in the {label} input file.")
        return ids

    def _compute_schema_diff(self, cols_a, cols_b):
        set_a = set(cols_a)
        set_b = set(cols_b)
        added = [c for c in cols_b if c not in set_a]
        removed = [c for c in cols_a if c not in set_b]
        shared_in_a = [c for c in cols_a if c in set_b]
        shared_in_b = [c for c in cols_b if c in set_a]
        reordered = shared_in_a != shared_in_b
        return {'added': added, 'removed': removed, 'reordered': reordered}

    def _index_by_key(self, table, key_ids, label):
        index = {}
        for row in table.rows:
            key = tuple(row[i] for i in key_ids)
            if key in index:
                pretty = ', '.join(self._value_to_str(v) for v in key)
                self.argparser.error(
                    f"Duplicate key ({pretty}) found in the {label} input file; "
                    "csvdiff requires keys to be unique."
                )
            index[key] = row
        return index

    def _diff_keyed(self, table_a, table_b, key_ids_a, key_ids_b, key_names, common_cols):
        index_a = self._index_by_key(table_a, key_ids_a, 'first')
        index_b = self._index_by_key(table_b, key_ids_b, 'second')

        # Don't report key columns as "changed" — equal keys are how rows matched in the first place.
        key_col_names = {table_a.column_names[i] for i in key_ids_a}
        compare_cols = [c for c in common_cols if c not in key_col_names]

        added, removed, changed = [], [], []
        unchanged = 0

        for key, row_a in index_a.items():
            if key not in index_b:
                removed.append(self._row_record(key, row_a, table_a.column_names))
                continue
            row_b = index_b[key]
            field_changes = self._diff_row_fields(
                row_a, table_a.column_names, row_b, table_b.column_names, compare_cols,
            )
            if field_changes:
                changed.append({
                    'key': [self._value_to_str(v) for v in key],
                    'changes': field_changes,
                })
            else:
                unchanged += 1

        for key, row_b in index_b.items():
            if key not in index_a:
                added.append(self._row_record(key, row_b, table_b.column_names))

        return {
            'mode': 'keyed',
            'key_columns': key_names,
            'added': added,
            'removed': removed,
            'changed': changed,
            'unchanged': unchanged,
        }

    def _diff_positional(self, table_a, table_b, common_cols):
        rows_a = list(table_a.rows)
        rows_b = list(table_b.rows)
        added, removed, changed = [], [], []
        unchanged = 0

        for i in range(max(len(rows_a), len(rows_b))):
            row_id = (str(i + 1),)
            if i >= len(rows_a):
                added.append(self._row_record(row_id, rows_b[i], table_b.column_names))
                continue
            if i >= len(rows_b):
                removed.append(self._row_record(row_id, rows_a[i], table_a.column_names))
                continue
            field_changes = self._diff_row_fields(
                rows_a[i], table_a.column_names,
                rows_b[i], table_b.column_names,
                common_cols,
            )
            if field_changes:
                changed.append({
                    'key': list(row_id),
                    'changes': field_changes,
                })
            else:
                unchanged += 1

        return {
            'mode': 'positional',
            'key_columns': ['row'],
            'added': added,
            'removed': removed,
            'changed': changed,
            'unchanged': unchanged,
        }

    def _row_record(self, key, row, column_names):
        return {
            'key': [self._value_to_str(v) for v in key],
            'row': {name: self._value_to_str(row[i]) for i, name in enumerate(column_names)},
        }

    def _diff_row_fields(self, row_a, cols_a, row_b, cols_b, compare_cols):
        idx_a = {name: i for i, name in enumerate(cols_a)}
        idx_b = {name: i for i, name in enumerate(cols_b)}
        changes = []
        for col in compare_cols:
            va = row_a[idx_a[col]]
            vb = row_b[idx_b[col]]
            if va != vb:
                changes.append({
                    'column': col,
                    'a': self._value_to_str(va),
                    'b': self._value_to_str(vb),
                })
        return changes

    def _value_to_str(self, value):
        if value is None:
            return ''
        return str(value)

    def _write_text(self, schema_diff, row_diff):
        out = self.output_file
        any_schema = (
            bool(schema_diff['added']) or bool(schema_diff['removed']) or schema_diff['reordered']
        )

        added = row_diff['added']
        removed = row_diff['removed']
        changed = row_diff['changed']

        out.write(
            f"Summary: {len(added)} added, {len(removed)} removed, "
            f"{len(changed)} changed, {row_diff['unchanged']} unchanged.\n"
        )

        if any_schema:
            out.write('\nSchema differences:\n')
            for col in schema_diff['added']:
                out.write(f'+ column: {col}\n')
            for col in schema_diff['removed']:
                out.write(f'- column: {col}\n')
            if schema_diff['reordered']:
                out.write('~ shared columns appear in a different order\n')

        if not (added or removed or changed):
            return

        out.write('\nRow differences:\n')

        for r in removed:
            out.write(self._format_text_row('-', r))
        for r in added:
            out.write(self._format_text_row('+', r))
        for r in changed:
            key_str = ' | '.join(r['key'])
            field_strs = ', '.join(
                f"{c['column']}: {c['a']} -> {c['b']}" for c in r['changes']
            )
            out.write(f'~ [{key_str}] {field_strs}\n')

    def _format_text_row(self, marker, record):
        key_str = ' | '.join(record['key'])
        values = ', '.join(f'{k}={v}' for k, v in record['row'].items())
        return f'{marker} [{key_str}] {values}\n'

    def _write_json(self, schema_diff, row_diff):
        payload = {
            'summary': {
                'added': len(row_diff['added']),
                'removed': len(row_diff['removed']),
                'changed': len(row_diff['changed']),
                'unchanged': row_diff['unchanged'],
            },
            'mode': row_diff['mode'],
            'key_columns': row_diff['key_columns'],
            'schema': schema_diff,
            'rows': {
                'added': row_diff['added'],
                'removed': row_diff['removed'],
                'changed': row_diff['changed'],
            },
        }
        json.dump(payload, self.output_file)
        self.output_file.write('\n')

    def _write_csv(self, schema_diff, row_diff):
        writer = agate.csv.writer(self.output_file, **self.writer_kwargs)
        writer.writerow(['status', 'key', 'column', 'a', 'b'])

        for col in schema_diff['added']:
            writer.writerow(['schema_added', '', col, '', ''])
        for col in schema_diff['removed']:
            writer.writerow(['schema_removed', '', col, '', ''])
        if schema_diff['reordered']:
            writer.writerow(['schema_reordered', '', '', '', ''])

        for r in row_diff['removed']:
            key_str = ' | '.join(r['key'])
            for col, val in r['row'].items():
                writer.writerow(['removed', key_str, col, val, ''])
        for r in row_diff['added']:
            key_str = ' | '.join(r['key'])
            for col, val in r['row'].items():
                writer.writerow(['added', key_str, col, '', val])
        for r in row_diff['changed']:
            key_str = ' | '.join(r['key'])
            for c in r['changes']:
                writer.writerow(['changed', key_str, c['column'], c['a'], c['b']])


def launch_new_instance():
    utility = CSVDiff()
    utility.run()


if __name__ == '__main__':
    launch_new_instance()
