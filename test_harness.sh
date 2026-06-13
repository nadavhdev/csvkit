#!/usr/bin/env bash
# csvdiff test harness — implementation of csv_test_harness.md (black-box).
#
# Single-file bash script. Sections (in order):
#   1. CLI arg parsing & globals
#   2. Logging / color helpers
#   3. Fixture generators
#   4. CLI probe (discovers key flag, exit-code scheme, policies)
#   5. Run-helper + assertion library
#   6. Test runner with retries (PASS / FAIL / FLAKY classification)
#   7. Test functions, grouped by category
#   8. Section dispatcher
#   9. Reporting (text / json / junit)
#  10. Main
#
# Exit 0 iff every functional test passed. With --strict, also fails on
# FLAKY or SKIPPED.

set -u -o pipefail

# ----------------------------------------------------------------------------
# 1. CLI args & globals
# ----------------------------------------------------------------------------

CSVDIFF=""
FILTER=""
RETRIES_FUNC=3
RETRIES_PERF=5
STRICT=0
KEEP=0
NO_COLOR=0
SKIP_PERF=0
REPORT_JSON=""
REPORT_JUNIT=""
REPORT_HTML=""

usage() {
    cat <<'EOF'
Usage: test_harness.sh [options]

  --csvdiff PATH        Path to csvdiff binary (default: discover on PATH or .venv)
  --filter PATTERN      Run only tests matching glob (e.g. 'happy/*', '*schema*')
  --retries N           Override default retries for functional tests (default 3)
  --strict              Exit non-zero on FLAKY or SKIPPED in addition to FAIL
  --keep                Keep working directory after run (for debugging)
  --skip-perf           Skip perf/* category
  --report-json PATH    Also emit JSON report to PATH
  --report-junit PATH   Also emit JUnit XML report to PATH
  --report-html PATH    Also emit a self-contained HTML report to PATH
  --no-color            Plain output
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --csvdiff)       CSVDIFF="$2"; shift 2 ;;
        --filter)        FILTER="$2"; shift 2 ;;
        --retries)       RETRIES_FUNC="$2"; shift 2 ;;
        --strict)        STRICT=1; shift ;;
        --keep)          KEEP=1; shift ;;
        --skip-perf)     SKIP_PERF=1; shift ;;
        --report-json)   REPORT_JSON="$2"; shift 2 ;;
        --report-junit)  REPORT_JUNIT="$2"; shift 2 ;;
        --report-html)   REPORT_HTML="$2"; shift 2 ;;
        --no-color)      NO_COLOR=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *)               echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

# Discover csvdiff if not supplied.
if [[ -z "$CSVDIFF" ]]; then
    if [[ -x "$(dirname "$0")/.venv/bin/csvdiff" ]]; then
        CSVDIFF="$(dirname "$0")/.venv/bin/csvdiff"
    elif command -v csvdiff >/dev/null 2>&1; then
        CSVDIFF="$(command -v csvdiff)"
    else
        echo "Error: csvdiff not found. Pass --csvdiff PATH." >&2
        exit 2
    fi
fi

[[ -x "$CSVDIFF" ]] || { echo "Error: $CSVDIFF is not executable." >&2; exit 2; }

WORK="$(mktemp -d -t csvdiff-harness.XXXXXX)"
cleanup() {
    if [[ $KEEP -eq 0 ]]; then
        rm -rf "$WORK"
    else
        echo "Working dir kept: $WORK"
    fi
}
trap cleanup EXIT

# Result tracking. Parallel arrays indexed by test number.
declare -a RES_NAMES
declare -a RES_DESCS
declare -a RES_STATUS    # PASS | FAIL | FLAKY | SKIPPED
declare -a RES_DETAIL    # failure message or skip reason
declare -a RES_MEDIAN_MS
declare -a RES_TIMES_MS  # space-separated list of per-retry millis
declare -a RES_FAIL_CMD
declare -a RES_FAIL_EXIT
declare -a RES_FAIL_STDOUT
declare -a RES_FAIL_STDERR

# cd_run state — initialized so set -u doesn't bite on tests that never call it.
CD_CMD=""
CD_STDOUT=""
CD_STDERR=""
CD_EXIT=0

# Probe-discovered flags / exit codes / policies.
KEY_FLAG="-k"
FMT_FLAG="--format"
FMT_JSONL_VAL="jsonl"
FMT_SUMMARY_VAL="summary"
NOINF_FLAG="-I"
EXIT_OK=0
EXIT_DIFF=1
EXIT_USAGE=2
NO_KEY_POLICY="unknown"   # positional | require-key | unknown
DUP_POLICY="unknown"      # error | allow | unknown
HELP_HAS_MEMORY_NOTE=0
PROBE_OK=1

# ----------------------------------------------------------------------------
# 2. Logging / color
# ----------------------------------------------------------------------------

if [[ $NO_COLOR -eq 0 ]] && [[ -t 1 ]]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_DIM=""; C_BOLD=""; C_OFF=""
fi

color_status() {
    case "$1" in
        PASS)    printf "%s" "${C_GREEN}PASS${C_OFF}" ;;
        FAIL)    printf "%s" "${C_RED}FAIL${C_OFF}" ;;
        FLAKY)   printf "%s" "${C_YELLOW}FLAKY${C_OFF}" ;;
        SKIPPED) printf "%s" "${C_DIM}SKIP${C_OFF}" ;;
        *)       printf "%s" "$1" ;;
    esac
}

# ----------------------------------------------------------------------------
# 3. Fixture generators
# ----------------------------------------------------------------------------

gen_basic_a() {
    cat > "$1" <<'EOF'
id,name,age
1,Alice,30
2,Bob,25
3,Carol,40
EOF
}

# diff from basic_a: id 2 age 25->26 (changed); id 3 removed; id 4 Dave added
gen_basic_b() {
    cat > "$1" <<'EOF'
id,name,age
1,Alice,30
2,Bob,26
4,Dave,35
EOF
}

# basic_a re-sorted (same data, shuffled rows)
gen_basic_a_resorted() {
    cat > "$1" <<'EOF'
id,name,age
3,Carol,40
1,Alice,30
2,Bob,25
EOF
}

# basic_a + city column
gen_basic_a_added_col() {
    cat > "$1" <<'EOF'
id,name,age,city
1,Alice,30,NYC
2,Bob,25,LA
3,Carol,40,SF
EOF
}

# basic_a minus age column
gen_basic_a_removed_col() {
    cat > "$1" <<'EOF'
id,name
1,Alice
2,Bob
3,Carol
EOF
}

# basic_a with columns reordered (id, age, name)
gen_basic_a_reordered_col() {
    cat > "$1" <<'EOF'
id,age,name
1,30,Alice
2,25,Bob
3,40,Carol
EOF
}

# basic_a but ages as floats (30.0 etc.)
gen_basic_a_typed() {
    cat > "$1" <<'EOF'
id,name,age
1,Alice,30.0
2,Bob,25.0
3,Carol,40.0
EOF
}

gen_dup_keys() {
    cat > "$1" <<'EOF'
id,name,age
1,Alice,30
1,Alicia,31
2,Bob,25
EOF
}

gen_composite_a() {
    cat > "$1" <<'EOF'
year,quarter,revenue
2024,Q1,100
2024,Q2,150
2024,Q3,200
EOF
}

gen_composite_b() {
    cat > "$1" <<'EOF'
year,quarter,revenue
2024,Q1,100
2024,Q2,155
2024,Q3,200
2024,Q4,180
EOF
}

# TSV equivalents (basic_a / basic_b)
gen_tsv_a() { printf 'id\tname\tage\n1\tAlice\t30\n2\tBob\t25\n3\tCarol\t40\n' > "$1"; }
gen_tsv_b() { printf 'id\tname\tage\n1\tAlice\t30\n2\tBob\t26\n4\tDave\t35\n' > "$1"; }

# Semicolon-delimited
gen_semi_a() { printf 'id;name;age\n1;Alice;30\n2;Bob;25\n3;Carol;40\n' > "$1"; }
gen_semi_b() { printf 'id;name;age\n1;Alice;30\n2;Bob;26\n4;Dave;35\n' > "$1"; }

# UTF-8 BOM + identical to basic_a
gen_bom_a() {
    printf '\xef\xbb\xbfid,name,age\n1,Alice,30\n2,Bob,25\n3,Carol,40\n' > "$1"
}

# Unicode in name column; row 2's name differs
gen_unicode_a() {
    printf 'id,name,note\n1,\xe7\x94\xb0\xe4\xb8\xad,hello\n2,\xf0\x9f\x98\x80,smile\n' > "$1"
}
gen_unicode_b() {
    printf 'id,name,note\n1,\xe7\x94\xb0\xe4\xb8\xad,hello\n2,\xf0\x9f\x98\x81,smirk\n' > "$1"
}

# Embedded newline inside a quoted cell. Identical pair (no diff).
gen_embedded_newline_a() {
    printf 'id,note\n1,"line1\nline2"\n2,plain\n' > "$1"
}
gen_embedded_newline_b() { gen_embedded_newline_a "$1"; }

# Single 100KB cell
gen_long_cell_a() {
    local big; big="$(python3 -c 'print("x"*100000)')"
    printf 'id,blob\n1,%s\n' "$big" > "$1"
}
gen_long_cell_b() {
    local big; big="$(python3 -c 'print("y"*100000)')"
    printf 'id,blob\n1,%s\n' "$big" > "$1"
}

# Leading zeros
gen_leading_zeros_a() { printf 'id,name\n007,a\n008,b\n009,c\n' > "$1"; }
gen_leading_zeros_b() { printf 'id,name\n7,a\n8,b\n9,c\n' > "$1"; }

# Dates MM/DD/YYYY
gen_dates_a() { printf 'id,when\n1,01/15/2024\n2,02/20/2024\n' > "$1"; }
gen_dates_b() { printf 'id,when\n1,01/15/2024\n2,02/21/2024\n' > "$1"; }

# Nulls
gen_blanks_a() { printf 'id,v\n1,\n2,NA\n3,NULL\n' > "$1"; }
gen_blanks_b() { printf 'id,v\n1,\n2,\n3,\n' > "$1"; }

# Truly empty file (0 bytes)
gen_empty() { : > "$1"; }

# Header-only file (0 data rows)
gen_header_only() { printf 'id,name,age\n' > "$1"; }

# Duplicate column names in header
gen_dup_cols() { printf 'a,b,a\n1,2,3\n4,5,6\n' > "$1"; }

# Latin-1 encoded with non-ASCII; row 2 differs
gen_latin1_a() { printf 'id,name\n1,Caf\xe9\n2,No\xebl\n' > "$1"; }
gen_latin1_b() { printf 'id,name\n1,Caf\xe9\n2,Noel\n' > "$1"; }

# CRLF vs LF — same data, different line endings
gen_crlf_a() { printf 'id,name\r\n1,a\r\n2,b\r\n' > "$1"; }
gen_lf_a()   { printf 'id,name\n1,a\n2,b\n' > "$1"; }

# Same key column but no shared data columns
gen_keyonly_a() { printf 'id,extra_a\n1,a1\n2,a2\n' > "$1"; }
gen_keyonly_b() { printf 'id,extra_b\n1,b1\n2,b2\n' > "$1"; }

# Skip-lines fixtures: 2 comment lines, then header & data
gen_skip_a() { printf '# comment 1\n# comment 2\nid,name\n1,a\n2,b\n' > "$1"; }
gen_skip_b() { printf '# comment 1\n# comment 2\nid,name\n1,a\n2,B\n' > "$1"; }

# No-header-row fixtures
gen_noheader_a() { printf '1,a\n2,b\n3,c\n' > "$1"; }
gen_noheader_b() { printf '1,a\n2,B\n3,c\n' > "$1"; }

# Performance fixtures (awk for speed)
gen_perf_pair() {
    # gen_perf_pair A B N M PCT_CHANGE
    local A="$1" B="$2" N="$3" M="$4" PCT="$5"
    awk -v n="$N" -v m="$M" 'BEGIN{
        printf "id"; for (j=1; j<m; j++) printf ",col%d", j; printf "\n";
        for (i=1; i<=n; i++) {
            printf "%d", i;
            for (j=1; j<m; j++) printf ",val_%d_%d", i, j;
            printf "\n";
        }
    }' > "$A"
    awk -v n="$N" -v m="$M" -v pct="$PCT" 'BEGIN{
        srand(42);
        printf "id"; for (j=1; j<m; j++) printf ",col%d", j; printf "\n";
        for (i=1; i<=n; i++) {
            printf "%d", i;
            for (j=1; j<m; j++) {
                if (rand()*100 < pct) printf ",X_%d_%d", i, j;
                else printf ",val_%d_%d", i, j;
            }
            printf "\n";
        }
    }' > "$B"
}

generate_all_fixtures() {
    gen_basic_a              "$WORK/basic_a.csv"
    gen_basic_b              "$WORK/basic_b.csv"
    gen_basic_a_resorted     "$WORK/basic_a_resorted.csv"
    gen_basic_a_added_col    "$WORK/basic_a_added_col.csv"
    gen_basic_a_removed_col  "$WORK/basic_a_removed_col.csv"
    gen_basic_a_reordered_col "$WORK/basic_a_reordered_col.csv"
    gen_basic_a_typed        "$WORK/basic_a_typed.csv"
    gen_dup_keys             "$WORK/dup_keys.csv"
    gen_composite_a          "$WORK/composite_a.csv"
    gen_composite_b          "$WORK/composite_b.csv"
    gen_tsv_a                "$WORK/tsv_a.tsv"
    gen_tsv_b                "$WORK/tsv_b.tsv"
    gen_semi_a               "$WORK/semi_a.csv"
    gen_semi_b               "$WORK/semi_b.csv"
    gen_bom_a                "$WORK/bom_a.csv"
    gen_unicode_a            "$WORK/unicode_a.csv"
    gen_unicode_b            "$WORK/unicode_b.csv"
    gen_embedded_newline_a   "$WORK/emnl_a.csv"
    gen_embedded_newline_b   "$WORK/emnl_b.csv"
    gen_long_cell_a          "$WORK/long_a.csv"
    gen_long_cell_b          "$WORK/long_b.csv"
    gen_leading_zeros_a      "$WORK/lz_a.csv"
    gen_leading_zeros_b      "$WORK/lz_b.csv"
    gen_dates_a              "$WORK/dates_a.csv"
    gen_dates_b              "$WORK/dates_b.csv"
    gen_blanks_a             "$WORK/blanks_a.csv"
    gen_blanks_b             "$WORK/blanks_b.csv"
    gen_empty                "$WORK/empty.csv"
    gen_header_only          "$WORK/header_only.csv"
    gen_dup_cols             "$WORK/dup_cols.csv"
    gen_latin1_a             "$WORK/latin1_a.csv"
    gen_latin1_b             "$WORK/latin1_b.csv"
    gen_crlf_a               "$WORK/crlf_a.csv"
    gen_lf_a                 "$WORK/lf_a.csv"
    gen_keyonly_a            "$WORK/keyonly_a.csv"
    gen_keyonly_b            "$WORK/keyonly_b.csv"
    gen_skip_a               "$WORK/skip_a.csv"
    gen_skip_b               "$WORK/skip_b.csv"
    gen_noheader_a           "$WORK/noh_a.csv"
    gen_noheader_b           "$WORK/noh_b.csv"
}

# ----------------------------------------------------------------------------
# 4. CLI probe
# ----------------------------------------------------------------------------

probe_cli() {
    local help; help="$("$CSVDIFF" --help 2>&1 || true)"

    # Memory-note epilog (R11) — case-insensitive.
    if echo "$help" | grep -qiE 'memor(y|ies)|index(es|ed)? .*(in )?memory'; then
        HELP_HAS_MEMORY_NOTE=1
    fi

    # Key flag detection. Prefer the short form if present.
    if echo "$help" | grep -qE -- '(^|[[:space:],])-k([[:space:],]|$)'; then
        KEY_FLAG="-k"
    elif echo "$help" | grep -qE -- '--key([[:space:],=]|$)'; then
        KEY_FLAG="--key"
    else
        KEY_FLAG=""
    fi

    # Format flag detection
    if echo "$help" | grep -qE -- '--format'; then
        FMT_FLAG="--format"
    else
        FMT_FLAG=""
    fi

    # No-inference flag detection
    if echo "$help" | grep -qE -- '(^|[[:space:],])-I([[:space:],]|$)'; then
        NOINF_FLAG="-I"
    elif echo "$help" | grep -qE -- '--no-inference'; then
        NOINF_FLAG="--no-inference"
    else
        NOINF_FLAG=""
    fi

    # Exit code probes — need a tiny fixture
    local tiny="$WORK/.probe_a.csv" tiny2="$WORK/.probe_b.csv"
    printf 'a,b,c\n1,2,3\n' > "$tiny"
    printf 'a,b,c\n1,2,4\n' > "$tiny2"

    "$CSVDIFF" $KEY_FLAG a "$tiny" "$tiny" >/dev/null 2>&1
    EXIT_OK=$?

    "$CSVDIFF" $KEY_FLAG a "$tiny" "$tiny2" >/dev/null 2>&1
    EXIT_DIFF=$?

    "$CSVDIFF" $KEY_FLAG nope "$tiny" "$tiny" >/dev/null 2>&1
    EXIT_USAGE=$?

    # No-key default policy
    local nk_err="$WORK/.nk.err"
    "$CSVDIFF" "$tiny" "$tiny" >/dev/null 2>"$nk_err"
    local nk_ec=$?
    if [[ $nk_ec -eq $EXIT_OK ]]; then
        NO_KEY_POLICY="positional"
    elif [[ $nk_ec -eq $EXIT_USAGE ]] && grep -qiE 'key' "$nk_err"; then
        NO_KEY_POLICY="require-key"
    elif [[ $nk_ec -eq $EXIT_OK ]] || [[ $nk_ec -eq $EXIT_DIFF ]]; then
        NO_KEY_POLICY="positional"
    else
        NO_KEY_POLICY="unknown"
    fi

    # Duplicate-key policy
    local dup="$WORK/.dup.csv"
    printf 'id,name\n1,a\n1,b\n2,c\n' > "$dup"
    "$CSVDIFF" $KEY_FLAG id "$dup" "$tiny" >/dev/null 2>&1
    local dec=$?
    if [[ $dec -eq $EXIT_USAGE ]]; then
        DUP_POLICY="error"
    else
        DUP_POLICY="allow"
    fi

    # Sanity
    if [[ -z "$KEY_FLAG" ]] || [[ "$EXIT_OK" == "$EXIT_DIFF" ]]; then
        PROBE_OK=0
    fi
}

# ----------------------------------------------------------------------------
# 5. Run-helper + assertions
# ----------------------------------------------------------------------------

# Run csvdiff, capture stdout / stderr / exit code into CD_STDOUT, CD_STDERR, CD_EXIT.
cd_run() {
    local out err
    out="$WORK/.run.out"; err="$WORK/.run.err"
    CD_CMD="csvdiff $*"
    "$CSVDIFF" "$@" >"$out" 2>"$err"
    CD_EXIT=$?
    CD_STDOUT="$(cat "$out")"
    CD_STDERR="$(cat "$err")"
}

# Like cd_run but pipes a file in as STDIN.
cd_run_stdin() {
    local stdin_file="$1"; shift
    local out err
    out="$WORK/.run.out"; err="$WORK/.run.err"
    CD_CMD="cat $stdin_file | csvdiff $*"
    "$CSVDIFF" "$@" <"$stdin_file" >"$out" 2>"$err"
    CD_EXIT=$?
    CD_STDOUT="$(cat "$out")"
    CD_STDERR="$(cat "$err")"
}

# Assertion helpers. Each returns 0/1 and writes to FAIL_MSG on failure.
FAIL_MSG=""

_fail() { FAIL_MSG="$1"; return 1; }

assert_eq() {
    local expected="$1" actual="$2" what="$3"
    [[ "$expected" == "$actual" ]] && return 0
    _fail "$what: expected '$expected', got '$actual'"
}

assert_ne() {
    local notwanted="$1" actual="$2" what="$3"
    [[ "$notwanted" != "$actual" ]] && return 0
    _fail "$what: expected NOT '$notwanted', but got that value"
}

assert_contains() {
    local needle="$1" haystack="$2" what="$3"
    [[ "$haystack" == *"$needle"* ]] && return 0
    _fail "$what: expected substring '$needle' not found in output"
}

assert_not_contains() {
    local needle="$1" haystack="$2" what="$3"
    [[ "$haystack" != *"$needle"* ]] && return 0
    _fail "$what: unwanted substring '$needle' was present"
}

assert_match() {
    local pattern="$1" haystack="$2" what="$3"
    [[ "$haystack" =~ $pattern ]] && return 0
    _fail "$what: regex /$pattern/ did not match"
}

assert_no_traceback() {
    local err="$1" what="$2"
    if [[ "$err" == *"Traceback"* ]]; then
        _fail "$what: unexpected Python traceback in stderr"
        return 1
    fi
    return 0
}

assert_json_valid() {
    local s="$1" what="$2"
    if echo "$s" | python3 -m json.tool >/dev/null 2>&1; then
        return 0
    fi
    _fail "$what: stdout is not valid JSON"
}

# Extract a JSON value (string) via python.
json_path() {
    # json_path STDIN_VAR PATH(dotted, e.g. summary.added)
    python3 - "$2" <<'PY' <<<"$1"
import json, sys
path = sys.argv[1].split('.')
data = json.load(sys.stdin)
for k in path:
    if isinstance(data, list):
        data = data[int(k)]
    else:
        data = data[k]
print(data)
PY
}

# ----------------------------------------------------------------------------
# 6. Test runner with retries
# ----------------------------------------------------------------------------

# Wall-clock millis (portable-ish; falls back to seconds on platforms without %N).
now_ms() {
    if date +%s%N | grep -qE '^[0-9]+N?$'; then
        # %N not supported (some BSDs print '%N' literal). Use python.
        python3 -c "import time; print(int(time.time()*1000))"
    else
        printf '%d' $(( $(date +%s%N) / 1000000 ))
    fi
}

# run_test ID DESC FUNC [RETRIES]
run_test() {
    local id="$1" desc="$2" func="$3" retries="${4:-$RETRIES_FUNC}"

    if [[ -n "$FILTER" ]] && ! [[ "$id" == $FILTER ]]; then
        # Not matched; quietly skip.
        return 0
    fi

    local pass=0 fail=0 first_fail_msg=""
    local first_fail_cmd="" first_fail_stdout="" first_fail_stderr="" first_fail_exit=""
    local times_ms=()

    local i
    for i in $(seq 1 "$retries"); do
        FAIL_MSG=""
        CD_CMD=""; CD_STDOUT=""; CD_STDERR=""; CD_EXIT=0
        local t0; t0=$(now_ms)
        local rc=0
        $func || rc=$?
        local t1; t1=$(now_ms)
        times_ms+=( $((t1 - t0)) )
        if (( rc == 0 )); then
            pass=$((pass + 1))
        else
            fail=$((fail + 1))
            if [[ -z "$first_fail_msg" ]]; then
                first_fail_msg="${FAIL_MSG:-(no diagnostic)}"
                first_fail_cmd="$CD_CMD"
                first_fail_stdout="$CD_STDOUT"
                first_fail_stderr="$CD_STDERR"
                first_fail_exit="$CD_EXIT"
            fi
        fi
    done

    local status
    if (( pass == retries )); then status="PASS"
    elif (( fail == retries )); then status="FAIL"
    else status="FLAKY"
    fi

    # Compute median (portable; bash 3.2 has no mapfile)
    local sorted=()
    local line
    while IFS= read -r line; do
        sorted+=( "$line" )
    done < <(printf '%s\n' "${times_ms[@]}" | sort -n)
    local mid=$(( ${#sorted[@]} / 2 ))
    local median_ms="${sorted[$mid]}"

    RES_NAMES+=( "$id" )
    RES_DESCS+=( "$desc" )
    RES_STATUS+=( "$status" )
    RES_DETAIL+=( "$first_fail_msg" )
    RES_MEDIAN_MS+=( "$median_ms" )
    RES_TIMES_MS+=( "${times_ms[*]}" )
    RES_FAIL_CMD+=( "$first_fail_cmd" )
    RES_FAIL_EXIT+=( "$first_fail_exit" )
    RES_FAIL_STDOUT+=( "$first_fail_stdout" )
    RES_FAIL_STDERR+=( "$first_fail_stderr" )

    printf '  [%s] %-40s %5sms\n' "$(color_status "$status")" "$id" "$median_ms"
    if [[ "$status" != "PASS" ]] && [[ -n "$first_fail_msg" ]]; then
        printf '       %s%s%s\n' "$C_DIM" "$first_fail_msg" "$C_OFF"
    fi
}

skip_test() {
    local id="$1" desc="$2" reason="$3"
    if [[ -n "$FILTER" ]] && ! [[ "$id" == $FILTER ]]; then
        return 0
    fi
    RES_NAMES+=( "$id" )
    RES_DESCS+=( "$desc" )
    RES_STATUS+=( "SKIPPED" )
    RES_DETAIL+=( "$reason" )
    RES_MEDIAN_MS+=( "0" )
    RES_TIMES_MS+=( "0" )
    RES_FAIL_CMD+=( "" )
    RES_FAIL_EXIT+=( "" )
    RES_FAIL_STDOUT+=( "" )
    RES_FAIL_STDERR+=( "" )
    printf '  [%s] %-40s %s\n' "$(color_status SKIPPED)" "$id" "$reason"
}

# ----------------------------------------------------------------------------
# 7. Test functions
# ----------------------------------------------------------------------------

# --- HAPPY ------------------------------------------------------------------

test_H01_identical() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit code" || return 1
    assert_match '0[^,]*changed.*0[^,]*added.*0[^,]*removed.*3 rows compared' \
        "$CD_STDOUT" "summary line" || return 1
}

test_H02_no_key_identical() {
    cd_run "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    if [[ "$NO_KEY_POLICY" == "positional" ]]; then
        assert_eq "$EXIT_OK" "$CD_EXIT" "exit code (positional default)" || return 1
    elif [[ "$NO_KEY_POLICY" == "require-key" ]]; then
        assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit code (require-key default)" || return 1
        assert_match '[Kk]ey' "$CD_STDERR" "stderr mentions key" || return 1
    else
        _fail "no-key policy could not be probed"; return 1
    fi
}

test_H03_added_row() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*added' "$CD_STDOUT" "summary added=1" || return 1
    printf '%s\n' "$CD_STDOUT" | grep -qE '^\+.*4.*Dave' \
        || { _fail "added row + marker with key 4 and Dave not found"; return 1; }
}

test_H04_removed_row() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*removed' "$CD_STDOUT" "summary removed=1" || return 1
    printf '%s\n' "$CD_STDOUT" | grep -qE '^-.*3.*Carol' \
        || { _fail "removed row - marker with key 3 and Carol not found"; return 1; }
}

test_H05_changed_field() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "summary changed=1" || return 1
    printf '%s\n' "$CD_STDOUT" | grep -qE '^~.*2.*age.*25.*26' \
        || { _fail "~ line for id 2 with age 25->26 not found"; return 1; }
    # unchanged column "name" must not appear on the ~ line for id=2.
    local changed_line
    changed_line=$(echo "$CD_STDOUT" | grep -E '^~' | grep -F '2' | head -1)
    if [[ "$changed_line" == *"name"* ]]; then
        _fail "unchanged column 'name' incorrectly listed on changed line: $changed_line"
        return 1
    fi
}

test_H06_mixed_counts() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed.*2 rows compared' \
        "$CD_STDOUT" "exact mixed counts" || return 1
    local plus minus tilde
    plus=$(echo "$CD_STDOUT" | grep -cE '^\+')
    minus=$(echo "$CD_STDOUT" | grep -cE '^-')
    tilde=$(echo "$CD_STDOUT" | grep -cE '^~')
    assert_eq "1" "$plus" "exactly one + row" || return 1
    assert_eq "1" "$minus" "exactly one - row" || return 1
    assert_eq "1" "$tilde" "exactly one ~ row" || return 1
}

test_H07_unchanged_fields_omitted() {
    # Make a fixture where only one of three columns changes.
    local A="$WORK/h07_a.csv" B="$WORK/h07_b.csv"
    printf 'id,name,age\n1,Alice,30\n' > "$A"
    printf 'id,name,age\n1,Alice,31\n' > "$B"
    cd_run $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    local tilde; tilde=$(echo "$CD_STDOUT" | grep -E '^~' | head -1)
    [[ -n "$tilde" ]] || { _fail "expected a ~ line"; return 1; }
    # The single ~ line must mention age but not name.
    if [[ "$tilde" != *"age"* ]]; then _fail "~ line missing 'age': $tilde"; return 1; fi
    if [[ "$tilde" == *"name"* ]]; then _fail "~ line should not mention unchanged 'name': $tilde"; return 1; fi
}

test_H08_identical_no_row_section() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0" || return 1
    # When identical, no '+', '-', or '~' marker rows at line-start.
    if echo "$CD_STDOUT" | grep -qE '^[+\-~] '; then
        _fail "unexpected diff markers in identical-files output"; return 1
    fi
}

test_H09a_no_key_positional() {
    [[ "$NO_KEY_POLICY" == "positional" ]] || return 0
    cd_run "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    # Row 1 same; row 2 age differs; row 3 entirely different.
    assert_match '2[^,]*changed' "$CD_STDOUT" "summary changed >=1" || return 1
}

test_H09b_no_key_require() {
    [[ "$NO_KEY_POLICY" == "require-key" ]] || return 0
    cd_run "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage" || return 1
    assert_match '[Kk]ey' "$CD_STDERR" "stderr mentions key" || return 1
}

test_H10_help_mentions_memory() {
    [[ $HELP_HAS_MEMORY_NOTE -eq 1 ]] && return 0
    _fail "csvdiff --help does not mention memory tradeoff (R11)"; return 1
}

test_H11_determinism() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    local out1="$CD_STDOUT"
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    local out2="$CD_STDOUT"
    assert_eq "$out1" "$out2" "byte-identical stdout across two runs" || return 1
}

# --- ALTERNATE --------------------------------------------------------------

test_A01_composite_key() {
    cd_run $KEY_FLAG year,quarter "$WORK/composite_a.csv" "$WORK/composite_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    printf '%s\n' "$CD_STDOUT" | grep -qE '^~.*2024.*Q2.*revenue.*150.*155' \
        || { _fail "~ line for composite key 2024,Q2 not found"; return 1; }
    printf '%s\n' "$CD_STDOUT" | grep -qE '^\+.*2024.*Q4' \
        || { _fail "+ row for 2024,Q4 not found"; return 1; }
}

test_A02_three_col_composite() {
    local A="$WORK/a02_a.csv" B="$WORK/a02_b.csv"
    printf 'a,b,c,v\n1,1,1,x\n1,1,2,y\n' > "$A"
    printf 'a,b,c,v\n1,1,1,X\n1,1,2,y\n' > "$B"
    cd_run $KEY_FLAG a,b,c "$A" "$B"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    # Keys render as typed values (agate infers an all-"1" column as Boolean True),
    # so assert a 3-part composite key tuple plus the v change rather than literal 1s.
    printf '%s\n' "$CD_STDOUT" | grep -qE '^~ key=\(.*,.*,.*\).*v: x -> X' \
        || { _fail "~ row for composite key (3 parts) changing v: x -> X not found"; return 1; }
}

test_A03_key_by_index() {
    cd_run $KEY_FLAG 1 "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "diff via index key" || return 1
}

test_A04_json_format() {
    [[ -n "$FMT_FLAG" ]] || { _fail "no --format flag advertised in help"; return 1; }
    cd_run "$FMT_FLAG" "$FMT_JSONL_VAL" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    # jsonl: one JSON object per line; the first line is the summary event with
    # flat top-level counts (event, compared, changed, added, removed).
    local summary_line; summary_line=$(printf '%s' "$CD_STDOUT" | head -1)
    assert_json_valid "$summary_line" "first jsonl line is valid JSON" || return 1
    local added; added=$(printf '%s' "$summary_line" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d["added"])')
    assert_eq "1" "$added" "summary event added=1" || return 1
}

test_A04b_json_identical() {
    [[ -n "$FMT_FLAG" ]] || return 0
    cd_run "$FMT_FLAG" "$FMT_JSONL_VAL" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit code" || return 1
    local summary_line; summary_line=$(printf '%s' "$CD_STDOUT" | head -1)
    assert_json_valid "$summary_line" "first jsonl line is valid JSON" || return 1
}

test_A05_summary_format() {
    [[ -n "$FMT_FLAG" ]] || { _fail "no --format flag advertised in help"; return 1; }
    cd_run "$FMT_FLAG" "$FMT_SUMMARY_VAL" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    # summary format emits only the headline counts — no per-row markers.
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "headline counts" || return 1
    if printf '%s' "$CD_STDOUT" | grep -qE '^[+~-] '; then
        _fail "summary format must not emit per-row +/-/~ markers"; return 1
    fi
}

test_A05b_summary_identical_headline_only() {
    [[ -n "$FMT_FLAG" ]] || return 0
    cd_run "$FMT_FLAG" "$FMT_SUMMARY_VAL" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit code" || return 1
    local nlines; nlines=$(printf '%s' "$CD_STDOUT" | grep -cE '.')
    # summary emits a single headline line on identical inputs (no per-row records).
    assert_eq "1" "$nlines" "summary is one headline line on identical inputs" || return 1
}

test_A06_stdin_for_second() {
    cd_run_stdin "$WORK/basic_b.csv" $KEY_FLAG id "$WORK/basic_a.csv" -
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "diff via stdin B" || return 1
}

test_A07_stdin_for_first() {
    cd_run_stdin "$WORK/basic_a.csv" $KEY_FLAG id - "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "diff via stdin A" || return 1
}

test_A08_schema_added_col() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_added_col.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '[Ss]chema' "$CD_STDOUT" "schema section appears" || return 1
    assert_match 'city' "$CD_STDOUT" "added column 'city' mentioned" || return 1
    assert_match '0[^,]*changed.*0[^,]*added.*0[^,]*removed' "$CD_STDOUT" "no row diffs" || return 1
    # Schema section must come BEFORE row diffs (it's the only differences here,
    # but check the section appears before the summary's row counts? Actually
    # PRD says schema BEFORE row diffs section). Verify schema appears before
    # any +/-/~ line — none here. We at least assert schema is present.
}

test_A09_schema_removed_col() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_removed_col.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match 'age' "$CD_STDOUT" "removed column 'age' mentioned" || return 1
    assert_match '[Ss]chema' "$CD_STDOUT" "schema section present" || return 1
}

test_A10_schema_reordered() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_reordered_col.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '[Ss]chema' "$CD_STDOUT" "schema section present" || return 1
    # No row diffs (data compared by name).
    assert_match '0[^,]*changed.*0[^,]*added.*0[^,]*removed' "$CD_STDOUT" "0 row diffs on reorder" || return 1
}

test_A11_resorted() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_resorted.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on resorted" || return 1
    assert_match '0[^,]*changed.*0[^,]*added.*0[^,]*removed.*3 rows compared' "$CD_STDOUT" "all unchanged" || return 1
}

test_A12_no_inference_string() {
    [[ -n "$NOINF_FLAG" ]] || { _fail "no --no-inference flag advertised"; return 1; }
    cd_run "$NOINF_FLAG" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_typed.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '3[^,]*changed' "$CD_STDOUT" "all 3 rows changed under string compare" || return 1
}

test_A13_typed_equal() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a_typed.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0: typed compare equates 30 and 30.0" || return 1
}

test_A14_tabs() {
    cd_run -t $KEY_FLAG id "$WORK/tsv_a.tsv" "$WORK/tsv_b.tsv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "diff on TSV" || return 1
}

test_A15_semi_delimiter() {
    cd_run -d ';' $KEY_FLAG id "$WORK/semi_a.csv" "$WORK/semi_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed.*1[^,]*added.*1[^,]*removed' "$CD_STDOUT" "diff on semicolon" || return 1
}

test_A16_latin1_encoding() {
    cd_run -e latin1 $KEY_FLAG id "$WORK/latin1_a.csv" "$WORK/latin1_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "1 row changed on latin1 inputs" || return 1
}

test_A17_no_header_row() {
    cd_run -H $KEY_FLAG 1 "$WORK/noh_a.csv" "$WORK/noh_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "1 row changed" || return 1
}

test_A18_skip_lines() {
    cd_run -K 2 $KEY_FLAG id "$WORK/skip_a.csv" "$WORK/skip_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit code" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "1 row changed after skipping comments" || return 1
}

# --- ERROR ------------------------------------------------------------------

test_E01_no_input_tty() {
    # When stdin is not a tty (we redirect /dev/null), some impls accept it
    # as empty input. The PRD only requires guarding the *tty* case. We
    # therefore assert: exit is non-zero (some error reported).
    "$CSVDIFF" </dev/null >/dev/null 2>"$WORK/.run.err"
    CD_EXIT=$?
    [[ $CD_EXIT -ne 0 ]] || { _fail "expected non-zero exit on no input"; return 1; }
}

test_E02_one_arg_with_piped_stdin() {
    # Documented stdin contract (TDD §4c): with one file arg and piped/redirected
    # data on stdin, stdin is the LEFT input — a valid two-input diff, not a usage
    # error. The interactive (tty + one-arg) case DOES error, but a harness cannot
    # allocate a tty, so that path is not asserted here.
    cd_run_stdin "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "one arg + piped stdin = valid (stdin,file) diff" || return 1
    assert_no_traceback "$CD_STDERR" "no traceback on one-arg + piped stdin" || return 1
}

test_E03_three_args() {
    cd_run "$WORK/basic_a.csv" "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage" || return 1
}

test_E04_missing_file() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/nonexistent_xyz.csv"
    [[ $CD_EXIT -ne 0 ]] || { _fail "expected non-zero exit on missing file"; return 1; }
    assert_no_traceback "$CD_STDERR" "no Python traceback on missing file" || return 1
    assert_match '([Nn]o such file|FileNotFound|cannot open|not found)' "$CD_STDERR" \
        "stderr mentions missing file" || return 1
}

test_E05_unreadable_file() {
    local u="$WORK/unreadable.csv"
    cp "$WORK/basic_a.csv" "$u"
    chmod 000 "$u"
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$u"
    local ec=$CD_EXIT
    chmod 644 "$u"
    [[ $ec -ne 0 ]] || { _fail "expected non-zero exit on unreadable file"; return 1; }
    assert_no_traceback "$CD_STDERR" "no Python traceback on unreadable" || return 1
}

test_E06_bad_key_name() {
    cd_run $KEY_FLAG nope "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage" || return 1
    assert_contains "nope" "$CD_STDERR" "stderr names the bad column" || return 1
}

test_E07_bad_key_index() {
    cd_run $KEY_FLAG 999 "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage" || return 1
}

test_E08_dup_keys_first() {
    if [[ "$DUP_POLICY" == "error" ]]; then
        cd_run $KEY_FLAG id "$WORK/dup_keys.csv" "$WORK/basic_a.csv"
        assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage on duplicate keys in file A" || return 1
        assert_match '[Dd]uplicate' "$CD_STDERR" "stderr mentions duplicate" || return 1
    else
        # Allow policy: should not error; should produce *some* output.
        cd_run $KEY_FLAG id "$WORK/dup_keys.csv" "$WORK/basic_a.csv"
        [[ $CD_EXIT -ne $EXIT_USAGE ]] || { _fail "policy=allow but got USAGE exit"; return 1; }
    fi
}

test_E09_dup_keys_second() {
    if [[ "$DUP_POLICY" == "error" ]]; then
        cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/dup_keys.csv"
        assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage on duplicate keys in file B" || return 1
    else
        cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/dup_keys.csv"
        [[ $CD_EXIT -ne $EXIT_USAGE ]] || { _fail "policy=allow but got USAGE exit"; return 1; }
    fi
}

test_E10_help() {
    cd_run -h
    assert_eq "0" "$CD_EXIT" "exit 0 for -h" || return 1
    assert_contains "usage" "$CD_STDOUT" "help mentions 'usage'" || return 1
    cd_run --help
    assert_eq "0" "$CD_EXIT" "exit 0 for --help" || return 1
}

test_E11_version() {
    cd_run -V
    assert_eq "0" "$CD_EXIT" "exit 0 for -V" || return 1
    assert_match '[0-9]+\.[0-9]+' "$CD_STDOUT" "version string" || return 1
    cd_run --version
    assert_eq "0" "$CD_EXIT" "exit 0 for --version" || return 1
}

test_E12_invalid_format_value() {
    [[ -n "$FMT_FLAG" ]] || return 0
    cd_run "$FMT_FLAG" yaml "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "exit usage on bad --format value" || return 1
}

test_E13_t_overrides_d() {
    # Per common-args inheritance: -t overrides -d. Run with both; should succeed.
    cd_run -t -d ';' $KEY_FLAG id "$WORK/tsv_a.tsv" "$WORK/tsv_a.tsv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 when -t overrides -d" || return 1
}

test_E14_stdin_ignored_with_two_files() {
    # Pipe stdin but pass two file args; stdin must be ignored.
    cd_run_stdin "$WORK/basic_b.csv" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "stdin ignored when both args given; A vs A is 0 diff" || return 1
}

test_E15_empty_key_arg() {
    # An empty --key value is treated as "no key given" — identical to csvjoin,
    # whose --columns uses the same `if self.args.columns:` falsy check (verified:
    # `csvjoin -c '' a b` also falls back and exits 0). The TDD mandates key
    # parsing be "identical to csvjoin's --columns", so csvdiff falling back to
    # positional mode (exit 0 on identical files), with no traceback, is the
    # spec-correct contract — not a usage error.
    cd_run $KEY_FLAG '' "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "empty --key falls back to positional (csvjoin-consistent)" || return 1
    assert_no_traceback "$CD_STDERR" "no traceback on empty --key" || return 1
}

# --- EDGE -------------------------------------------------------------------

test_ED01_empty_files() {
    cd_run $KEY_FLAG id "$WORK/empty.csv" "$WORK/empty.csv"
    assert_no_traceback "$CD_STDERR" "no traceback on empty files" || return 1
}

test_ED02_header_only() {
    cd_run $KEY_FLAG id "$WORK/header_only.csv" "$WORK/header_only.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on identical header-only files" || return 1
    assert_match '0[^,]*changed.*0[^,]*added.*0[^,]*removed' "$CD_STDOUT" "0 diffs" || return 1
}

test_ED03_single_row_change() {
    local A="$WORK/ed03_a.csv" B="$WORK/ed03_b.csv"
    printf 'id,v\n1,a\n' > "$A"
    printf 'id,v\n1,b\n' > "$B"
    cd_run $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "1 changed" || return 1
}

test_ED04_lf_vs_crlf() {
    local crlf="$WORK/ed04_crlf.csv"
    printf 'id,v\r\n1,a\r\n2,b\r\n' > "$crlf"
    local lf="$WORK/ed04_lf.csv"
    printf 'id,v\n1,a\n2,b\n' > "$lf"
    cd_run $KEY_FLAG id "$crlf" "$lf"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0: line endings don't count as row diffs" || return 1
}

test_ED05_bom() {
    cd_run $KEY_FLAG id "$WORK/bom_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "BOM transparent" || return 1
}

test_ED06_unicode() {
    cd_run $KEY_FLAG id "$WORK/unicode_a.csv" "$WORK/unicode_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    # The CJK and emoji should appear in output bytes (UTF-8).
    if ! LC_ALL=C grep -q $'\xf0\x9f\x98' <<<"$CD_STDOUT"; then
        _fail "expected an emoji byte sequence in output"
        return 1
    fi
}

test_ED07_embedded_newline() {
    cd_run $KEY_FLAG id "$WORK/emnl_a.csv" "$WORK/emnl_b.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "identical files with embedded newlines" || return 1
}

test_ED08_long_cell() {
    cd_run -z 200000 $KEY_FLAG id "$WORK/long_a.csv" "$WORK/long_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff on 100k cell change" || return 1
}

test_ED09_leading_zeros() {
    # With --no-leading-zeroes, "007" is kept as string; "7" is numeric. Different.
    cd_run --no-leading-zeroes $KEY_FLAG name "$WORK/lz_a.csv" "$WORK/lz_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "007 vs 7 differs under --no-leading-zeroes" || return 1
}

test_ED10_date_format() {
    cd_run --date-format '%m/%d/%Y' $KEY_FLAG id "$WORK/dates_a.csv" "$WORK/dates_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '1[^,]*changed' "$CD_STDOUT" "1 changed" || return 1
}

test_ED11_blanks() {
    # Default: "" and "NA" both treated as NULL → identical content.
    cd_run $KEY_FLAG id "$WORK/blanks_a.csv" "$WORK/blanks_b.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "default blanks-as-null: identical" || return 1
    # With --blanks: NA/NULL are literal strings → differ.
    cd_run --blanks $KEY_FLAG id "$WORK/blanks_a.csv" "$WORK/blanks_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "--blanks: NA != empty" || return 1
}

test_ED12_trailing_newline() {
    local A="$WORK/ed12_a.csv" B="$WORK/ed12_b.csv"
    printf 'id,v\n1,a\n' > "$A"
    printf 'id,v\n1,a' > "$B"   # no trailing newline
    cd_run $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_OK" "$CD_EXIT" "trailing newline doesn't change semantics" || return 1
}

test_ED13_skipinitialspace() {
    local A="$WORK/ed13_a.csv" B="$WORK/ed13_b.csv"
    printf 'id, name\n1, Alice\n' > "$A"
    printf 'id, name\n1, Alice\n' > "$B"
    cd_run -S $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_OK" "$CD_EXIT" "identical with -S" || return 1
}

test_ED14_empty_strings() {
    local A="$WORK/ed14_a.csv" B="$WORK/ed14_b.csv"
    printf 'id,v\n1,\n2,x\n' > "$A"
    printf 'id,v\n1,\n2,x\n' > "$B"
    cd_run $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_OK" "$CD_EXIT" "empty cells unchanged" || return 1
}

test_ED15_schema_and_row_drift() {
    # A: id,name,age; B: id,name,age,city  (city added)  with one row also changed
    local B="$WORK/ed15_b.csv"
    printf 'id,name,age,city\n1,Alice,30,NYC\n2,Bob,26,LA\n3,Carol,40,SF\n' > "$B"
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$B"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '[Ss]chema' "$CD_STDOUT" "schema section present" || return 1
    # Schema section should precede first row marker.
    local schema_line; schema_line=$(echo "$CD_STDOUT" | grep -nE '[Ss]chema' | head -1 | cut -d: -f1)
    local marker_line; marker_line=$(echo "$CD_STDOUT" | grep -nE '^[+\-~] ' | head -1 | cut -d: -f1)
    if [[ -n "$schema_line" ]] && [[ -n "$marker_line" ]]; then
        [[ "$schema_line" -lt "$marker_line" ]] \
            || { _fail "schema section did not precede row markers"; return 1; }
    fi
}

test_ED16_empty_to_three_added() {
    cd_run $KEY_FLAG id "$WORK/header_only.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '3[^,]*added' "$CD_STDOUT" "3 added" || return 1
}

test_ED17_three_to_empty_removed() {
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/header_only.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff" || return 1
    assert_match '3[^,]*removed' "$CD_STDOUT" "3 removed" || return 1
}

test_ED18_keyonly_no_shared_data() {
    cd_run $KEY_FLAG id "$WORK/keyonly_a.csv" "$WORK/keyonly_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "schema differences cause exit diff" || return 1
    assert_match '[Ss]chema' "$CD_STDOUT" "schema section present" || return 1
}

test_ED19_all_rows_changed() {
    local A="$WORK/ed19_a.csv" B="$WORK/ed19_b.csv"
    printf 'id,v\n1,a\n2,b\n3,c\n' > "$A"
    printf 'id,v\n1,A\n2,B\n3,C\n' > "$B"
    cd_run $KEY_FLAG id "$A" "$B"
    assert_match '3[^,]*changed.*3 rows compared' "$CD_STDOUT" "all changed, none unchanged" || return 1
}

test_ED20_dup_column_names() {
    cd_run $KEY_FLAG 1 "$WORK/dup_cols.csv" "$WORK/dup_cols.csv"
    assert_no_traceback "$CD_STDERR" "no traceback on duplicate column names" || return 1
}

test_ED21_comma_in_key_name() {
    # A column whose NAME literally contains a comma. csvdiff inherits csvjoin's
    # key parser, which splits --key on ',' with no escape mechanism — the same
    # documented limitation csvjoin (the two-input template) has. Referencing
    # such a column as a key is therefore unsupported by design, not a defect.
    # The contract we assert is a *clean* failure: a usage error (exit 2) with
    # no Python traceback.
    local A="$WORK/ed21_a.csv" B="$WORK/ed21_b.csv"
    printf '"last,first",age\nAlice,30\nBob,25\n' > "$A"
    cp "$A" "$B"
    cd_run $KEY_FLAG 'last,first' "$A" "$B"
    assert_eq "$EXIT_USAGE" "$CD_EXIT" "clean usage error for comma-in-key-name (csvkit-wide limitation)" || return 1
    assert_no_traceback "$CD_STDERR" "no traceback on comma-in-key-name" || return 1
}

# --- PERFORMANCE ------------------------------------------------------------

# Wall-clock budget for csvdiff invocation. Uses `time` builtin via subshell.
time_csvdiff_seconds() {
    local t0 t1
    t0=$(now_ms)
    "$CSVDIFF" "$@" >/dev/null 2>&1
    t1=$(now_ms)
    printf '%s' "$(( (t1 - t0) / 1000 ))"
}

test_P01_small_1k() {
    gen_perf_pair "$WORK/p1k_a.csv" "$WORK/p1k_b.csv" 1000 5 1
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/p1k_a.csv" "$WORK/p1k_b.csv")
    [[ "$secs" -le 5 ]] || { _fail "1k rows took ${secs}s (>5s budget)"; return 1; }
}

test_P02_medium_10k() {
    gen_perf_pair "$WORK/p10k_a.csv" "$WORK/p10k_b.csv" 10000 5 1
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/p10k_a.csv" "$WORK/p10k_b.csv")
    [[ "$secs" -le 15 ]] || { _fail "10k rows took ${secs}s (>15s budget)"; return 1; }
}

test_P03_large_100k() {
    gen_perf_pair "$WORK/p100k_a.csv" "$WORK/p100k_b.csv" 100000 5 1
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/p100k_a.csv" "$WORK/p100k_b.csv")
    [[ "$secs" -le 120 ]] || { _fail "100k rows took ${secs}s (>120s budget)"; return 1; }
}

test_P04_wide_10k_x_50() {
    gen_perf_pair "$WORK/pwide_a.csv" "$WORK/pwide_b.csv" 10000 50 1
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/pwide_a.csv" "$WORK/pwide_b.csv")
    [[ "$secs" -le 60 ]] || { _fail "10k x 50 took ${secs}s (>60s budget)"; return 1; }
}

test_P05_identical_large() {
    gen_perf_pair "$WORK/pid_a.csv" "$WORK/pid_a.csv" 50000 5 0
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/pid_a.csv" "$WORK/pid_a.csv")
    [[ "$secs" -le 60 ]] || { _fail "50k identical took ${secs}s (>60s budget)"; return 1; }
}

test_P06_worst_case() {
    # Empty header-only A vs 50k row B → everything added.
    gen_perf_pair "$WORK/pwc_a.csv" "$WORK/pwc_b.csv" 50000 5 0
    gen_header_only "$WORK/pwc_a.csv"
    # Re-create header to match B's schema for a clean "all added"
    printf 'id' > "$WORK/pwc_a.csv"
    for j in 1 2 3 4; do printf ',col%d' "$j" >> "$WORK/pwc_a.csv"; done
    printf '\n' >> "$WORK/pwc_a.csv"
    local secs; secs=$(time_csvdiff_seconds $KEY_FLAG id "$WORK/pwc_a.csv" "$WORK/pwc_b.csv")
    [[ "$secs" -le 60 ]] || { _fail "worst-case 50k all-added took ${secs}s (>60s budget)"; return 1; }
}

test_P07_timing_stability() {
    # Run 5 times; flag flaky if max/min > 3x (loose: very forgiving on local hw)
    gen_perf_pair "$WORK/ps_a.csv" "$WORK/ps_b.csv" 5000 5 1
    local i ms tmin=99999999 tmax=0
    for i in 1 2 3 4 5; do
        local t0 t1
        t0=$(now_ms)
        "$CSVDIFF" $KEY_FLAG id "$WORK/ps_a.csv" "$WORK/ps_b.csv" >/dev/null 2>&1
        t1=$(now_ms)
        ms=$((t1 - t0))
        (( ms < tmin )) && tmin=$ms
        (( ms > tmax )) && tmax=$ms
    done
    if (( tmin == 0 )); then tmin=1; fi
    local ratio_x10=$(( (tmax * 10) / tmin ))
    [[ $ratio_x10 -le 30 ]] || { _fail "timing var ${tmin}ms..${tmax}ms ratio=${ratio_x10}/10"; return 1; }
}

test_P08_output_stability() {
    cd_run $KEY_FLAG id "$WORK/p10k_a.csv" "$WORK/p10k_b.csv"
    local out1="$CD_STDOUT"
    cd_run $KEY_FLAG id "$WORK/p10k_a.csv" "$WORK/p10k_b.csv"
    assert_eq "$out1" "$CD_STDOUT" "byte-identical output across two runs (10k)" || return 1
}

# --- INHERITED --------------------------------------------------------------

test_I01_version() { cd_run -V; assert_eq "0" "$CD_EXIT" "-V exit 0" || return 1; }
test_I02_help()    { cd_run -h; assert_eq "0" "$CD_EXIT" "-h exit 0" || return 1; }

test_I03_delimiter() {
    cd_run -d ';' $KEY_FLAG id "$WORK/semi_a.csv" "$WORK/semi_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on identical semi-delim" || return 1
}

test_I04_tabs() {
    cd_run -t $KEY_FLAG id "$WORK/tsv_a.tsv" "$WORK/tsv_a.tsv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on identical TSV" || return 1
}

test_I05_quotechar() {
    local A="$WORK/i05_a.csv" B="$WORK/i05_b.csv"
    printf "id,v\n1,'hello, world'\n" > "$A"; cp "$A" "$B"
    cd_run -q "'" $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with custom quote char" || return 1
}

test_I06_quoting_mode() {
    cd_run -u 1 $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -u 1" || return 1
}

test_I07_no_doublequote() {
    cd_run -b $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -b" || return 1
}

test_I08_escapechar() {
    cd_run -p '\' $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -p '\\'" || return 1
}

test_I09_maxfieldsize() {
    cd_run -z 200000 $KEY_FLAG id "$WORK/long_a.csv" "$WORK/long_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on long-cell with -z bump" || return 1
}

test_I10_encoding() {
    cd_run -e latin1 $KEY_FLAG id "$WORK/latin1_a.csv" "$WORK/latin1_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 on latin1 identical" || return 1
}

test_I11_locale() {
    cd_run -L en_US $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -L" || return 1
}

test_I12_skipinitialspace() {
    local A="$WORK/i12.csv"
    printf 'id, name\n1, Alice\n' > "$A"
    cd_run -S $KEY_FLAG id "$A" "$A"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -S" || return 1
}

test_I13_blanks_and_null_value() {
    local A="$WORK/i13_a.csv" B="$WORK/i13_b.csv"
    printf 'id,v\n1,N/A\n2,foo\n' > "$A"
    printf 'id,v\n1,\n2,foo\n' > "$B"
    # Default: N/A → null → equal
    cd_run $KEY_FLAG id "$A" "$B"
    assert_eq "$EXIT_OK" "$CD_EXIT" "N/A and empty both null" || return 1
}

test_I14_date_format() {
    cd_run --date-format '%m/%d/%Y' $KEY_FLAG id "$WORK/dates_a.csv" "$WORK/dates_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with --date-format" || return 1
}

test_I15_no_leading_zeroes() {
    cd_run --no-leading-zeroes $KEY_FLAG name "$WORK/lz_a.csv" "$WORK/lz_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with --no-leading-zeroes (identical)" || return 1
}

test_I16_no_header_row() {
    cd_run -H $KEY_FLAG 1 "$WORK/noh_a.csv" "$WORK/noh_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -H identical" || return 1
}

test_I17_skip_lines() {
    cd_run -K 2 $KEY_FLAG id "$WORK/skip_a.csv" "$WORK/skip_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -K 2 identical" || return 1
}

test_I18_verbose_traceback() {
    # With -v, a forced runtime error should produce a Python traceback;
    # without -v, it shouldn't. Trigger via missing file (a runtime, not arg, error).
    cd_run $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/no_such_file.csv"
    assert_no_traceback "$CD_STDERR" "no traceback without -v" || return 1
    cd_run -v $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/no_such_file.csv"
    [[ "$CD_STDERR" == *"Traceback"* ]] || { _fail "expected Traceback with -v"; return 1; }
}

test_I19_linenumbers() {
    # -l/--linenumbers is a CSV *writer* kwarg; csvdiff renders its own
    # (non-CSV) output and never calls to_csv, so -l is a no-op here. Assert it
    # is accepted and harmless rather than expecting a line_number column.
    cd_run -l $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv"
    assert_eq "$EXIT_DIFF" "$CD_EXIT" "exit diff with -l (no-op for csvdiff)" || return 1
    assert_no_traceback "$CD_STDERR" "no traceback with -l" || return 1
}

test_I20_add_bom() {
    local out="$WORK/i20_out.csv"
    "$CSVDIFF" --add-bom $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_b.csv" > "$out" 2>/dev/null || true
    # The base class writes the BOM before main() for any tool, regardless of
    # output format. First three bytes should be EF BB BF.
    local first3
    first3=$(head -c 3 "$out" | od -An -tx1 | tr -d ' \n')
    if [[ "$first3" != "efbbbf" ]]; then
        _fail "expected UTF-8 BOM (EF BB BF) at start of file; got '$first3'"
        return 1
    fi
}

test_I21_zero_based() {
    cd_run --zero $KEY_FLAG 0 "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with --zero -k 0" || return 1
}

test_I22_no_inference() {
    [[ -n "$NOINF_FLAG" ]] || return 0
    cd_run "$NOINF_FLAG" $KEY_FLAG id "$WORK/basic_a.csv" "$WORK/basic_a.csv"
    assert_eq "$EXIT_OK" "$CD_EXIT" "exit 0 with -I on identical" || return 1
}

# ----------------------------------------------------------------------------
# 8. Section dispatcher
# ----------------------------------------------------------------------------

section_header() {
    printf '\n%s%s%s\n' "$C_BOLD" "$1" "$C_OFF"
}

run_happy() {
    section_header "[happy]"
    run_test happy/01_identical                  "two identical files compare equal"     test_H01_identical
    run_test happy/02_no_key_identical           "no-key default behavior — identical"   test_H02_no_key_identical
    run_test happy/03_added_row                  "added row classified + marker"         test_H03_added_row
    run_test happy/04_removed_row                "removed row classified + marker"       test_H04_removed_row
    run_test happy/05_changed_field              "per-field change with before→after"    test_H05_changed_field
    run_test happy/06_mixed_counts               "mixed counts add+rm+chg+unchanged"     test_H06_mixed_counts
    run_test happy/07_unchanged_fields_omitted   "unchanged fields not reported"         test_H07_unchanged_fields_omitted
    run_test happy/08_no_row_section_when_equal  "no row section when identical"         test_H08_identical_no_row_section
    run_test happy/09a_no_key_positional         "no-key default = positional (if so)"   test_H09a_no_key_positional
    run_test happy/09b_no_key_require            "no-key default = require-key (if so)"  test_H09b_no_key_require
    run_test happy/10_help_mentions_memory       "epilog mentions memory tradeoff"       test_H10_help_mentions_memory
    run_test happy/11_determinism                "two runs produce identical stdout"     test_H11_determinism
}

run_alternate() {
    section_header "[alternate]"
    run_test alternate/01_composite_key          "composite key on year,quarter"         test_A01_composite_key
    run_test alternate/02_three_col_composite    "3-column composite key"                test_A02_three_col_composite
    run_test alternate/03_key_by_index           "key by 1-based column index"           test_A03_key_by_index
    run_test alternate/04_jsonl_format           "jsonl output is valid and structured"  test_A04_json_format
    run_test alternate/04b_jsonl_identical       "jsonl output on identical inputs"      test_A04b_json_identical
    run_test alternate/05_summary_format         "summary output is headline-only counts" test_A05_summary_format
    run_test alternate/05b_summary_identical     "summary is one headline line when equal" test_A05b_summary_identical_headline_only
    run_test alternate/06_stdin_second           "second input from STDIN"               test_A06_stdin_for_second
    run_test alternate/07_stdin_first            "first input from STDIN"                test_A07_stdin_for_first
    run_test alternate/08_schema_added_col       "added column reported as schema diff"  test_A08_schema_added_col
    run_test alternate/09_schema_removed_col     "removed column reported as schema diff" test_A09_schema_removed_col
    run_test alternate/10_schema_reordered       "reordered columns surface separately"  test_A10_schema_reordered
    run_test alternate/11_resorted               "re-sorted file: no row diffs (keyed)"  test_A11_resorted
    run_test alternate/12_no_inference_string    "-I: 30 ≠ 30.0"                         test_A12_no_inference_string
    run_test alternate/13_typed_equal            "typed: 30 == 30.0"                     test_A13_typed_equal
    run_test alternate/14_tabs                   "-t works on TSV inputs"                test_A14_tabs
    run_test alternate/15_semi_delimiter         "-d ';' works"                           test_A15_semi_delimiter
    run_test alternate/16_latin1                 "-e latin1 works"                        test_A16_latin1_encoding
    run_test alternate/17_no_header_row          "-H works with key-by-index"             test_A17_no_header_row
    run_test alternate/18_skip_lines             "-K 2 skips comments"                    test_A18_skip_lines
}

run_error() {
    section_header "[error]"
    run_test error/01_no_input                   "no input → non-zero exit"               test_E01_no_input_tty
    run_test error/02_one_arg_piped_stdin        "one arg + piped stdin = valid diff"     test_E02_one_arg_with_piped_stdin
    run_test error/03_three_args                 "three positionals → usage error"        test_E03_three_args
    run_test error/04_missing_file               "missing file → clean error"             test_E04_missing_file
    run_test error/05_unreadable_file            "unreadable file → clean error"          test_E05_unreadable_file
    run_test error/06_bad_key_name               "bad --key name → usage error"           test_E06_bad_key_name
    run_test error/07_bad_key_index              "bad --key index → usage error"          test_E07_bad_key_index
    run_test error/08_dup_keys_first             "duplicate keys in file A (per policy)"  test_E08_dup_keys_first
    run_test error/09_dup_keys_second            "duplicate keys in file B (per policy)"  test_E09_dup_keys_second
    run_test error/10_help                       "-h/--help → usage on stdout"            test_E10_help
    run_test error/11_version                    "-V/--version → version on stdout"       test_E11_version
    run_test error/12_invalid_format             "--format yaml → usage error"            test_E12_invalid_format_value
    run_test error/13_t_overrides_d              "-t overrides -d, doesn't error"         test_E13_t_overrides_d
    run_test error/14_stdin_ignored_w_2_files    "stdin ignored when 2 file args given"   test_E14_stdin_ignored_with_two_files
    run_test error/15_empty_key_arg              "--key '' = no key (csvjoin-consistent)" test_E15_empty_key_arg
}

run_edge() {
    section_header "[edge]"
    run_test edge/01_empty_files                 "both 0-byte files: no traceback"        test_ED01_empty_files
    run_test edge/02_header_only                 "both header-only: 0 diffs"              test_ED02_header_only
    run_test edge/03_single_row_change           "1-row file with 1 change"               test_ED03_single_row_change
    run_test edge/04_lf_vs_crlf                  "LF vs CRLF: 0 diffs"                    test_ED04_lf_vs_crlf
    run_test edge/05_bom                         "UTF-8 BOM transparent"                  test_ED05_bom
    run_test edge/06_unicode                     "CJK + emoji round-trip"                 test_ED06_unicode
    run_test edge/07_embedded_newline            "newline in quoted cell"                 test_ED07_embedded_newline
    run_test edge/08_long_cell                   "100KB cell with -z bump"                test_ED08_long_cell
    run_test edge/09_leading_zeros               "007 ≠ 7 with --no-leading-zeroes"       test_ED09_leading_zeros
    run_test edge/10_date_format                 "--date-format MM/DD/YYYY"               test_ED10_date_format
    run_test edge/11_blanks                      "blanks vs --blanks toggle"              test_ED11_blanks
    run_test edge/12_trailing_newline            "trailing newline ignored"               test_ED12_trailing_newline
    run_test edge/13_skipinitialspace            "-S strips leading spaces"               test_ED13_skipinitialspace
    run_test edge/14_empty_strings               "empty cells equal empty cells"          test_ED14_empty_strings
    run_test edge/15_schema_and_row_drift        "schema section precedes row markers"    test_ED15_schema_and_row_drift
    run_test edge/16_empty_to_three_added        "header-only vs 3 rows → 3 added"        test_ED16_empty_to_three_added
    run_test edge/17_three_to_empty_removed      "3 rows vs header-only → 3 removed"      test_ED17_three_to_empty_removed
    run_test edge/18_keyonly_no_shared_data      "only key column shared → schema only"   test_ED18_keyonly_no_shared_data
    run_test edge/19_all_rows_changed            "all rows changed, none unchanged"       test_ED19_all_rows_changed
    run_test edge/20_dup_column_names            "duplicate column names: no traceback"   test_ED20_dup_column_names
    run_test edge/21_comma_in_key_name           "comma-in-key-name → clean usage error" test_ED21_comma_in_key_name
}

run_perf() {
    [[ $SKIP_PERF -eq 1 ]] && { section_header "[perf]"; echo "  skipped via --skip-perf"; return; }
    section_header "[perf]"
    run_test perf/01_small_1k                    "1k rows × 5 cols, 1% diff < 5s"         test_P01_small_1k 1
    run_test perf/02_medium_10k                  "10k rows × 5 cols, 1% diff < 15s"       test_P02_medium_10k 1
    run_test perf/03_large_100k                  "100k rows × 5 cols, 1% diff < 120s"     test_P03_large_100k 1
    run_test perf/04_wide_10kx50                 "10k × 50 cols < 60s"                    test_P04_wide_10k_x_50 1
    run_test perf/05_identical_large             "50k identical files < 60s"              test_P05_identical_large 1
    run_test perf/06_worst_case                  "50k all-added < 60s"                    test_P06_worst_case 1
    run_test perf/07_timing_stability            "5 runs: min/max ratio ≤ 3x"             test_P07_timing_stability 1
    run_test perf/08_output_stability            "byte-identical stdout across 2 runs"    test_P08_output_stability 1
}

run_inherited() {
    section_header "[inherited]"
    run_test inherited/01_version                "-V"                                       test_I01_version
    run_test inherited/02_help                   "-h"                                       test_I02_help
    run_test inherited/03_delimiter              "-d ';'"                                   test_I03_delimiter
    run_test inherited/04_tabs                   "-t"                                       test_I04_tabs
    run_test inherited/05_quotechar              "-q '\\''"                                 test_I05_quotechar
    run_test inherited/06_quoting_mode           "-u 1"                                     test_I06_quoting_mode
    run_test inherited/07_no_doublequote         "-b"                                       test_I07_no_doublequote
    run_test inherited/08_escapechar             "-p"                                       test_I08_escapechar
    run_test inherited/09_maxfieldsize           "-z"                                       test_I09_maxfieldsize
    run_test inherited/10_encoding               "-e latin1"                                test_I10_encoding
    run_test inherited/11_locale                 "-L en_US"                                 test_I11_locale
    run_test inherited/12_skipinitialspace       "-S"                                       test_I12_skipinitialspace
    run_test inherited/13_blanks_null            "--blanks / --null-value"                  test_I13_blanks_and_null_value
    run_test inherited/14_date_format            "--date-format"                            test_I14_date_format
    run_test inherited/15_no_leading_zeroes      "--no-leading-zeroes"                      test_I15_no_leading_zeroes
    run_test inherited/16_no_header_row          "-H"                                       test_I16_no_header_row
    run_test inherited/17_skip_lines             "-K"                                       test_I17_skip_lines
    run_test inherited/18_verbose_traceback      "-v toggles traceback printing"            test_I18_verbose_traceback
    run_test inherited/19_linenumbers            "-l is an accepted no-op"                  test_I19_linenumbers
    run_test inherited/20_add_bom                "--add-bom emits EF BB BF"                 test_I20_add_bom
    run_test inherited/21_zero_based             "--zero with -k 0"                         test_I21_zero_based
    run_test inherited/22_no_inference           "-I / --no-inference"                      test_I22_no_inference
}

# ----------------------------------------------------------------------------
# 9. Reporting
# ----------------------------------------------------------------------------

emit_summary() {
    local total=${#RES_NAMES[@]}
    local pass=0 fail=0 flaky=0 skipped=0
    local i
    for ((i=0; i<total; i++)); do
        case "${RES_STATUS[$i]}" in
            PASS)    pass=$((pass+1));;
            FAIL)    fail=$((fail+1));;
            FLAKY)   flaky=$((flaky+1));;
            SKIPPED) skipped=$((skipped+1));;
        esac
    done

    printf '\n%s================================================================%s\n' "$C_BOLD" "$C_OFF"
    printf '%sSummary%s\n' "$C_BOLD" "$C_OFF"
    printf '  csvdiff:        %s\n' "$CSVDIFF"
    printf '  probe:          KEY_FLAG=%s  FMT_FLAG=%s  NOINF_FLAG=%s\n' \
        "${KEY_FLAG:-<none>}" "${FMT_FLAG:-<none>}" "${NOINF_FLAG:-<none>}"
    printf '                  exit codes: OK=%s DIFF=%s USAGE=%s\n' "$EXIT_OK" "$EXIT_DIFF" "$EXIT_USAGE"
    printf '                  no-key policy: %s    dup-key policy: %s\n' "$NO_KEY_POLICY" "$DUP_POLICY"
    printf '  total: %d   %sPASS%s: %d   %sFAIL%s: %d   %sFLAKY%s: %d   %sSKIP%s: %d\n' \
        "$total" \
        "$C_GREEN" "$C_OFF" "$pass" \
        "$C_RED" "$C_OFF" "$fail" \
        "$C_YELLOW" "$C_OFF" "$flaky" \
        "$C_DIM" "$C_OFF" "$skipped"

    if (( fail + flaky + skipped > 0 )); then
        printf '\n%sDetails:%s\n' "$C_BOLD" "$C_OFF"
        for ((i=0; i<total; i++)); do
            case "${RES_STATUS[$i]}" in
                FAIL|FLAKY|SKIPPED)
                    printf '  [%s] %s\n        %s\n' \
                        "$(color_status "${RES_STATUS[$i]}")" \
                        "${RES_NAMES[$i]}" \
                        "${RES_DETAIL[$i]:-(none)}"
                    ;;
            esac
        done
    fi
    printf '%s================================================================%s\n' "$C_BOLD" "$C_OFF"

    if [[ -n "$REPORT_JSON" ]]; then
        emit_report_json "$REPORT_JSON"
        printf '  json report:  %s\n' "$REPORT_JSON"
    fi
    if [[ -n "$REPORT_JUNIT" ]]; then
        emit_report_junit "$REPORT_JUNIT"
        printf '  junit report: %s\n' "$REPORT_JUNIT"
    fi
    if [[ -n "$REPORT_HTML" ]]; then
        emit_report_html "$REPORT_HTML"
        printf '  html report:  %s\n' "$REPORT_HTML"
    fi

    # Exit code
    if (( fail > 0 )); then return 1; fi
    if (( STRICT == 1 )) && (( flaky + skipped > 0 )); then return 1; fi
    return 0
}

emit_report_json() {
    local path="$1"
    local total=${#RES_NAMES[@]}
    {
        printf '{\n  "csvdiff": "%s",\n' "$CSVDIFF"
        printf '  "probe": {"key_flag":"%s","format_flag":"%s","noinf_flag":"%s","exit_ok":%s,"exit_diff":%s,"exit_usage":%s,"no_key_policy":"%s","dup_policy":"%s"},\n' \
            "$KEY_FLAG" "$FMT_FLAG" "$NOINF_FLAG" "$EXIT_OK" "$EXIT_DIFF" "$EXIT_USAGE" "$NO_KEY_POLICY" "$DUP_POLICY"
        printf '  "tests": [\n'
        local i
        for ((i=0; i<total; i++)); do
            local sep=","
            (( i == total - 1 )) && sep=""
            local id_j; id_j=$(printf '%s' "${RES_NAMES[$i]}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
            local desc_j; desc_j=$(printf '%s' "${RES_DESCS[$i]}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
            local detail; detail=$(printf '%s' "${RES_DETAIL[$i]}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
            printf '    {"id":%s,"desc":%s,"status":"%s","median_ms":%s,"detail":%s}%s\n' \
                "$id_j" "$desc_j" "${RES_STATUS[$i]}" "${RES_MEDIAN_MS[$i]}" "$detail" "$sep"
        done
        printf '  ]\n}\n'
    } > "$path"
}

_html_escape() {
    python3 -c 'import sys, html; sys.stdout.write(html.escape(sys.stdin.read()))'
}

emit_report_html() {
    local path="$1"
    local total=${#RES_NAMES[@]}
    local pass=0 fail=0 flaky=0 skipped=0
    local i
    for ((i=0; i<total; i++)); do
        case "${RES_STATUS[$i]}" in
            PASS)    pass=$((pass+1));;
            FAIL)    fail=$((fail+1));;
            FLAKY)   flaky=$((flaky+1));;
            SKIPPED) skipped=$((skipped+1));;
        esac
    done

    local timestamp; timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local cdiff_esc; cdiff_esc=$(printf '%s' "$CSVDIFF" | _html_escape)
    local mem_yn; if [[ $HELP_HAS_MEMORY_NOTE -eq 1 ]]; then mem_yn="yes"; else mem_yn="no"; fi

    {
        cat <<'HTMLHEAD'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>csvdiff test harness report</title>
<style>
:root {
  --bg:#0b1020; --panel:#131a30; --border:#2a3358; --fg:#e5e7eb; --muted:#9ca3af;
  --green:#22c55e; --red:#ef4444; --yellow:#eab308; --blue:#60a5fa;
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
main { max-width: 1200px; margin: 0 auto; padding: 28px 40px 80px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; transition: border-color 0.15s;
}
.card h3 {
  margin: 0 0 6px; font-size: 10.5px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
}
.card .num { font-size: 38px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
.card.pass  .num { color: var(--green); }
.card.fail  .num { color: var(--red); }
.card.flaky .num { color: var(--yellow); }
.card.skip  .num { color: var(--muted); }
.card.fail { border-color: rgba(239,68,68,0.4); }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 22px; }
.panel > h2 {
  margin: 0; padding: 14px 20px; font-size: 11.5px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  border-bottom: 1px solid var(--border);
}
.panel > .body { padding: 16px 20px; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 18px; font-family: var(--mono); font-size: 12.5px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
th { color: var(--muted); font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; }
td.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }
.pill {
  display: inline-block; padding: 2px 9px; border-radius: 99px;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; font-family: var(--mono);
}
.pill.pass  { background: rgba(34,197,94,0.16); color: var(--green); }
.pill.fail  { background: rgba(239,68,68,0.16); color: var(--red); }
.pill.flaky { background: rgba(234,179,8,0.18); color: var(--yellow); }
.pill.skip  { background: rgba(156,163,175,0.18); color: var(--muted); }
details.test {
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  margin: 8px 0; overflow: hidden;
}
details.test > summary {
  cursor: pointer; padding: 10px 16px; display: flex; gap: 14px; align-items: center;
  list-style: none;
}
details.test > summary::-webkit-details-marker { display: none; }
details.test > summary::before { content: '▸'; color: var(--muted); transition: transform 0.15s; font-size: 11px; }
details.test[open] > summary::before { transform: rotate(90deg); }
details.test.fail  { border-color: rgba(239,68,68,0.35); }
details.test.flaky { border-color: rgba(234,179,8,0.35); }
details.test .name { flex: 1; font-family: var(--mono); font-size: 12.5px; }
details.test .desc { color: var(--muted); font-size: 12px; }
details.test .time {
  color: var(--muted); font-family: var(--mono); font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.detail { padding: 4px 18px 18px 36px; font-size: 12.5px; }
.detail h4 {
  margin: 14px 0 6px; font-size: 10.5px; font-weight: 600; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.detail h4:first-child { margin-top: 6px; }
.detail .msg {
  color: #fda4af; font-family: var(--mono); font-size: 12.5px;
  white-space: pre-wrap; word-break: break-word;
}
.detail pre {
  background: #06091a; border: 1px solid var(--border); border-radius: 6px;
  padding: 10px 12px; margin: 0; overflow: auto; max-height: 280px;
  font-family: var(--mono); font-size: 12px; line-height: 1.55; color: #cbd5e1;
}
.detail pre.empty { color: var(--muted); font-style: italic; }
.section-title {
  margin: 36px 0 12px; font-size: 11.5px; font-weight: 600; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.filters { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }
.filter {
  background: var(--panel); border: 1px solid var(--border); color: var(--fg);
  padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer;
  font-family: inherit;
}
.filter:hover { border-color: #44508c; }
.filter.active { background: #1c2549; border-color: var(--blue); color: #cfd9ff; }
.filter .count { color: var(--muted); margin-left: 8px; font-variant-numeric: tabular-nums; }
.filter.active .count { color: #aab9e8; }
.hidden { display: none !important; }
.note { color: var(--muted); font-size: 12px; margin-top: 6px; }
</style>
</head>
<body>
HTMLHEAD

        printf '<header><h1>csvdiff test harness report</h1><div class="meta">'
        printf '<div>Run: %s</div>' "$timestamp"
        printf '<div>csvdiff: %s</div>' "$cdiff_esc"
        printf '<div>retries: %s (functional), %s (perf)</div>' "$RETRIES_FUNC" "$RETRIES_PERF"
        printf '</div></header>\n'

        printf '<main>\n'

        # Summary cards
        printf '<section class="cards">'
        printf '<div class="card pass"><h3>PASS</h3><div class="num">%d</div></div>' "$pass"
        printf '<div class="card fail"><h3>FAIL</h3><div class="num">%d</div></div>' "$fail"
        printf '<div class="card flaky"><h3>FLAKY</h3><div class="num">%d</div></div>' "$flaky"
        printf '<div class="card skip"><h3>SKIPPED</h3><div class="num">%d</div></div>' "$skipped"
        printf '</section>\n'

        # Probe panel
        printf '<section class="panel"><h2>Probe</h2><div class="body"><dl class="kv">'
        printf '<dt>Key flag</dt><dd>%s</dd>' "$(printf '%s' "${KEY_FLAG:-<none>}" | _html_escape)"
        printf '<dt>Format flag</dt><dd>%s</dd>' "$(printf '%s' "${FMT_FLAG:-<none>}" | _html_escape)"
        printf '<dt>No-inference flag</dt><dd>%s</dd>' "$(printf '%s' "${NOINF_FLAG:-<none>}" | _html_escape)"
        printf '<dt>Exit codes</dt><dd>OK=%s · DIFF=%s · USAGE=%s</dd>' "$EXIT_OK" "$EXIT_DIFF" "$EXIT_USAGE"
        printf '<dt>No-key policy</dt><dd>%s</dd>' "$NO_KEY_POLICY"
        printf '<dt>Duplicate-key policy</dt><dd>%s</dd>' "$DUP_POLICY"
        printf '<dt>Memory note in --help</dt><dd>%s</dd>' "$mem_yn"
        printf '</dl></div></section>\n'

        # Issues panel — failing tests with full failure context (open by default)
        if (( fail + flaky > 0 )); then
            printf '<h3 class="section-title">Issues — %d failing test(s)</h3>\n' "$((fail + flaky))"
            printf '<div class="note">Each failing test below shows the failure message, '
            printf 'the exact command run, exit code, and captured stdout / stderr from the failing invocation.</div>\n'
            for ((i=0; i<total; i++)); do
                local status="${RES_STATUS[$i]}"
                [[ "$status" == "FAIL" ]] || [[ "$status" == "FLAKY" ]] || continue
                local lc; lc=$(printf '%s' "$status" | tr 'A-Z' 'a-z')
                local name_esc; name_esc=$(printf '%s' "${RES_NAMES[$i]}" | _html_escape)
                local desc_esc; desc_esc=$(printf '%s' "${RES_DESCS[$i]}" | _html_escape)
                local msg_esc;  msg_esc=$(printf '%s' "${RES_DETAIL[$i]}" | _html_escape)
                local cmd_esc;  cmd_esc=$(printf '%s' "${RES_FAIL_CMD[$i]}" | _html_escape)
                local out_esc;  out_esc=$(printf '%s' "${RES_FAIL_STDOUT[$i]}" | _html_escape)
                local err_esc;  err_esc=$(printf '%s' "${RES_FAIL_STDERR[$i]}" | _html_escape)
                local ec="${RES_FAIL_EXIT[$i]}"

                printf '<details class="test %s" open>' "$lc"
                printf '<summary><span class="pill %s">%s</span>' "$lc" "$status"
                printf '<span class="name">%s</span>' "$name_esc"
                printf '<span class="desc">%s</span>' "$desc_esc"
                printf '<span class="time">%sms</span></summary>' "${RES_MEDIAN_MS[$i]}"

                printf '<div class="detail">'
                printf '<h4>Why it failed</h4><div class="msg">%s</div>' "$msg_esc"
                if [[ -n "$cmd_esc" ]]; then
                    printf '<h4>Command</h4><pre>%s</pre>' "$cmd_esc"
                fi
                if [[ -n "$ec" ]]; then
                    printf '<h4>Exit code</h4><pre>%s</pre>' "$ec"
                fi
                printf '<h4>Stdout (captured)</h4>'
                if [[ -n "$out_esc" ]]; then
                    printf '<pre>%s</pre>' "$out_esc"
                else
                    printf '<pre class="empty">(empty)</pre>'
                fi
                printf '<h4>Stderr (captured)</h4>'
                if [[ -n "$err_esc" ]]; then
                    printf '<pre>%s</pre>' "$err_esc"
                else
                    printf '<pre class="empty">(empty)</pre>'
                fi
                printf '</div></details>\n'
            done
        fi

        # Per-category breakdown
        printf '<section class="panel"><h2>By category</h2><div class="body">'
        printf '<table><tr><th>Category</th><th>Total</th><th>Pass</th><th>Fail</th><th>Flaky</th><th>Skipped</th></tr>'
        local cats="happy alternate error edge inherited perf"
        local cat
        for cat in $cats; do
            local ctotal=0 cpass=0 cfail=0 cflaky=0 cskip=0
            for ((i=0; i<total; i++)); do
                [[ "${RES_NAMES[$i]}" == "$cat/"* ]] || continue
                ctotal=$((ctotal+1))
                case "${RES_STATUS[$i]}" in
                    PASS)    cpass=$((cpass+1));;
                    FAIL)    cfail=$((cfail+1));;
                    FLAKY)   cflaky=$((cflaky+1));;
                    SKIPPED) cskip=$((cskip+1));;
                esac
            done
            printf '<tr><td>%s</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td></tr>' \
                "$cat" "$ctotal" "$cpass" "$cfail" "$cflaky" "$cskip"
        done
        printf '</table></div></section>\n'

        # All tests with status filters
        printf '<h3 class="section-title">All tests (%d)</h3>\n' "$total"
        printf '<div class="filters">'
        printf '<button class="filter active" data-status="all">All <span class="count">%d</span></button>' "$total"
        printf '<button class="filter" data-status="pass">Pass <span class="count">%d</span></button>' "$pass"
        printf '<button class="filter" data-status="fail">Fail <span class="count">%d</span></button>' "$fail"
        printf '<button class="filter" data-status="flaky">Flaky <span class="count">%d</span></button>' "$flaky"
        printf '<button class="filter" data-status="skip">Skipped <span class="count">%d</span></button>' "$skipped"
        printf '</div>\n'
        printf '<div id="tests">'
        for ((i=0; i<total; i++)); do
            local status="${RES_STATUS[$i]}"
            local lc; lc=$(printf '%s' "$status" | tr 'A-Z' 'a-z')
            [[ "$lc" == "skipped" ]] && lc="skip"
            local name_esc; name_esc=$(printf '%s' "${RES_NAMES[$i]}" | _html_escape)
            local desc_esc; desc_esc=$(printf '%s' "${RES_DESCS[$i]}" | _html_escape)
            local msg_esc;  msg_esc=$(printf '%s' "${RES_DETAIL[$i]}" | _html_escape)

            printf '<details class="test %s" data-status="%s">' "$lc" "$lc"
            printf '<summary><span class="pill %s">%s</span>' "$lc" "$status"
            printf '<span class="name">%s</span>' "$name_esc"
            printf '<span class="desc">%s</span>' "$desc_esc"
            printf '<span class="time">%sms</span></summary>' "${RES_MEDIAN_MS[$i]}"
            if [[ "$status" != "PASS" ]] && [[ -n "$msg_esc" ]]; then
                printf '<div class="detail"><div class="msg">%s</div></div>' "$msg_esc"
            fi
            printf '</details>\n'
        done
        printf '</div>\n'

        printf '</main>\n'

        cat <<'JS'
<script>
document.querySelectorAll('.filter').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const want = btn.dataset.status;
        document.querySelectorAll('#tests > details.test').forEach(d => {
            if (want === 'all' || d.dataset.status === want) {
                d.classList.remove('hidden');
            } else {
                d.classList.add('hidden');
            }
        });
    });
});
</script>
</body></html>
JS
    } > "$path"
}

emit_report_junit() {
    local path="$1"
    local total=${#RES_NAMES[@]}
    local failures=0 skipped=0 i
    for ((i=0; i<total; i++)); do
        case "${RES_STATUS[$i]}" in
            FAIL|FLAKY) failures=$((failures+1));;
            SKIPPED)    skipped=$((skipped+1));;
        esac
    done
    {
        printf '<?xml version="1.0" encoding="UTF-8"?>\n'
        printf '<testsuite name="csvdiff" tests="%s" failures="%s" skipped="%s">\n' \
            "$total" "$failures" "$skipped"
        for ((i=0; i<total; i++)); do
            local id="${RES_NAMES[$i]}"
            local status="${RES_STATUS[$i]}"
            local time_s; time_s=$(awk -v ms="${RES_MEDIAN_MS[$i]}" 'BEGIN{printf "%.3f", ms/1000}')
            local detail_escaped
            detail_escaped=$(printf '%s' "${RES_DETAIL[$i]}" | python3 -c '
import sys, html
print(html.escape(sys.stdin.read()))')
            case "$status" in
                PASS)
                    printf '  <testcase name="%s" time="%s"/>\n' "$id" "$time_s"
                    ;;
                FAIL|FLAKY)
                    printf '  <testcase name="%s" time="%s"><failure type="%s">%s</failure></testcase>\n' \
                        "$id" "$time_s" "$status" "$detail_escaped"
                    ;;
                SKIPPED)
                    printf '  <testcase name="%s" time="%s"><skipped>%s</skipped></testcase>\n' \
                        "$id" "$time_s" "$detail_escaped"
                    ;;
            esac
        done
        printf '</testsuite>\n'
    } > "$path"
}

# ----------------------------------------------------------------------------
# 10. Main
# ----------------------------------------------------------------------------

main() {
    printf '%scsvdiff test harness%s\n' "$C_BOLD" "$C_OFF"
    printf '  csvdiff: %s\n' "$CSVDIFF"
    printf '  work:    %s\n' "$WORK"

    generate_all_fixtures
    probe_cli

    if (( PROBE_OK == 0 )); then
        echo "Warning: probe was incomplete. Dependent tests may FAIL/SKIP."
    fi

    printf '\n[probe] key=%s  format=%s  no-inference=%s\n' \
        "${KEY_FLAG:-<none>}" "${FMT_FLAG:-<none>}" "${NOINF_FLAG:-<none>}"
    printf '[probe] exit codes: OK=%s DIFF=%s USAGE=%s\n' "$EXIT_OK" "$EXIT_DIFF" "$EXIT_USAGE"
    printf '[probe] no-key default: %s    dup-key policy: %s\n' "$NO_KEY_POLICY" "$DUP_POLICY"
    printf '[probe] help mentions memory tradeoff: %s\n' \
        "$( [[ $HELP_HAS_MEMORY_NOTE -eq 1 ]] && echo yes || echo no )"

    run_happy
    run_alternate
    run_error
    run_edge
    run_inherited
    run_perf

    emit_summary
}

main "$@"
