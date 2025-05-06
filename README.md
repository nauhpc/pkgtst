# pkgtst - The Software Package Tester

This project aims to help verify that a set of software packages is working,
especially to help detect breakage from software updates or accidental edits.

It does this with three types of software tests:

1. the "fileint" file integrity test

2. detecting missing libraries as reported by the `ldd` command

3. custom tests

# Quickstart Tutorial

1. Clone the project and `cd` into it:

```
git clone https://github.com/nauhpc/pkgtst
cd pkgtst
```

2. We highly recommend installing this package in a python venv:

```
python3 -m venv ./p-env
. ./p-env/bin/activate
```

3. Then install with pip:

```
pip install .

# (Optional) Execute the `post-install` script, which:
# 1. sets paths in the configuration file to be subdirectories of the base repo
# 2. create needed directories
# 3. adds PKGTST_ROOT setting to the ./p-env/bin/activate script
#    - if you don't run the post-install script, you'll still need the
#      PKGTST_ROOT env var setting (example:
#      `export PKGTST_ROOT='/scratch/billy/pkgtst-repro/pkgtst'`)

./post-install
```

4. Review the default configuration in `./etc/pkgtst.yaml`

    The most important parts are the `[general][base]` and `[general][hierarchy]` settings. The former should point to the base of a package tree. We set this to be the base of our package tree for our loadable [Lmod](https://github.com/TACC/Lmod) modules. The latter setting should match your file system hierarchy. Once you have this set to your liking move on to the next step.
    
    You'll also want to replace the placeholder values, namely: `[fileint][dbfile]`, `[general][email]`, and `[report_gen][rendered_html]`.
    
5. Test all packages

```
pkgtst test --all
```

    Note: you can optionally do it with the `--slurm` flag which means that `pkgtst` will use a job array with an element for each detected package. You can tell `pkgtst` to list the packages with `pkgtst enumerate`.

6. Viewing results

    The `pkgtst report` subcommand has all the options you need. By default the results are printed directly to stdout. But you can render the results into an easier to read HTML file by using the `--render-template` option. We've included several templates to choose from in the `./etc/templates` directory.
    
    Some examples:
```
# print all results
pkgtst report

# print only three runs per package
pkgtst report --limit-per 3

# render the default jinja template (the default template is determined by the
# `[report_gen][rendered_html]` parameter of the config file)
pkgtst report --render-jinja

# render an a different jinja template by specifying the path
pkgtst report --template-path ./etc/templates/static-table-wo-dates.html
```

7. (Bonus) Running custom tests

    The main per-package test runs are for validating that there are no file system changes to the packages, and that there are no library not found errors. But in addition to that, we have a selection of custom tests, which each run an `sbatch` job and determine if it passes by checking the `ExitCode` field from the `sacct` command.

    Important custom test commands:

```
# view all options for the custom_test subcommand
pkgtst custom_test --help

## list available custom tests

pkgtst custom_test --list

## run a specific custom test

pkgtst custom_test TESTNAME[:VARIANT]

# run all custom tests
pkgtst custom_test --all

# view results on the command-line

pkgtst custom_test -p

# Note: Alternatively, you can re-run `pkgtst report --render-jinja` to
#       regenerate the HTML file. The default Jinja template includes the custom
#       test results.
```

8. (Bonus) Custom test configuration

    As the name suggests, these tests are customizable. You can drag and drop additional Slurm jobs there, and `pkgtst` will consider an `ExitCode` of 0 to be a success and any other value to mean that the job failed. If the script supports it, there is an option to include a YAML configuration file too in the `[custom_test][script]` directory.
    
    For example, by creating an `ior.yaml` in the same directory as the `ior.sh` script:

```
# ior.yaml
variants:
  type: slurm_feature_w_args
  value:
    - feature: myslurmfeature # this command will list Slurm features on your site: sinfo -h -a -e -o '%n %f'
      sbatch_args: # set cmd-line args for the sbatch program, run 'man sbatch' to view all options
        - '--ntasks=20'
      args: # set cmd-line args for the ior.sh script, run './ior.sh --help' to view all options
        - '--min-write=10000'
        - '--min-read=5000'

# Scripts that follow the `script.template` format will all use these options:
#
# OPTIONS
#     -h, --help    print this help message
#
#     -d RESULTS_DIR, --results-dir=RESULTS_DIR
#                   the directory in which to write temporary output files (if not set, will attempt to use TMPDIR or /tmp)
#
#     -c, --clean   clean the RESULTS_DIR dir (these files will not be removed by default)
```
