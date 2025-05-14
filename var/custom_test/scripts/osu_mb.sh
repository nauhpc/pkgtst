#!/bin/bash
#SBATCH -N 2
#SBATCH -n 2
#SBATCH --time=4:00

function die() {
    local msg="$1"
    local -i exit="$2"
    printf 'ERROR: %s\n' "$msg" 1>&2
    exit "$exit"
}

function cleanup() {

    if [[ "$NOCLEAN" == 1 ]]; then
        printf '%s\n' 'skipping cleanup (NOCLEAN=1)' 1>&2
        return
    fi
    
    # shellcheck disable=2317
    if [[ -n "$BASEDIR" ]]; then
        # can't hurt to double-check
        if [[ "$(basename "$BASEDIR")" = osu_mb ]]; then
            rm -rf -- "$BASEDIR"
        fi
    fi
}

function setup() {
    mkdir -- "$BASEDIR" || {
        die "could not mkdir ${BASEDIR@Q}" 1
    }
    cd -- "$BASEDIR" || {
        die "could not cd into ${BASEDIR@Q}" 1
    }

    
    while IFS=: read -r module_name; do
        printf '%s\n' "loading $module_name"
        module load "$module_name"
    done <<< "$REQ_MODULES"
}

function execute() {
    srun osu_bibw > "$BIBW_LOGFILE"
    srun osu_latency > "$LATENCY_LOGFILE"
}

function evaluate() {

    bandwidth_threshold=10000 # in MB/s
    latency_threshold=2 # in microseconds
    
    # if the max bw is not at least 10,000 MB/s, then the test fails
    awk -v b="$bandwidth_threshold" '/^[0-9]+/ { if($2 >= m) { m=$2 } } END { if(m < b) { exit 1 } }' "$BIBW_LOGFILE" || {
        die "bandwidth threshold of ${bandwidth_threshold@Q} (in MB/s) not met"
    }

    # look at sizes of 16 and below, if any of them have a latency greater than 2, then the test fails
    awk -v l="$latency_threshold" '/^[0-9]+/ { if($2 <= m || !m) { m=$2 } } END { if(m > l) { exit 1 } }' "$LATENCY_LOGFILE" || {
        die "latency threshold of ${latency_threshold@Q} (in microseconds) not met"
    }

    # the output files are small, let's print them to stdout
    for logfile in "$BIBW_LOGFILE" "$LATENCY_LOGFILE"; do
        prefix="$(basename "$logfile")"
        echo
        awk -v p="$prefix" '{ print p":"$0 }' "$logfile"
    done
}

BASEDIR="${TMPDIR:-/tmp}/osu_mb"
LATENCY_LOGFILE="${BASEDIR}/latency.log"
BIBW_LOGFILE="${BASEDIR}/bibw.log"
NOCLEAN="${NOCLEAN:-0}"

if [[ -n "$1" ]]; then
    REQ_MODULES="$1"
else
    REQ_MODULES="osu-micro-benchmarks"
fi

trap cleanup EXIT

setup

execute

evaluate
