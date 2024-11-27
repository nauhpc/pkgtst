#!/bin/bash

function usage() {
    echo -e '\e[1mNAME\e[0m
    exec_pkgtst.sh

\e[1mUSAGE\e[0m
    exec_pkgtst.sh [OPTIONS]

\e[1mOPTIONS\e[0m
    -n NUMBER, --nmax NUMBER       The max number of packages to test if this is
                                   not set, every package will be tested
    -h, --help                     Display this help message'
}

N=

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -n|--nmax)
            shift
            if ! [[ "$1" =~ ^[0-9]+$ ]]; then
                printf '%s\n' "ERROR: expected an int argument for -n|--nmax, received ${1@Q}" 1>&2
                usage
                exit 1
            fi
            N="$1"
            ;;
        *)
            printf '%s\n' "ERROR: unexpected argument ${1@Q}" 1>&2
            usage
            exit 1
            ;;
    esac
    shift
done

# check that the pkgtst command exists before proceeding
if ! command -v pkgtst &> /dev/null; then
    printf '%s\n' 'ERROR: pkgtst command not found, cannot proceed (did you activate your python venv?)'
    exit 1
fi

if EMAIL="$(python -c "import yaml; print(yaml.safe_load(open('./etc/pkgtst.yaml'))['general']['email'])" 2> /dev/null)"; then
    if [[ "$EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        printf '%s\n' "INFO: sending notification to email (${EMAIL@Q})" 1>&2
        printf '%s\n' "$(date)" "Running as $(whoami)" | mailx -s "executing exec_pkgtst.sh" "$EMAIL"
    fi
fi

# set DIRNAME to the directory in which this script resides
IFS= read -rd '' DIRNAME < <(dirname -z -- "${BASH_SOURCE[0]}")

if ! [[ "$N" =~ ^[0-9]+$ ]]; then
    N="$(wc -l < <(pkgtst enumerate))"
fi

if [[ ! "$N" =~ ^[0-9]+$ ]] || [[ "$N" -lt 1 ]]; then
    printf '%s\n' "ERROR: unexpected value of N (${N@Q})" 1>&2
    exit 1
fi

# clean up old logs
cd -- "$DIRNAME" && {
    rm -vrf ./logs
}

# submit job array
output_file="$DIRNAME/logs/pkgtst_combined.log"
jobid="$(sbatch --array="1-${N}%16" --output="$output_file" "$DIRNAME"/job_script.sh | awk '{ print $4 }')"
if ! [[ "$jobid" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "ERROR: job submission failed for array" 1>&2
    exit 1
fi

# submit jinja rendering job, will execute after the array
output_file="$DIRNAME/logs/render_jinja_$(date +"%Y-%m-%dT%T").log"
sbatch --time=5 --job-name='render_jinja' --dependency="afterany:$jobid" --wrap="pkgtst report --render-jinja" --output="$output_file"
