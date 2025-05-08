#!/bin/bash
# This jobscript will be called from the pkgtst custom test function
# The acceptable min value for the elbencho test will be sent as an argument to this script
#SBATCH --job-name=pkgtst_elbencho
#SBATCH --time=10:00
#SBATCH -N 2
#SBATCH -c16
#SBATCH -C epyc

function usage() {
    printf '%b\n' "${BOLD}NAME${END}
    ${SCRIPT_NAME}

${BOLD}DESCRIPTION${END}
    Sbatch/bash wrapper for the elbencho program, will parse the output for acceptable values

${BOLD}OPTIONS${END}
    -h, --help    print this help message

    -r MIN_READ, --min-read=MIN_READ
                  minimum acceptable read value, script will return a non-zero exit code if this condition is not met (default is 50000 [in MiB/s])

    -w MIN_WRITE, --min-write=MIN_WRITE
                  minimum acceptable write value, script will return a non-zero exit code if this condition is not met (default is 10000 [in MiB/s])

    -t TARGET_DIR, --target=TARGET_DIR
                  the directory against which to run the elbencho test (if not set, will attepmt to use /scratch/$USER/elbencho)

    -d RESULTS_DIR, --results-dir=RESULTS_DIR
                  the directory in which to write temporary output files (if not set, will attempt to use TMPDIR or /tmp)

    -e ELBENCHO_EXE, --elbencho-exe=ELBENCHO_EXE
                  the path to the elbencho executable (set this if elbencho is not already in PATH)

    -c, --clean   clean the RESULTS_DIR dir (these files will not be removed by default)"
}

function die() {
    local msg="$1"
    local -i exit="$2"
    printf 'ERROR: %s\n' "$msg" 1>&2
    exit "$exit"
}

function cleanup() {
    # quit services
    if [[ -x "$ELBENCHO_EXE" ]]; then
        "$ELBENCHO_EXE" --quit --hosts "$hosts"
    fi

    echo 'my run log -- start'
    cat -- "$run_log" # let's write the results to stdout
    echo 'my run log -- end'

    if [[ "$NOCLEAN" = 0 ]]; then
        echo "in cleanup(): NOCLEAN=${NOCLEAN@Q} ignored, no deletion will occur"
    fi
}

function setup() {
    # set to 1 (fail) incase this test fails to complete 
    echo "1" > "$lastrun_status"
    mkdir -p -- "$RESULTS_DIR"/results
}

function execute() {

    # Start service on all hosts 
    srun "$ELBENCHO_EXE" --service --foreground &

    # wait for elbencho http ports to open 
    sleep 5

    # Run benchmark
    "$ELBENCHO_EXE" --hosts "$hosts" \
                    --threads 16 \
                    --resfile "$log" \
                    --size 4g \
                    --files 1 \
                    -i "$num_tests" \
                    --dirsharing \
	            --direct \
	            -D \
	            -F \
                    --mkdirs \
                    --block 1m \
                    --blockvaralgo fast \
                    --blockvarpct 100 \
                    --write "$TARGET_DIR" \
                    --read
}

function evaluate() {
    if [ ! -f "$log" ]; then
        echo "$date - no log found! - FAIL" >> "$run_log"
        exit 1
    fi

    local min_write="$MIN_WRITE"
    local min_read="$MIN_READ"
    local flag=0
    local write_avg
    local read_avg
    
    write_avg="$(grep -A4 WRITE "$log" | grep Throughput | awk '{sum += $5; count++} END { print sum / count }')"
    read_avg="$(grep -A4 READ "$log" | grep Throughput | awk '{sum += $5; count++} END { print sum / count }')"

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
        echo "$date - Read: $read_avg - FAIL" >> "$run_log"
        flag=1
    else
        echo "$date - Read: $read_avg - OK" >> "$run_log"
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

RESULTS_DIR="${TMPDIR:-/tmp}/elbencho"
ELBENCHO_EXE=
TARGET_DIR=/scratch/"$USER"/elbencho
num_tests=2
hosts="$(scontrol show hostnames "$SLURM_JOB_NODELIST" | tr "\n" ",")"
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
        -e|--elbencho-exe=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            ELBENCHO_EXE="$1"
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

if [[ -z "$ELBENCHO_EXE" ]]; then
    ELBENCHO_EXE="$(type -P elbencho)" || {
        die "the -e/--elbencho-exe option was not set, and no elbencho program could be found in PATH" 1
    }
fi

if ! [[ -x "$ELBENCHO_EXE" ]]; then
    die "ELBENCHO_EXE (${ELBENCHO_EXE@Q}) either doesn't exist or is not executable" 1
fi

date="$(date +"%Y%m%d.%H%M")"
log="$RESULTS_DIR"/results/elbencho_"$date".out
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
