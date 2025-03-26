#!/bin/bash
#SBATCH -G 1
#SBATCH --mem=8G
#SBATCH --time=5

function usage() {
    printf '%b\n' "${BOLD}NAME${END}
    ${SCRIPT_NAME}

${BOLD}DESCRIPTION${END}
    Build and executes gpu_burn, checking for GPU usage during the run

${BOLD}OPTIONS${END}
    -h, --help    print this help message

    -d RESULTS_DIR, --results-dir=RESULTS_DIR
                  intermediate results dir (if not set, will attempt to use TMPDIR or /tmp)

    -c, --clean   clean the RESULTS_DIR dir (these files will not be removed by default)"
}

function die() {
    local msg="$1"
    local -i exit="$2"
    printf 'ERROR: %s\n' "$msg" 1>&2
    exit "$exit"
}

function cleanup() {

    printf 'in cleanup(): %s\n' "RESULTS_DIR=${RESULTS_DIR}"

    if [[ "$NOCLEAN" = 1 ]]; then
        printf '%s\n' 'skipping cleanup (NOCLEAN=1)' 1>&2
        return
    fi
    
    # shellcheck disable=2317
    if [[ -n "$RESULTS_DIR" ]]; then
        # can't hurt to double-check
        if [[ "$(basename "$RESULTS_DIR")" = gpu-burn ]]; then
            rm -rf -- "$RESULTS_DIR"
        fi
    fi
}

function setup() {
    local output
    
    output="$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)"
    if ! [[ "$output" =~ ^[0-9]+$  && "$output" -gt 0 ]]; then
        die 'could not determine the number of available GPUs' 1
    fi

    cd -- "$(dirname -- "$RESULTS_DIR")" || {
        die "failed to cd into $(dirname -- "$RESULTS_DIR")/.." 1
    }

    if ! [[ -d "gpu-burn" ]]; then
        if ! git clone https://github.com/wilicc/gpu-burn; then
            die 'unable to run git clone' 1
        fi
    else
        printf 'INFO: gpu-burn directory already exists, will skip git the clone step\n' 1>&2
        NOCLONE=1
    fi

    cd -- gpu-burn || {
        die 'failed to cd into gpu-burn (did the git clone operation work?' 1
    }

    if [[ "$NOCLONE" = 1 ]]; then
        make clean || {
            die 'failed to clean the build' 1
        }
    fi
}

function execute() {

    module purge

    # we'll keep trying cuda modules until one works, starting with the latest module
    while read -r module_name; do
        module purge
        module load "$module_name"
        if output="$("$CUDA_HOME"/extras/demo_suite/deviceQuery)"; then
            lines="$(wc -l <<< "$output")"
            if [[ "$lines" =~ ^[0-9]+$ ]] && [[ "$lines" -gt 0 ]]; then
                cuda_compute="$(awk '/CUDA Capability/ { print $NF; exit }' <<< "$output")"
                cuda_compute="$(tr -c -d '0-9' <<< "$cuda_compute")"
                break
            fi
        fi
    done < <(module --terse av cuda |& grep -P '^cuda' | sort -V -r)

    printf '%s\n' "COMPUTE=${cuda_compute@Q}" 1>&2

    make COMPUTE="$cuda_compute" || {
        die 'make failed' 2
    }
 
    timeout 35s nvidia-smi dmon 2> /dev/null 1> "$LOGFILE" &

    ./gpu_burn 30 || {
        die 'gpu_burn exited abnormally' 2
    }
}

function evaluate() {
    local output
    if output="$(awk '($0 !~ /^#/ && $5 >= 95) { i+= 1 } END { print "Busy polls", i }' "$LOGFILE")"; then
        if [[ "$output" =~ ^Busy\ polls.*$ ]]; then
            read -r word1 word2 N <<< "$output"
            printf '%s\n' "N=$N"
            if [[ "$N" =~ ^[0-9]+$ ]] && [[ "$N" -ge 25 ]]; then
                return 0
            else
                die 'Utilization threshold not met' 3
            fi
        fi
    fi
}

RESULTS_DIR=
NOCLEAN=1

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit
            ;;
        -d|--results-dir=*)
            if [[ "$1" =~ ^.*=.*$ ]]; then
                set -- "${1#*=}" "${@:2}"
            else
                shift
            fi
            RESULTS_DIR="$1"
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

if [[ -z "$RESULTS_DIR" ]]; then
    RESULTS_DIR="${TMPDIR:-/tmp}/gpu-burn"
fi

LOGFILE="${RESULTS_DIR}/nvidia-smi.log"

trap cleanup EXIT

setup

execute

evaluate
