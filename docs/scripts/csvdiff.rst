=======
csvdiff
=======

.. warning::

   **Experimental.** ``csvdiff`` was added in csvkit 2.3.0 with experimental status. Its flags,
   output format, and exit codes may change in 2.4.x based on user feedback. Please report issues
   and suggestions at the `csvkit issue tracker <https://github.com/wireservice/csvkit/issues>`_.

Description
===========

Compares two CSV files semantically — at the record and field level — rather than line by line.
Reports which rows were added, removed, or changed, with per-field details for changed rows.
Columns that differ between the two files are reported in a schema-drift section before the row
diff.

.. code-block:: none

   usage: csvdiff [-h] [-d DELIMITER] [-t] [-q QUOTECHAR] [-u {0,1,2,3,4,5}] [-b]
                  [-p ESCAPECHAR] [-z FIELD_SIZE_LIMIT] [-e ENCODING] [-L LOCALE]
                  [-S] [--blanks] [--null-value NULL_VALUES [NULL_VALUES ...]]
                  [--date-format DATE_FORMAT] [--datetime-format DATETIME_FORMAT]
                  [--no-leading-zeroes] [-H] [-K SKIP_LINES] [-v] [-l]
                  [--add-bom] [--zero] [-V] [-c KEY] [--on-dup {error,first,all}]
                  [--ignore IGNORE] [-f {human,jsonl,summary}] [--quiet]
                  [--no-schema-check] [-y SNIFF_LIMIT] [-I]
                  [FILE ...]

   Compare two CSV files semantically, reporting row-level differences.

   positional arguments:
     FILE                  The two CSV files to compare. Use "-" for stdin (at
                           most once).

   options:
     -c, --key KEY         Column name(s) or 1-based index(es) identifying each
                           row uniquely. Comma-separated for composite keys (e.g.
                           ``-c "order_id,line_no"``). When omitted, rows are
                           compared positionally (row N of LEFT vs row N of RIGHT).
     --on-dup {error,first,all}
                           Behavior when ``--key`` is not unique within a file.
                           ``error`` (default): exit 2 naming the duplicate key and
                           rows. ``first``: keep only the first occurrence of each
                           key. ``all``: compare the Cartesian product of all
                           matching duplicate rows (warning: O(n*m) per key; large
                           duplicate groups can produce enormous output).
     --ignore IGNORE       Comma-separated column names or indices to exclude from
                           row comparison.
     -f, --format {human,jsonl,summary}
                           Output format. ``human`` (default) is the human-readable
                           layout. ``jsonl`` emits one JSON object per event
                           (summary, optional schema, then one per row diff).
                           ``summary`` prints only the headline counts (and schema
                           banner if applicable).
     --quiet               Suppress all stdout output; exit code only. (``-q`` is
                           not available as a short form — it is the inherited
                           ``-q/--quotechar`` flag.)
     --no-schema-check     Skip the schema-drift section. Added, removed, or
                           reordered columns are no longer reported in a banner or
                           counted toward the exit code; rows are compared on the
                           shared columns as if the schemas were identical.
     -y, --snifflimit SNIFF_LIMIT
                           Limit CSV dialect sniffing to the specified number of
                           bytes. Specify "0" to disable sniffing entirely, or
                           "-1" to sniff the entire file.
     -I, --no-inference    Disable type inference when parsing the input. Compare
                           as raw strings.

Exit codes
==========

``csvdiff`` uses a three-value exit-code contract. This is new behaviour for csvkit — existing
tools use only exit 0 (success) and exit 2 (usage error). The mapping mirrors :manpage:`diff(1)`.

**Exit 0 — files are equivalent.** Both inputs contain the same rows (matched by key or position)
and no schema drift is detected (or ``--no-schema-check`` was passed). Scripts that want to assert
"no changes" should branch on ``$? -eq 0``.

**Exit 1 — differences found.** At least one row-level difference (added, removed, or changed row)
or schema-level difference (added, removed, or reordered column) was detected. Schema drift alone
is sufficient for exit 1; there need not be any row-level differences.

**Exit 2 — usage or parse error.** Returned for invalid arguments (unknown key column, duplicate
key with ``--on-dup=error``, stdin used for both inputs) or for CSV files that cannot be parsed
(malformed CSV, encoding error). Parse errors are explicitly routed to exit 2, not exit 1, so
that a CI script can distinguish "file could not be read" from "file was read and differs."

Design choices and limitations
===============================

**Typed comparison by default.** csvdiff uses agate's type inference when reading both inputs, so
values that are numerically equal — ``"1"`` and ``"1.0"``, or ``"true"`` and ``"True"`` — compare
as equal regardless of how they are spelled in the CSV. Use ``-I / --no-inference`` to compare raw
strings instead.

**In-memory operation.** Both files are read fully into memory before comparison. The tool is not
suitable for files that do not fit in available RAM. As a rough guide, a 500 k-row × 20-column CSV
occupies several hundred megabytes of Python object memory. For very large files, consider sorting
upstream and using a streaming merge approach.

**Schema renaming appears as remove and add.** csvdiff has no concept of column renaming. If a
column named ``qty`` in LEFT is renamed ``quantity`` in RIGHT, csvdiff reports ``removed: qty`` and
``added: quantity``. The data in those two columns is not compared.

**Single encoding for both files.** The inherited ``-e / --encoding`` option applies to *both*
input files. If LEFT is UTF-8 and RIGHT is Latin-1, pre-process one of them with
:doc:`csvformat` first. Per-file encoding flags are a possible future extension.

**Schema diff is suppressed under** ``-H / --no-header-row``. When both files are treated as
header-less, column names are synthetic (``a``, ``b``, ``c``, …). Comparing those synthetic names
is meaningless, so the ``! schema changed:`` banner is always suppressed and schema drift does not
contribute to the exit code when ``-H`` is active.

See also: :doc:`../common_arguments`.

Examples
========

Compare two files by a key column:

.. code-block:: bash

   csvdiff -c id examples/diff_a.csv examples/diff_b.csv

Compare using a composite key (two columns together identify a row uniquely):

.. code-block:: bash

   csvdiff -c "order_id,line_no" examples/diff_composite_a.csv examples/diff_composite_b.csv

Compare row by row without a key (positional mode — note that re-sorted files will produce
wide spurious diffs; use ``-c`` whenever a stable row identifier is available):

.. code-block:: bash

   csvdiff examples/diff_pos_a.csv examples/diff_pos_b.csv

Use in a CI pipeline — exit code only, no output:

.. code-block:: bash

   csvdiff -c id before.csv after.csv --quiet
   echo $?

Emit machine-readable JSONL for downstream processing:

.. code-block:: bash

   csvdiff -c id before.csv after.csv --format jsonl

Show only headline counts (useful for logs):

.. code-block:: bash

   csvdiff -c id before.csv after.csv --format summary

Ignore a timestamp column when comparing:

.. code-block:: bash

   csvdiff -c id --ignore updated_at before.csv after.csv

Detect a schema change (added or removed columns) — new columns appear in the schema banner,
not as per-row differences, because row comparison narrows to the common column intersection:

.. code-block:: bash

   csvdiff -c id examples/diff_schema_base.csv examples/diff_schema_added.csv

Read one file from stdin:

.. code-block:: bash

   cat new.csv | csvdiff -c id old.csv -
