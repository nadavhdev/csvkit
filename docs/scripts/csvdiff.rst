=======
csvdiff
=======

Description
===========

Semantically compares two CSV files and reports added, removed, and changed rows. Unlike a line-oriented :code:`diff`, csvdiff understands column layout and row identity: it can match rows across files by a key (so re-sorted or re-inserted rows still line up), report which individual columns changed within a matched row, and distinguish *schema* differences (added, removed, or reordered columns) from *row* differences.

.. code-block:: none

   usage: csvdiff [-h] [-d DELIMITER] [-t] [-q QUOTECHAR] [-u {0,1,2,3}] [-b]
                  [-p ESCAPECHAR] [-z FIELD_SIZE_LIMIT] [-e ENCODING] [-L LOCALE]
                  [-S] [--blanks] [--null-value NULL_VALUES [NULL_VALUES ...]]
                  [--date-format DATE_FORMAT] [--datetime-format DATETIME_FORMAT]
                  [-H] [-K SKIP_LINES] [-v] [-l] [--zero] [-V] [-k KEY]
                  [--format {text,json,csv}] [-y SNIFF_LIMIT] [-I]
                  [FILE [FILE ...]]

   Semantically diff two CSV files: report added, removed, and changed rows.

   positional arguments:
     FILE                  The two CSV files to compare. Use "-" to read one of
                           them from STDIN.

   optional arguments:
     -h, --help            show this help message and exit
     -k KEY, --key KEY     A comma-separated list of column names or indices that
                           uniquely identify a row. When omitted, rows are
                           compared positionally: row N of the first file against
                           row N of the second.
     --format {text,json,csv}
                           Output format for the diff. Defaults to "text", a
                           human-readable summary. "json" and "csv" emit
                           structured, machine-readable output.
     -y SNIFF_LIMIT, --snifflimit SNIFF_LIMIT
                           Limit CSV dialect sniffing to the specified number of
                           bytes. Specify "0" to disable sniffing entirely, or
                           "-1" to sniff the entire file.
     -I, --no-inference    Disable type inference (and --locale, --date-format,
                           --datetime-format, --no-leading-zeroes) when parsing
                           the input. With this flag, "1" and "1.0" compare as
                           different strings.

See also: :doc:`../common_arguments`.

Behavior
========

* **Row matching.** With :code:`--key`, rows are matched across files by the key column(s); the order of rows in either file does not matter. Without :code:`--key`, rows are compared positionally (row N of the first file against row N of the second).
* **Schema drift.** Added, removed, and reordered columns are reported in a dedicated "Schema differences" section, separate from row-level diffs. Row comparisons consider only the columns that are present in both files.
* **What counts as changed.** By default, values are compared *typed*: agate's inferred types mean numeric :code:`1` equals numeric :code:`1.0`, and a date string and its ISO normalization compare equal. Pass :code:`--no-inference` (:code:`-I`) to compare every cell as a raw string instead.
* **Duplicate keys** within either input file are treated as a usage error: csvdiff exits with code 2 and a clear message. De-duplicate first (for example with :code:`csvsort | uniq`) and try again.
* **Memory.** Both files are read fully into memory. Don't try this on very large files.

Exit codes
==========

* :code:`0` — the two files are equivalent (no schema drift, no row differences).
* :code:`1` — differences were found.
* :code:`2` — usage error (bad arguments, missing key column, duplicate keys, etc.). This is argparse's default error exit code.

Examples
========

Match rows by a key column and show a human-readable diff:

.. code-block:: bash

   csvdiff -k id examples/diff_a.csv examples/diff_b.csv

Compare with type inference disabled (every cell as a raw string):

.. code-block:: bash

   csvdiff -I -k id examples/diff_a.csv examples/diff_a_typed.csv

Use a composite key:

.. code-block:: bash

   csvdiff -k year,quarter examples/diff_composite_a.csv examples/diff_composite_b.csv

Emit structured output for downstream tooling:

.. code-block:: bash

   csvdiff --format json -k id examples/diff_a.csv examples/diff_b.csv
   csvdiff --format csv  -k id examples/diff_a.csv examples/diff_b.csv

Read one input from STDIN:

.. code-block:: bash

   cat examples/diff_b.csv | csvdiff -k id examples/diff_a.csv -
