#!/bin/bash
#SBATCH --job-name=pkgtst_single
#SBATCH --mem=10G
#SBATCH --time=45
#SBATCH -c 4

DIRNAME="$(pkgtst config slurm_runner:output_dir -p)" || {
    printf '%s\n' "WARNING: 'pkgtst config slurm_runner:output_dir' command failed" 1>&2
    printf '%s\n' "WARNING: defaulting to using SLURM_SUBMIT_DIR as the output_dir" 1>&2
    DIRNAME="$SLURM_SUBMIT_DIR"
}

package_id="$1"

if [[ -z "$package_id" ]]; then
    printf '%s\n' "[$(date)] ERROR: empty package_id (SLURM_ARRAY_TASK_ID: ${SLURM_ARRAY_TASK_ID@Q})"
    exit 1
fi

{

    printf '%s\n' "SLURM_JOB_ID=${SLURM_JOB_ID@Q}"
    command time -v pkgtst test "$package_id"

} &> "$DIRNAME"/tests/pkgtst_test_"${package_id//:/_}"_"$(date +'%Y-%m-%dT%H:%M:%S')".log
