#!/bin/bash
#SBATCH --job-name=pkgtst_array
#SBATCH --mem=10G
#SBATCH --time=45
#SBATCH -c 4

DIRNAME="$(pkgtst config slurm_runner:output_dir -p)" || {
    printf '%s\n' "WARNING: 'pkgtst config slurm_runner:output_dir' command failed" 1>&2
    printf '%s\n' "WARNING: defaulting to using SLURM_SUBMIT_DIR as the output_dir" 1>&2
    DIRNAME="$SLURM_SUBMIT_DIR"
}

if [[ $# -eq 0 ]]; then
    read -r package_id < <(pkgtst enumerate | sed -n "${SLURM_ARRAY_TASK_ID}p")
else
    read -r package_id < <(pkgtst enumerate "$@" | sed -n "${SLURM_ARRAY_TASK_ID}p")
fi

if [[ -z "$package_id" ]]; then
    printf '%s\n' "[$(date)] ERROR: empty package_id (SLURM_ARRAY_TASK_ID: ${SLURM_ARRAY_TASK_ID@Q})"
    exit 1
fi

{

    printf '%s\n' "SLURM_ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID@Q}" "SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID@Q}"
    command time -v pkgtst test "$package_id"

} &> "$DIRNAME"/tests/pkgtst_test_"${package_id//:/_}"_"$(date +'%Y-%m-%dT%H:%M:%S')".log
