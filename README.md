# pkgtst - The Software Package Tester

This project aims to help verify that a set of software packages is working,
especially to help detect breakage from software updates or accidental edits.

It does this with three types of software tests:

1. the "fileint" file integrity test

2. detecting missing libraries as reported by the `ldd` command

3. templated test runs (planned)

# Quickstart Tutorial

1. Clone the project and `cd` into it:

```
git clone https://nauhpc/pkgtst
cd pkgtst
```

2. We highly recommend installing this package in a python venv:

```
python3 -m venv ./p-env
. ./p-env
```

3. Then install with pip:
```
pip install .
```

    3.b. (Optional) Use the `post-install` script to set paths in the configuration file to be subdirectories of the base repo and create expected directories:
    ```
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

# render the default jinja template (the default template is determined by the `[report_gen][rendered_html]` parameter of the config file)
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
