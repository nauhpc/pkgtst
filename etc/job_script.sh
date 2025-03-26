#!/bin/bash
#SBATCH --job-name=pkgtst_array
#SBATCH --mem=10G
#SBATCH --time=45
#SBATCH -c 4

DIRNAME="$SLURM_SUBMIT_DIR"

read -r package_id < <(pkgtst enumerate | sed -n "${SLURM_ARRAY_TASK_ID}p")

if [[ -z "$package_id" ]]; then
    printf '%s\n' "[$(date)] ERROR: empty package_id (SLURM_ARRAY_TASK_ID: ${SLURM_ARRAY_TASK_ID@Q})"
    exit 1
fi

{

    command time -v pkgtst test "$package_id"

} &> "$DIRNAME"/logs/pkgtst_test_"${package_id//:/_}"_"$(date --iso)".log
