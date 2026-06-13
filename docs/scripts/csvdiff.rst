=======
csvdiff
=======

.. warning::

   **Experimental** — ``csvdiff`` is new in 2.3.0. Its flags, output format, and exit-code
   contract may change in 2.4.x based on user feedback. If you build scripts or CI jobs on top
   of ``csvdiff``, please pin your csvkit version and watch the `issue tracker
   <https://github.com/wireservice/csvkit/issues>`_ for breaking-change notices.

Description
===========

Compares two CSV files semantically — at the record and field level, not line by line.
Unlike a plain ``diff``, ``csvdiff`` understands CSV structure: it can match rows by a key
column, report which *fields* changed inside a row, detect schema drift (columns
added, removed, or reordered), and emit a structured summary suitable for CI pipelines.

.. code-block:: none

   usage: csvdiff [-h] [-d DELIMITER] [-t] [-q QUOTECHAR] [-u {0,1,2,3}] [-b]
                  [-p ESCAPECHAR] [-z FIELD_SIZE_LIMIT] [-e ENCODING] [-L LOCALE]
                  [-S] [--blanks] [--null-value NULL_VALUES [NULL_VALUES ...]]
                  [--date-format DATE_FORMAT] [--datetime-format DATETIME_FORMAT]
                  [-H] [-K SKIP_LINES] [-v] [-l] [--zero] [-V]
                  [-c KEY] [--on-dup {error,first,all}]
                  [-f {human,jsonl,summary}] [--no-schema-check]
                  [--ignore COLS] [--quiet]
                  [-y SNIFF_LIMIT] [-I]
                  [FILE [FILE ...]]

   Compare two CSV files semantically, reporting row-level differences.

   positional arguments:
     FILE                  The two CSV files to compare. Use "-" for stdin
                           (at most once). If exactly one path is given and
                           stdin is not a tty, stdin is treated as the LEFT file.

   csvdiff options:
     -c KEY, --key KEY     Column name(s) or 1-based index(es) identifying each
                           row uniquely. Comma-separated for a composite key
                           (e.g. -c "order_id,line_no"). When omitted, rows are
                           compared positionally (row N vs row N).
     --on-dup {error,first,all}
                           Behavior when --key is not unique within a file.
                           "error" (default): exit 2, naming the duplicate key.
                           "first": keep only the first occurrence of each key.
                           "all": compare the Cartesian product of all matching
                           duplicate rows (warning: O(n*m) per key).
     -f {human,jsonl,summary}, --format {human,jsonl,summary}
                           Output format. "human" (default) is the human-readable
                           layout. "jsonl" emits one JSON object per event.
                           "summary" prints only the headline counts.
     --no-schema-check     Skip schema-drift detection. Added, removed, or
                           reordered columns are not reported and do not
                           contribute to the exit code; rows are compared on
                           the shared columns as if the schemas were identical.
     --ignore COLS         Comma-separated column names or 1-based indexes to
                           exclude from row comparison. Excluded columns still
                           appear in the schema-drift section.
     --quiet               Suppress all stdout output; exit code only. Error
                           messages on stderr are unaffected. Note: use
                           ``--quiet``, not ``-q`` — the ``-q`` short form is
                           the inherited ``-q/--quotechar`` flag.
     -y SNIFF_LIMIT, --snifflimit SNIFF_LIMIT
                           Limit CSV dialect sniffing to the specified number of
                           bytes. Specify "0" to disable sniffing entirely, or
                           "-1" to sniff the entire file.
     -I, --no-inference    Disable type inference when parsing the input.
                           Compare field values as raw strings.

See also: :doc:`../common_arguments`.

Exit codes
==========

``csvdiff`` introduces a three-value exit-code contract that is new for csvkit. Scripts
that previously assumed "csvkit tools only exit 0 or 2" will need updating.

**Exit 0 — files are equivalent.**
Both the row diff and the schema diff (unless ``--no-schema-check`` is set) are empty.
The headline still shows all-zero counts (e.g. ``0 changed, 0 added, 0 removed (of 3 rows compared)``).
Use ``--quiet`` to suppress all output entirely.

**Exit 1 — differences found.**
At least one row was added, removed, or changed, *or* at least one schema difference
was detected (and ``--no-schema-check`` was not set). This mirrors the ``diff(1)``
convention (0 = same, 1 = different) and is the signal for CI jobs to fail a
"no unexpected changes" gate. The exit code is set after rendering, so the diff
output is always emitted before the process exits.

**Exit 2 — usage or parse error.**
The arguments are invalid (missing or unknown key column, stdin used twice, more than
two input files), a duplicate key was found with ``--on-dup=error``, or a CSV file
could not be parsed (malformed CSV, encoding error). The error message is written to
stderr. Note: a parse error always exits 2 — it never exits 1 — even though 1 is
also a "non-zero" exit. This distinction matters for CI pipelines that branch on the
exit code.

Notes
=====

**Typed comparison by default.** ``csvdiff`` passes both files through agate's type
inference before comparing. This means ``"1"`` and ``"1.0"`` compare as equal (both
become the number ``1``), and ``"true"`` and ``"True"`` compare as equal (both become
a Boolean). Use ``-I``/``--no-inference`` to compare field values as raw strings.

**In-memory operation.** Both files are read fully into memory before any comparison
takes place. The memory footprint is roughly ``2 × max(size_of_LEFT, size_of_RIGHT)``
in agate's typed row representation, plus two key-index dictionaries. Do not run
``csvdiff`` on files that exceed your available RAM; sort and chunk upstream instead.

**Schema drift: rename is reported as remove + add.** When a column is renamed between
LEFT and RIGHT (e.g. ``qty`` → ``quantity``), ``csvdiff`` has no way to detect the
semantic link and reports it as ``removed: qty`` plus ``added: quantity``. This is the
literal truth of what changed in the CSV header row. Rows in RIGHT that formerly held
``qty`` will appear as added (the new ``quantity`` column exists only on the RIGHT
side). To avoid this, rename columns consistently before diffing.

**Single encoding for both files.** The inherited ``-e``/``--encoding`` flag applies to
*both* LEFT and RIGHT with the same encoding. There is no per-file encoding override in
this version. If your two files use different encodings, convert one of them with
``csvformat -e <target-encoding>`` before running ``csvdiff``.

**Schema drift is suppressed under** ``-H``/``--no-header-row``. When headers are absent,
csvkit assigns synthetic column names (``a``, ``b``, ``c``, …) to both files. Reporting
schema drift on synthetic names would produce misleading output (e.g. "removed: a, b"),
so the schema-drift section is silently suppressed and schema differences do not
contribute to the exit code. Row diffs still run normally.

**No-key positional mode footgun.** Without ``-c``/``--key``, ``csvdiff`` compares row N
of LEFT to row N of RIGHT. If the two files contain the same records but in a different
order, positional mode will report all rows as changed or as removed/added. Always use
``-c`` when comparing files that may have been sorted differently.

Examples
========

Compare two CSV files by a key column:

.. code-block:: bash

   csvdiff -c id examples/diff_a.csv examples/diff_b.csv

Compare with a composite key:

.. code-block:: bash

   csvdiff -c "order_id,line_no" orders_jan.csv orders_feb.csv

Compare row-by-row positionally (no key — use only when row order is stable):

.. code-block:: bash

   csvdiff examples/diff_a.csv examples/diff_b.csv

Read the left file from stdin:

.. code-block:: bash

   csvdiff - examples/diff_b.csv < examples/diff_a.csv

Show schema drift when columns are added or removed:

.. code-block:: bash

   csvdiff -c id examples/diff_schema_base.csv examples/diff_schema_added.csv

Show only the headline counts (useful for CI log lines):

.. code-block:: bash

   csvdiff -c id --format summary examples/diff_a.csv examples/diff_b.csv

Emit machine-readable JSONL output (one JSON object per event):

.. code-block:: bash

   csvdiff -c id --format jsonl examples/diff_a.csv examples/diff_b.csv

Suppress schema-drift reporting and ignore a timestamp column:

.. code-block:: bash

   csvdiff -c id --no-schema-check --ignore updated_at old.csv new.csv

Use in a CI script that fails on any difference:

.. code-block:: bash

   if ! csvdiff -c id --quiet expected.csv actual.csv; then
     echo "Output changed — review the diff:" >&2
     csvdiff -c id expected.csv actual.csv >&2
     exit 1
   fi
