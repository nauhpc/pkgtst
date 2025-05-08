#!/bin/bash
#SBATCH --job-name=pkgtst_ior
#SBATCH --time=5:00
#SBATCH --ntasks=28
#SBATCH -N 1
#SBATCH --exclusive

function usage() {
    printf '%b\n' "${BOLD}NAME${END}
    ${SCRIPT_NAME}

${BOLD}DESCRIPTION${END}
    Sbatch/bash wrapper for the ior program, will parse the output for acceptable values

${BOLD}OPTIONS${END}
    -h, --help    print this help message

    -r MIN_READ, --min-read=MIN_READ
                  minimum acceptable read value, script will return a non-zero exit code if this condition is not met (default is 50000 [in MiB/s])

    -w MIN_WRITE, --min-write=MIN_WRITE
                  minimum acceptable write value, script will return a non-zero exit code if this condition is not met (default is 10000 [in MiB/s])

    -t TARGET_DIR, --target=TARGET_DIR
                  the directory against which to run the ior test (if not set, will attepmt to use /scratch/$USER/ior)

    -d RESULTS_DIR, --results-dir=RESULTS_DIR
                  the directory in which to write temporary output files (if not set, will attempt to use TMPDIR or /tmp)

    -e IOR_EXE, --ior-exe=IOR_EXE
                  the path to the ior executable (set this if ior is not already in PATH)

    -c, --clean   clean the RESULTS_DIR dir (these files will not be removed by default)"
}

function die() {
    local msg="$1"
    local -i exit="$2"
    printf 'ERROR: %s\n' "$msg" 1>&2
    exit "$exit"
}

function cleanup() {
    echo "in cleanup(): TARGET_DIR=${TARGET_DIR@Q}, RESULTS_DIR=${RESULTS_DIR@Q}" 1>&2

    printf 'in cleanup(): ' 1>&2

    cat -- "$run_log" # let's write the results to stdout

    if [[ "$NOCLEAN" = 1 ]]; then
        printf '%s\n' 'skipping cleanup (NOCLEAN=1)' 1>&2
        return
    fi

    # We have two dirs to clean up:
    # 1. TARGET_DIR
    #    - ior may have left files here, it read/writes them as par of its tests
    # 2. RESULTS_DIR
    #    - contains temporary output files, it will be a subfolder of the user's
    #      tmp, but it can be set differently with a cmdline arg

    if [[ -n "$TARGET_DIR" ]]; then
        rm -rf -- "$TARGET_DIR"
    fi

    if [[ -n "$RESULTS_DIR" ]]; then
        rm -rf -- "RESULTS_DIR"
    fi
}

function setup() {

    echo "in setup()"

    mkdir -p -- "$TARGET_DIR" || {
        die "unable to create dir ${TARGET_DIR@Q}" 1
    }
    mkdir -p -- "$RESULTS_DIR"/results || {
        die "unable to create dir $RESULTS_DIR/results" 1
    }

    # set to 1 (fail) incase this test fails to complete 
    echo "1" > "$lastrun_status"
}

function execute() {
    echo "in execute()"
    module load openmpi
    srun --mpi=pmi2 -o "$log" "$IOR_EXE" -i 5 -F -t 1m -b 512m -o "$TARGET_DIR"/ior_64_epyc."$date"
}

function evaluate() {
    echo "in evaluate()"
    echo "run_log=${run_log@Q}"
    if [ ! -f "$log" ]; then
        echo "$date - no log found! - FAIL" >> "$run_log"
        exit 1
    fi

    # local min_read=50000
    # local min_write=10000
    local min_read="$MIN_READ"
    local min_write="$MIN_WRITE"
    local flag=0

    local write_avg
    local read_avg

    write_avg="$(tail -n 3 "$log" | grep write|awk '{print $4}')"
    read_avg="$(tail -n 3 "$log" | grep read|awk '{print $4}')"

    # Ensure write_avg is not empty
    if [ -z "$write_avg" ]; then
        echo "no write data in log!"
        exit 1
    fi

    # Ensure read_avg is not empty
    if [ -z "$read_avg" ]; then
        echo "no read data in log!"
        exit 1
    fi

    # check write average
    if [ "$(echo "$write_avg <= $min_write" | bc)" -eq 1 ]; then
        echo "$date - Write: $write_avg - FAIL" >> "$run_log"
        flag=1
    else
        echo "$date - Write: $write_avg - OK" >> "$run_log"
    fi

    # check read average
    if [ "$(echo "$read_avg <= $min_read" | bc)" -eq 1 ]; then
        echo "$date - Read:  $read_avg - FAIL" >> "$run_log"
        flag=1
    else
        echo "$date - Read:  $read_avg - OK" >> "$run_log"
    fi

    if [ "$flag" -eq 1 ]; then
        return 1
    else
        return 0
    fi
}

# set these vars for the usage function (ANSI escape codes)
readonly BOLD=$"\033[1m"
readonly END=$"\033[0m"
# this pipeline technically works more robustly when there are special chars in
# the filename
IFS= read -rd '' SCRIPT_NAME < <(basename -z -- "${BASH_SOURCE[0]}")

RESULTS_DIR="${TMPDIR:-/tmp}/ior"
MIN_READ=50000
MIN_WRITE=10000
TARGET_DIR=/scratch/"$USER"/ior
IOR_EXE=
NOCLEAN=1

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit
            ;;
        -r|--min-read=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            if ! [[ "$1" =~ ^[0-9]+$ ]]; then
                die "MIN_READ argument must be an int" 1
            fi
            MIN_READ="$1"
            ;;
        -w|--min-write=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            if ! [[ "$1" =~ ^[0-9]+$ ]]; then
                die "MIN_WRITE argument must be an int" 1
            fi
            MIN_WRITE="$1"
            ;;
        -t|--target-dir=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            TARGET_DIR="$1"
            ;;
        -d|--results-dir=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            RESULTS_DIR="$1"
            ;;
        -e|--ior-exe=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            IOR_EXE="$1"
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

if [[ -z "$IOR_EXE" ]]; then
    IOR_EXE="$(type -P ior)" || {
        die "the -e/--ior-exe option was not set, and no ior program could be found in PATH" 1
    }
fi

if ! [[ -x "$IOR_EXE" ]]; then
    die "IOR_EXE (${IOR_EXE@Q}) either doesn't exist or is not executable" 1
fi

date="$(date +"%Y%m%d.%H%M")"
log="$RESULTS_DIR"/results/ior_"$date".out
lastrun_status="$RESULTS_DIR"/lastrun.status
run_log="$RESULTS_DIR"/run.log

printf '%s\n' "MIN_READ=${MIN_READ@Q}" "MIN_WRITE=${MIN_WRITE@Q}" "TARGET_DIR=${TARGET_DIR@Q}" "RESULTS_DIR=${RESULTS_DIR@Q}" "IOR_EXE=${IOR_EXE@Q}"

trap cleanup EXIT

setup

execute

if evaluate;  then
  echo "0" > "$lastrun_status"
  exit 0
else
  echo "1" > "$lastrun_status"
  exit 1
fi
