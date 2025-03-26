#!/bin/bash
#SBATCH --job-name=pkgtst_stream
#SBATCH --time=5:00
##SBATCH --chdir=/scratch/pkgtst
##SBATCH --output=/common/adm/monsoon_tests/pkgtst/stream/slurm.out
#SBATCH --exclusive

function usage() {
    printf '%b\n' "${BOLD}NAME${END}
    ${SCRIPT_NAME}

${BOLD}DESCRIPTION${END}
    Sbatch/bash wrapper for the stream program, will parse the output for acceptable values

${BOLD}OPTIONS${END}
    -h, --help    print this help message

    -r MIN_TRIAD, --min-read=MIN_TRIAD
                  minimum acceptable triad value, script will return a non-zero exit code if this condition is not met (default is 50000 [in MiB/s])

    -d RESULTS_DIR, --results-dir=RESULTS_DIR
                  the directory in which to write temporary output files (if not set, will attempt to use TMPDIR or /tmp)

    -e STREAM_EXE, --stream-exe=STREAM_EXE
                  the path to the stream executable (set this if stream is not already in PATH)

    -c, --clean   clean the RESULTS_DIR dir (these files will not be removed by default)"
}

function die() {
    local msg="$1"
    local -i exit="$2"
    printf 'ERROR: %s\n' "$msg" 1>&2
    exit "$exit"
}

function cleanup() {
    cat -- "$run_log" # let's write the results to stdout
    echo "cleanup() -- NOT YET IMPLEMENTED, DOING NOTHING"
}

function setup() {
    # set to 1 (fail) incase this test fails to complete 
    echo "1" > "$lastrun_status"
    mkdir -p "$RESULTS_DIR"/results
}

function execute() {
    for i in $(seq 1 "$num_tests"); do
        srun bash -c "OMP_NUM_THREADS=$hostcpus $STREAM_EXE" >> "$log"
    done
}

function evaluate() {
    if [ ! -f "$log" ]; then
        echo "$date - no log found! - FAIL" >> "$run_log"
        exit 1
    fi

    local min_triad="$MIN_TRIAD"
    local flag=0
    local triad_avg
    triad_avg="$(grep "Triad" "$log" | awk '{ sum += $2; count++ } END { print sum / count }')"

    # Ensure triad_avg is not empty
    if [ -z "$triad_avg" ]; then
        echo "no write data in log!"
        exit 1
    fi

    # check triad average
    if [ "$(echo "$triad_avg <= $min_triad" | bc)" -eq 1 ]; then
        echo "$date - Triad: $triad_avg - FAIL" >> "$run_log"
        flag=1
    else
        echo "$date - Triad: $triad_avg - OK" >> "$run_log"
    fi

    if [ "$flag" -eq 1 ]; then
        return 1
    else
        return 0
    fi
}

trap cleanup EXIT

# set these vars for the usage function (ANSI escape codes)
readonly BOLD=$"\033[1m"
readonly END=$"\033[0m"
# this pipeline technically works more robustly when there are special chars in
# the filename
IFS= read -rd '' SCRIPT_NAME < <(basename -z -- "${BASH_SOURCE[0]}")

RESULTS_DIR="${TMPDIR:-/tmp}/stream"
STREAM_EXE=
MIN_TRIAD=10000
num_tests=5
hostcpus="$(srun env |grep SLURM_CPUS_ON_NODE|awk -F= '{print $2; exit}')"

if ! [[ "$hostcpus" =~ ^[0-9]+$ ]]; then
    die "hostcpus is not an int" 1
fi
    
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit
            ;;
        -r|--min-triad=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            if ! [[ "$1" =~ ^[0-9]+$ ]]; then
                die "MIN_TRIAD argument must be an int" 1
            fi
            MIN_TRIAD="$1"
            ;;
        -d|--results-dir=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            RESULTS_DIR="$1"
            ;;
        -e|--stream-exe=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            STREAM_EXE="$1"
            ;;
        -c|--clean)
            NOCLEAN=0
            ;;
        *)
            die "unrecognized argument ${1@Q}$(echo; usage)" 1
            ;;
    esac
    shift
done

if [[ -z "$STREAM_EXE" ]]; then
    STREAM_EXE="$(type -P stream_omp)" || {
        die "the -e/--stream-exe option was not set, and no stream program could be found in PATH" 1
    }
fi

if ! [[ -x "$STREAM_EXE" ]]; then
    die "STREAM_EXE (${STREAM_EXE@Q}) either doesn't exist or is not executable" 1
fi

echo "STREAM_EXE=${STREAM_EXE}"

date="$(date +"%Y%m%d.%H%M")"
log="$RESULTS_DIR"/results/stream_"$date".out
lastrun_status="$RESULTS_DIR"/lastrun.status
run_log="$RESULTS_DIR"/run.log

setup

execute

if evaluate;  then
    echo "0" > "$lastrun_status"
    exit 0
else
    echo "1" > "$lastrun_status"
    exit 1
fi
