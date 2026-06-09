---
name: csvkit-feature-review
description: |
  Audit a csvkit tool (or significant extension) against the project's design guidelines
  in csvkit_design_guidelines.md and emit a slick self-contained HTML quality report.
  Use this when a new utility is added under csvkit/utilities/ or a substantial change
  ships, and you want a structured, opinionated review across 10 weighted dimensions
  plus cross-cutting bars. Produces a numeric score (0–10) and letter grade (A–F).
  Accepts an optional argument: the tool/command name to review (e.g. "csvdiff");
  if omitted, defaults to "csvdiff".
---

# csvkit-feature-review

You are reviewing a csvkit feature against the project's design rubric and producing
a polished HTML report.

**Be a tough critic.** This review exists to surface real problems, not to validate
work. Default to lower scores. A tool that mechanically copies the nearest template
correctly is **Good (7.0)**, not Excellent. Numbers ≥ 8.5 must be earned with
specific, demonstrable craft. A single ✗ Bad finding should drop the dimension's
score by at least 1.5 points unless it is genuinely trivial.

Cite line numbers. Compare against the canonical template files for every claim.
Refuse to give a high score because "it follows the template" — say specifically
*how* it does so, and call out anything where it deviates without a defensible
reason.

## Inputs

- **Target.** First non-empty argument from the invocation is the tool name (e.g.
  `csvdiff`). If no argument is given, default to `csvdiff`. Strip any leading
  `csv` from the user-provided name only if necessary to find the module — but
  the canonical name (e.g. `csvdiff`) is what the report should display.
- **Guidelines.** Read `csvkit_design_guidelines.md` at the repo root. This is the
  source of truth for the 10 dimensions (D1–D10) and cross-cutting bars (A–I). If
  the file is missing, abort and tell the user to generate it first.
- **Output path.** Default to `<target>_quality_report.html` at the repo root.
  The user may override by saying "write to PATH".

---

## Scoring scheme

### Per-dimension score (0.0–10.0)

Each of D1–D10 receives a numeric score on a 0–10 scale (one decimal allowed),
one **findings table** with 4 columns, and a weighted contribution to the total.

| Score range | Bucket | What it means |
|-------------|--------|---------------|
| 9.0–10.0 | **Exceptional** | Sets a new bar. Meets every "How to check" bullet *and* shows craft beyond the suite's average — better error messages, cleaner factoring than the template, an insight worth propagating. Requires at least one row graded Exceptional and zero Bad rows. |
| 8.0–8.9 | **Excellent** | Meets every guideline bullet cleanly with no gaps. Shows above-average care in at least one place. Requires ≥1 Excellent or Exceptional row and zero Bad rows. |
| 7.0–7.9 | **Good** | Mechanically correct — follows the templates and guideline bullets, nothing more. Any Bad rows must be minor and explained. |
| 6.0–6.9 | **OK** | Present but unremarkable. Meets the letter of the guideline, not the spirit. Or: one identifiable gap that doesn't quite reach FAIL. Usually 1–2 Bad rows that are recoverable. |
| 0.0–5.9 | **Bad** | At least one "FAIL signal" from the guideline is present, or the dimension has multiple structural gaps. Multiple Bad rows, possibly fundamental violations. |

### Findings table — 4 columns, one row per aspect

Each dimension renders as **one** table. Rows are aspects of that dimension;
columns are:

| Column | Header | Content |
|--------|--------|---------|
| 1 | **Aspect** | Short topic label, 1–4 words. E.g. "Schema-vs-row split", "Duplicate-key validation", "Help text quality", "Fixture naming". |
| 2 | **Details** | A short `<ul>` of bulleted facts. Each `<li>` is one observation with a `file:line` citation. Bullets must be tight — single clause or short sentence. No prose paragraphs. |
| 3 | **Grade** | A colored pill for this row's rating: **Exceptional / Excellent / Good / OK / Bad**. |
| 4 | **Suggestions** | A short `<ul>` of actionable lift items. Each `<li>` names a concrete change (file, line, what to add/change). For Bad rows, include the score-lift estimate (e.g. "Lifts D5 6.5 → ~8.0"). |

**One row = one aspect.** Don't try to put five separate findings into one row.
If you find yourself writing "additionally…" or "also…" inside a Details bullet,
that's a sign you should split it into a new row.

**Row ordering.** Within each dimension's table, order rows by aspect in a
logical/source-code order (the order a reader would encounter them when reading
the utility module top-to-bottom). If two rows share the same aspect topic,
sub-sort by grade severity (Bad first within that group).

**Grade is a property of the row, not the dimension.** The dimension's overall
score is the weighted reading of all rows. A dimension that scores 9.0 will have
mostly Exceptional and Excellent rows; a dimension that scores 5.5 will have
Bad rows visible at the top of its table.

### When column 4 (Suggestions) may be empty

| Grade | Suggestions column required? |
|-------|------------------------------|
| **Exceptional** | Optional — write `Propagate to siblings` if the pattern should spread, otherwise a single `<li>` saying `—`. |
| **Excellent**   | **Required** — must name the specific gap to Exceptional. What would have to change for this to be a 10/10? |
| **Good**        | **Required** — what would lift this toward Excellent. May be a concrete polish OR an honest "Standard pattern; no realistic lift." Never empty. |
| **OK**          | **Required** — concrete change that would lift toward Good. Never empty. |
| **Bad**         | **Required** — the fix, imperative, names the file. Include the score lift estimate. Never empty. |

**Why every non-Exceptional row must fill Suggestions.** Excellent, Good, OK,
and Bad are all explicitly "not at the top." The Suggestions column is where
you make the gap visible. If you genuinely cannot identify any realistic lift
for a Good aspect, write `Standard pattern; no realistic lift.` — that's data
too. Vague suggestions are noise; specific suggestions are reviewable.

**Tone.** Concise. Each bullet is one short sentence. Name the file/line/method
where the change would happen.

### Dimension weights

| Dim | Name                         | Weight |
|-----|------------------------------|--------|
| D1  | Modeling                     | 15%    |
| D2  | Package structuring          | 3%     |
| D3  | Component separation         | 8%     |
| D4  | Reuse                        | 15%    |
| D5  | Testing coverage             | 20%    |
| D6  | Observability                | 15%    |
| D7  | CLI & flag discipline        | 6%     |
| D8  | Error model & exit codes     | 6%     |
| D9  | Data semantics               | 7%     |
| D10 | Documentation & registration | 5%     |

Weights sum to 100. Do not invent your own weights — these are the configured
defaults for this project.

### Total score

```
total = sum(dimension_score * weight) / 100
```

The total is on a 0–10 scale (one decimal). Letter grade:

| Total | Letter | Meaning |
|-------|--------|---------|
| ≥ 9.0 | **A** | Exceptional — would set a benchmark for the suite |
| ≥ 8.0 | **B** | Excellent — ships, with confidence |
| ≥ 7.0 | **C** | Good — ships, with the listed follow-ups |
| ≥ 6.0 | **D** | Marginal — fix the Bad rows before merge |
| < 6.0 | **F** | Failing — back to design |

### Canonical color scheme (one color per rating, identical everywhere)

| Rating | Color | Hex | Used for |
|--------|-------|-----|----------|
| **Exceptional** | emerald | `#10b981` | grade pill, row left-accent + row tint, bar-fg, dimension border, grade-A chip |
| **Excellent**   | green   | `#22c55e` | same surfaces, grade-B chip |
| **Good**        | yellow  | `#eab308` | same surfaces, grade-C chip |
| **OK**          | orange  | `#f97316` | same surfaces, grade-D chip |
| **Bad**         | red     | `#ef4444` | same surfaces, grade-F chip |

The dimension's overall score color paints only the `<details>` border accent
and the dimension's summary pill. Each row's grade color paints the row's
left accent, the row's subtle background tint, and the row's grade pill —
independently. Do not let the dimension's color bleed onto inner rows.

### Cross-cutting bars are hard gates

Any failed bar A–I caps the letter grade at **F**, regardless of the weighted
score. The numeric total still appears in the report, but the letter is F and
the report leads with the failed bar(s).

---

## Procedure

Execute these steps in order. Do not skip steps. Do not rewrite the
implementation.

### 1. Locate the feature surface

Find every file that belongs to the target feature. Typically:

- `csvkit/utilities/<target>.py` — the utility module
- `tests/test_utilities/test_<target>.py` — the test module
- `docs/scripts/<target>.rst` — the user-facing docs
- `man/<target>.1` — the man page (optional)
- New fixtures in `examples/` (use `git status` / `git log` to find newly added ones)
- `pyproject.toml` — `[project.scripts]` and `[tool.setuptools.data-files]` entries
- `CHANGELOG.rst` — top entry
- `AUTHORS.rst` — recent additions
- `docs/cli.rst` — the index that should link the new tool
- `.github/workflows/ci.yml` — stdin/pipe smoke-test blocks

Use `git log --diff-filter=A --name-only` against the merge base with `master` if
you need to discover newly-added files.

Record the file list — it appears in the report's appendix.

### 2. Read the canonical templates for comparison

Before scoring, re-read the relevant template files so your citations are accurate:

- Always: `csvkit/cli.py` (the base class), `csvkit/exceptions.py`, `tests/utils.py`.
- For a two-file tool: `csvkit/utilities/csvjoin.py`, `tests/test_utilities/test_csvjoin.py`.
- For a single-file tool: `csvkit/utilities/csvsort.py` (transform) or
  `csvkit/utilities/csvgrep.py` (streaming) and their tests.
- For exit-code-on-data-condition precedent: `csvkit/utilities/csvclean.py`.

Read enough to ground your specific line citations. Do not skim.

### 3. Score each of D1–D10

For each dimension defined in `csvkit_design_guidelines.md` §3, produce:

1. **A numeric score** in `[0.0, 10.0]`, one decimal allowed.
2. **A bucket label** derived from the score (Exceptional / Excellent / Good /
   OK / Bad).
3. **A rationale** of 1–3 sentences that names the specific code paths
   supporting the score. Cite `file:line`.
4. **A findings table** with 4 columns (Aspect, Details, Grade, Suggestions).
   One row per aspect; rows ordered by source-code/logical order with any
   intra-aspect ties broken by grade severity (Bad first).

#### Aspect identification

Look for the natural topics within each dimension. For D3 Component separation,
typical aspects include: "File handling in read loop", "Four-phase ordering",
"Base lifecycle methods", "Helper factoring", "Data-driven validation",
"Duplicate-key validation phase". For D5 Testing coverage: "Mixin setup",
"Output format coverage", "Stdin testing", "Schema-drift coverage", etc.

Aim for 4–8 rows per dimension. Fewer than 4 means you haven't broken the
dimension down enough; more than 8 means you're splitting hairs.

#### Calibration anchors (per-row grade)

Apply these to each row, not just to the dimension as a whole:

- **Exceptional row.** This aspect demonstrably exceeds what the template does.
  Examples: a try/finally where csvjoin doesn't have one; an error message that
  names both column and file when csvjoin names only column.
- **Excellent row.** The aspect is cleanly done with above-average care, but
  there's a specific identifiable gap to Exceptional. Suggestions column names
  that gap.
- **Good row.** The aspect is mechanically correct — matches the template, no
  surprises. Suggestions column either names a small polish or honestly says
  "Standard pattern; no realistic lift."
- **OK row.** The aspect is present but bare or has one small gap. Suggestions
  column names what would lift it to Good.
- **Bad row.** A guideline FAIL signal fires here. Suggestions column names the
  fix and the score lift estimate.

#### "FAIL signals" that force a Bad row

When any of these appears in your reading, write a Bad row for it:

- **D1**: New domain vocabulary in help text without explanation; flags named
  after internal data structures.
- **D2**: Module name doesn't match the command; reusable helpers buried inside
  the utility module.
- **D3**: `__init__` or `run()` overridden; I/O before validation; `main()`
  exceeding ~120 lines without helpers.
- **D4**: `match_column_identifier` / `parse_column_identifiers` reimplemented;
  files opened with the raw `open()` builtin; common args redefined.
- **D5**: Missing `EmptyFileTests`; missing `test_launch_new_instance`;
  hand-rolled stdout capture; coverage < 80%; `default_args` makes the empty
  mixin a vacuous pass.
- **D6**: Status messages on stdout; tracebacks printed without `-v`; custom
  `sys.excepthook`; vague error messages.
- **D7**: Redefines an inherited flag; collides with a sibling tool's flag for
  a different concept; copy-pasted help strings; underscores in long-form
  flags.
- **D8**: Bare `sys.exit(2)` or `sys.exit(1)` for usage errors; new exit code
  introduced without epilog/docs disclosure; `ColumnIdentifierError` leaking
  as a traceback.
- **D9**: Builds its own `TypeTester`; ignores `--blanks` / `--null-value` /
  `--date-format`; treats typed equality differently from the rest of the
  suite without explanation.
- **D10**: `[project.scripts]` line missing; rst docs missing; CHANGELOG entry
  missing; CI stdin/pipe smoke tests not updated.

### 4. Evaluate cross-cutting bars A–I

For each bar A–I in §4 of the guidelines, score `PASS` or `FAIL` with one
sentence and a citation. **Any FAIL caps the overall letter at F.**

### 5. Compute the total and the letter grade

1. For each dimension, compute `weighted = score * weight`.
2. `total = sum(weighted) / 100`, one decimal.
3. Derive the letter grade from the total.
4. **If any bar A–I is FAIL, override the letter grade to F.**

Show your math in the report (the score-breakdown table).

### 6. Produce top recommendations

After all scoring, list the **top 3–7 actionable recommendations**, ordered by
severity (largest score impact first, then bars, then nice-to-haves). Each
recommendation is a single sentence: imperative mood, names the file and the
fix. Pull these from the Suggestions column of the Bad rows first, then the OK
rows, then the highest-lift Good rows.

If a recommendation can lift a dimension out of OK/Bad into Good or higher,
note that explicitly (e.g. "Fixing this would lift D5 from 6.5 → ~8.0.").

### 7. Emit the HTML report

Write a single self-contained HTML file to the output path. Use the embedded
template below. Replace each `{{slot}}` placeholder. Do not include external
CSS, JS, fonts, or images.

When filling in slots:

- HTML-escape any content that comes from code. Use
  `python3 -c 'import html, sys; print(html.escape(sys.stdin.read()))'` via
  Bash when assembling content into a temp file.
- The dimension summary pill uses `pill-exceptional`, `pill-excellent`,
  `pill-good`, `pill-ok`, `pill-bad` (mapped from the dimension's overall score).
- Each row in the findings table uses `<tr class="row-{rating}">` for the row
  accent and `<span class="pill pill-{rating}">` in the Grade column.
- Cross-cutting bars use `pill-pass` / `pill-fail`.
- The letter-grade chip uses `grade-a`, `grade-b`, `grade-c`, `grade-d`,
  `grade-f`.
- Citations are inline `<code>` tags. Example: `<code>csvjoin.py:46</code>`.
- Each row's Details and Suggestions cells should contain a `<ul>` with
  short `<li>` bullets. Even a single observation goes in a one-item `<ul>`.
- The dimension `<details>` elements should be **open by default** for any
  dimension scoring < 7.5, **closed** for ≥ 7.5.
- If any bar A–I failed, render the `.failed-bar-banner` at the top of `<main>`.
  Otherwise omit it.

### 8. Final response

After writing the file, respond to the user with:

1. The path to the report.
2. One-line headline: `Total: X.X / 10 — Grade <LETTER>` and the single
   weakest dimension. If any bar failed, prepend the bar(s) and note that
   the letter is gated to F.
3. A tight bullet list of the Bad rows, grouped by dimension.
4. Offer to open it (suggest the user run `open <path>`).

Do not paste the HTML into chat. The report is the deliverable.

---

## HTML template

Slots are written as `{{slot_name}}`. Some slots are multi-element; for those,
the template shows a single instance you should repeat as needed.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{title}}</title>
<style>
:root {
  --bg:#0b1020; --panel:#131a30; --border:#2a3358; --fg:#e5e7eb; --muted:#9ca3af;
  --green:#22c55e; --emerald:#10b981; --red:#ef4444; --orange:#f97316;
  --yellow:#eab308; --blue:#60a5fa; --purple:#a78bfa; --pink:#f472b6;
  --mono: 'SF Mono','JetBrains Mono','Menlo','Consolas',monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--fg);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
header {
  padding: 32px 40px 24px; border-bottom: 1px solid var(--border);
  display: flex; gap: 24px; align-items: baseline; justify-content: space-between; flex-wrap: wrap;
}
header h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }
header .meta { color: var(--muted); font-family: var(--mono); font-size: 12px; }
header .meta div { margin-top: 2px; }
main { max-width: 1240px; margin: 0 auto; padding: 28px 40px 80px; }

.headline { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; }
.score-big { font-family: var(--mono); font-size: 44px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
.score-big .max { color: var(--muted); font-size: 22px; font-weight: 500; }
.grade-chip {
  font-family: var(--mono); font-size: 28px; font-weight: 800;
  letter-spacing: 0.02em; padding: 6px 18px; border-radius: 10px;
}
.grade-chip.grade-a { background: rgba(16,185,129,0.18); color: var(--emerald); }
.grade-chip.grade-b { background: rgba(34,197,94,0.18); color: var(--green); }
.grade-chip.grade-c { background: rgba(234,179,8,0.18); color: var(--yellow); }
.grade-chip.grade-d { background: rgba(249,115,22,0.18); color: var(--orange); }
.grade-chip.grade-f { background: rgba(239,68,68,0.22); color: var(--red); }

.failed-bar-banner {
  background: rgba(239,68,68,0.10); border: 1px solid rgba(239,68,68,0.45);
  border-left: 3px solid var(--red); border-radius: 8px;
  padding: 14px 18px; margin: 20px 0 24px; color: #fecaca; font-size: 13.5px;
}
.failed-bar-banner b { color: #fee2e2; }

.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 20px 0 28px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
.card h3 { margin: 0 0 6px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.card .num { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
.card .sub { font-size: 11.5px; color: var(--muted); font-family: var(--mono); margin-top: 6px; }
.card.score-card .num { color: var(--emerald); }
.card.bars-card .num { color: var(--red); }
.card.bars-card.ok .num { color: var(--green); }
.card.bad-card .num { color: var(--red); }
.card.weak-card .num { font-size: 14px; color: var(--fg); font-family: var(--mono); }

.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 22px; }
.panel > h2 {
  margin: 0; padding: 14px 20px; font-size: 11.5px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  border-bottom: 1px solid var(--border);
}
.panel > .body { padding: 16px 20px; }

table.breakdown { width: 100%; border-collapse: collapse; font-size: 13px; }
table.breakdown th, table.breakdown td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); }
table.breakdown tr:last-child td { border-bottom: none; }
table.breakdown th { color: var(--muted); font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; }
table.breakdown td.num, table.breakdown th.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }
.bar-bg {
  display: inline-block; vertical-align: middle; width: 90px; height: 8px;
  background: rgba(96,165,250,0.10); border-radius: 4px; overflow: hidden;
  margin-right: 8px;
}
.bar-fg { display: block; height: 100%; border-radius: 4px; }
.bar-fg.bucket-exceptional { background: var(--emerald); }
.bar-fg.bucket-excellent   { background: var(--green); }
.bar-fg.bucket-good        { background: var(--yellow); }
.bar-fg.bucket-ok          { background: var(--orange); }
.bar-fg.bucket-bad         { background: var(--red); }

.pill {
  display: inline-block; padding: 2px 9px; border-radius: 99px;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; font-family: var(--mono);
  white-space: nowrap;
}
.pill-exceptional { background: rgba(16,185,129,0.20); color: var(--emerald); }
.pill-excellent   { background: rgba(34,197,94,0.18); color: var(--green); }
.pill-good        { background: rgba(234,179,8,0.20); color: var(--yellow); }
.pill-ok          { background: rgba(249,115,22,0.20); color: var(--orange); }
.pill-bad         { background: rgba(239,68,68,0.22); color: var(--red); }
.pill-pass        { background: rgba(34,197,94,0.18); color: var(--green); }
.pill-fail        { background: rgba(239,68,68,0.22); color: var(--red); }
.pill-weight      { background: rgba(167,139,250,0.18); color: var(--purple); }

details.dim { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin: 10px 0; overflow: hidden; }
details.dim > summary {
  cursor: pointer; padding: 14px 20px; display: flex; gap: 14px; align-items: center;
  list-style: none;
}
details.dim > summary::-webkit-details-marker { display: none; }
details.dim > summary::before { content: '▸'; color: var(--muted); transition: transform 0.15s; font-size: 11px; }
details.dim[open] > summary::before { transform: rotate(90deg); }
details.dim.bucket-exceptional { border-color: rgba(16,185,129,0.45); }
details.dim.bucket-excellent   { border-color: rgba(34,197,94,0.40); }
details.dim.bucket-good        { border-color: rgba(234,179,8,0.40); }
details.dim.bucket-ok          { border-color: rgba(249,115,22,0.40); }
details.dim.bucket-bad         { border-color: rgba(239,68,68,0.45); }
details.dim .id   { font-family: var(--mono); font-size: 13px; color: var(--blue); width: 36px; }
details.dim .name { flex: 1; font-weight: 600; }
details.dim .score-num {
  font-family: var(--mono); font-size: 13px; color: var(--fg);
  font-variant-numeric: tabular-nums; min-width: 48px; text-align: right;
}
.dim-body { padding: 4px 22px 18px 22px; font-size: 13.5px; line-height: 1.6; }
.dim-body h4 {
  margin: 14px 0 6px; font-size: 10.5px; font-weight: 600; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.dim-body h4:first-child { margin-top: 6px; }
.dim-body p { margin: 0; color: #d1d5db; }
.dim-body .math {
  font-family: var(--mono); font-size: 12px; color: var(--muted);
  margin: 8px 0 14px; padding: 6px 10px; border-left: 2px solid var(--border);
}

/* Findings table — 4 columns: Aspect | Details | Grade | Suggestions */
table.findings {
  width: 100%; border-collapse: separate; border-spacing: 0;
  margin-top: 6px; font-size: 12.8px; table-layout: fixed;
  border: 1px solid rgba(255,255,255,0.14);
  border-radius: 6px; overflow: hidden;
  background: rgba(7,11,28,0.35);
}
table.findings th, table.findings td {
  text-align: left; vertical-align: top; padding: 10px 12px;
  border-right: 1px solid rgba(255,255,255,0.10);
  border-bottom: 1px solid rgba(255,255,255,0.10);
}
table.findings th:last-child, table.findings td:last-child { border-right: none; }
table.findings tr:last-child td { border-bottom: none; }
table.findings th {
  background: rgba(255,255,255,0.04);
  color: var(--muted); font-weight: 600; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.08em;
  border-bottom: 1px solid rgba(255,255,255,0.18);
}
table.findings td { color: #d1d5db; line-height: 1.5; }
table.findings col.col-aspect      { width: 17%; }
table.findings col.col-details     { width: 38%; }
table.findings col.col-grade       { width: 11%; }
table.findings col.col-suggestions { width: 34%; }
table.findings td.col-aspect {
  font-weight: 600; color: var(--fg); font-size: 13px;
}
table.findings td.col-grade { text-align: center; vertical-align: middle; }
table.findings ul { margin: 0; padding-left: 16px; }
table.findings li { margin: 4px 0; color: #d1d5db; }
table.findings li:first-child { margin-top: 0; }

/* Per-row grade accent — left border + faint background tint */
table.findings tr.row-exceptional td:first-child { box-shadow: inset 3px 0 0 var(--emerald); }
table.findings tr.row-excellent   td:first-child { box-shadow: inset 3px 0 0 var(--green); }
table.findings tr.row-good        td:first-child { box-shadow: inset 3px 0 0 var(--yellow); }
table.findings tr.row-ok          td:first-child { box-shadow: inset 3px 0 0 var(--orange); }
table.findings tr.row-bad         td:first-child { box-shadow: inset 3px 0 0 var(--red); }
table.findings tr.row-exceptional td { background: rgba(16,185,129,0.05); }
table.findings tr.row-excellent   td { background: rgba(34,197,94,0.04); }
table.findings tr.row-good        td { background: rgba(234,179,8,0.04); }
table.findings tr.row-ok          td { background: rgba(249,115,22,0.05); }
table.findings tr.row-bad         td { background: rgba(239,68,68,0.06); }

code {
  font-family: var(--mono); font-size: 11.5px;
  background: rgba(96,165,250,0.10); color: var(--blue);
  padding: 1px 5px; border-radius: 4px;
}
.bar-list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.bar-list .bar { display: flex; gap: 12px; align-items: baseline; padding: 8px 0; border-bottom: 1px solid var(--border); }
.bar-list .bar:last-child, .bar-list .bar:nth-last-child(2) { border-bottom: none; }
.bar-list .bar .id { font-family: var(--mono); color: var(--purple); width: 24px; }
.bar-list .bar .name { flex: 1; color: #d1d5db; font-size: 13px; }
.recs { background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--blue); border-radius: 8px; padding: 16px 22px; }
.recs ol { margin: 4px 0 0 0; padding-left: 22px; }
.recs li { margin: 6px 0; color: #d1d5db; }
.section-title { margin: 36px 0 12px; font-size: 11.5px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
.appendix { margin-top: 30px; }
.appendix pre {
  background: #06091a; border: 1px solid var(--border); border-radius: 6px;
  padding: 12px 14px; margin: 0; overflow: auto;
  font-family: var(--mono); font-size: 12px; line-height: 1.55; color: #cbd5e1;
}
</style>
</head>
<body>
<header>
  <div>
    <h1>{{title}}</h1>
    <div class="headline">
      <div class="score-big">{{total_score}}<span class="max"> / 10</span></div>
      <div class="grade-chip {{grade_class}}">{{grade_letter}}</div>
    </div>
  </div>
  <div class="meta">
    <div>Run: {{timestamp_iso8601_utc}}</div>
    <div>Target: <code>{{target_name}}</code></div>
    <div>Bucket: {{total_bucket}}</div>
  </div>
</header>
<main>

{{failed_bar_banner_or_empty}}

<section class="cards">
  <div class="card score-card"><h3>Total score</h3><div class="num">{{total_score}}</div><div class="sub">{{total_bucket}}</div></div>
  <div class="card weak-card"><h3>Weakest dimension</h3><div class="num">D{{weakest_n}} {{weakest_name}}</div><div class="sub">Score {{weakest_score}} · contributes {{weakest_contribution}}</div></div>
  <div class="card bad-card"><h3>Bad rows</h3><div class="num">{{bad_finding_count}}</div><div class="sub">Across {{bad_finding_dims}} dimensions</div></div>
  <div class="card bars-card {{bars_ok_class}}"><h3>Failed bars</h3><div class="num">{{failed_bar_count}}</div><div class="sub">of 9 cross-cutting gates</div></div>
</section>

<section class="panel">
  <h2>Score breakdown</h2>
  <div class="body">
    <table class="breakdown">
      <thead>
        <tr>
          <th>Dim</th><th>Name</th>
          <th class="num">Weight</th><th class="num">Score</th>
          <th>Visual</th><th>Bucket</th><th class="num">Contribution</th>
        </tr>
      </thead>
      <tbody>
        {{!-- Repeat one row per D1..D10. --}}
        <tr>
          <td><code>D{{n}}</code></td><td>{{dim_name}}</td>
          <td class="num">{{weight_pct}}%</td><td class="num">{{score}}</td>
          <td><span class="bar-bg"><span class="bar-fg bucket-{{bucket_class_short}}" style="width: {{score_pct}}%"></span></span></td>
          <td><span class="pill pill-{{bucket_class_short}}">{{bucket_label}}</span></td>
          <td class="num">{{weighted}}</td>
        </tr>
        <tr style="border-top: 2px solid var(--border);">
          <td colspan="6" style="text-align: right; color: var(--muted); text-transform: uppercase; font-size: 10.5px; letter-spacing: 0.08em;">Total (sum / 100)</td>
          <td class="num"><b>{{total_score}}</b></td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<section class="panel">
  <h2>Top recommendations</h2>
  <div class="body">
    <div class="recs"><ol>{{rec_items}}</ol></div>
  </div>
</section>

<h3 class="section-title">Dimensions</h3>

{{!-- Repeat one <details> per dimension D1..D10. Open by default if score < 7.5. --}}
<details class="dim bucket-{{bucket_class_short}}" {{open_attr}}>
  <summary>
    <span class="id">D{{n}}</span>
    <span class="name">{{dim_name}}</span>
    <span class="pill pill-weight">{{weight_pct}}%</span>
    <span class="pill pill-{{bucket_class_short}}">{{bucket_label}}</span>
    <span class="score-num">{{score}} / 10</span>
  </summary>
  <div class="dim-body">
    <h4>Rationale</h4>
    <p>{{rationale_html}}</p>
    <div class="math">score {{score}} × weight {{weight_pct}}% = contribution {{weighted}}</div>

    <table class="findings">
      <colgroup>
        <col class="col-aspect">
        <col class="col-details">
        <col class="col-grade">
        <col class="col-suggestions">
      </colgroup>
      <thead>
        <tr>
          <th>Aspect</th>
          <th>Details</th>
          <th>Grade</th>
          <th>Suggestions</th>
        </tr>
      </thead>
      <tbody>
        {{!-- Repeat one <tr> per aspect, in source-code/logical order.
             Each row uses class="row-{rating}" and includes a Grade pill. --}}
        <tr class="row-{{row_grade_short}}">
          <td class="col-aspect">{{aspect_name}}</td>
          <td>
            <ul>
              {{detail_bullets}}
            </ul>
          </td>
          <td class="col-grade"><span class="pill pill-{{row_grade_short}}">{{row_grade_label}}</span></td>
          <td>
            <ul>
              {{suggestion_bullets}}
            </ul>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</details>

<h3 class="section-title">Cross-cutting bars</h3>
<section class="panel"><div class="body">
  <div class="bar-list">
    {{!-- one .bar per A..I --}}
    <div class="bar"><span class="id">{{letter}}</span><span class="name">{{bar_name}} — {{bar_note}}</span><span class="pill pill-{{bar_class}}">{{bar_label}}</span></div>
  </div>
</div></section>

<h3 class="section-title">Appendix — reviewed files</h3>
<section class="panel"><div class="body appendix"><pre>{{file_list}}</pre></div></section>

</main>
</body>
</html>
```

### Bucket-class mapping (for slots)

When filling the template, map each score to a short class:

| Score range | `bucket_class_short` / `row_grade_short` | Label |
|-------------|-------------------------------------------|-------|
| ≥ 9.0 | `exceptional` | Exceptional |
| ≥ 8.0 | `excellent`   | Excellent |
| ≥ 7.0 | `good`        | Good |
| ≥ 6.0 | `ok`          | OK |
| < 6.0 | `bad`         | Bad |

`bars_ok_class` is `ok` if zero bars failed, empty otherwise.

---

## Worked-example tone (for your finding rows)

**Good Excellent row** (Aspect + bulleted details + Grade + bulleted suggestions
naming the gap to Exceptional):

```html
<tr class="row-excellent">
  <td class="col-aspect">Per-name column resolution</td>
  <td>
    <ul>
      <li>Calls <code>match_column_identifier</code> per key name at <code>csvdiff.py:110-119</code></li>
      <li>Attaches a file label ("first"/"second input file") to each error</li>
      <li>Diverges from <code>parse_column_identifiers</code> deliberately to preserve the label</li>
    </ul>
  </td>
  <td class="col-grade"><span class="pill pill-excellent">Excellent</span></td>
  <td>
    <ul>
      <li>The <code>label</code> arg is a hardcoded string; doesn't scale beyond two inputs</li>
      <li>Derive label from input index (<code>f"input file #{i+1}"</code>) to future-proof</li>
    </ul>
  </td>
</tr>
```

**Good Bad row** (Aspect + crisp details + Grade + the fix with score lift):

```html
<tr class="row-bad">
  <td class="col-aspect">Duplicate-key validation phase</td>
  <td>
    <ul>
      <li>Check at <code>csvdiff.py:131-142</code> runs inside <code>_index_by_key</code></li>
      <li><code>_index_by_key</code> is invoked from <code>_diff_keyed</code> during the transform phase</li>
      <li>Violates the four-phase contract (validate before transform)</li>
    </ul>
  </td>
  <td class="col-grade"><span class="pill pill-bad">Bad</span></td>
  <td>
    <ul>
      <li>Hoist to a <code>_validate_keys_unique()</code> helper called from <code>main()</code></li>
      <li>Run after read but before <code>_diff_keyed</code></li>
      <li><b>Lifts D3 7.0 → ~8.5</b></li>
    </ul>
  </td>
</tr>
```

**Bad row** (vague, no citation — do not write this):

```html
<tr class="row-bad">
  <td class="col-aspect">Validation</td>
  <td><ul><li>Some validation in wrong place</li></ul></td>
  <td class="col-grade"><span class="pill pill-bad">Bad</span></td>
  <td><ul><li>Fix the validation</li></ul></td>
</tr>
```
