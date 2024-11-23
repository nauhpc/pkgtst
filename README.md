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
python3 -m venv ./pkgtst-env
. ./pkgtst-env
```

3. Then install with pip:
```
pip install .
```

4. Review the default configuration in `./etc/pkgtst.yaml`

    The most important parts are the `[general][base]` and `[general][hierarchy]` settings. The former should point to the base of a package tree. We set this to be the base of our package tree for our loadable [Lmod](https://github.com/TACC/Lmod) modules. The latter setting should match your file system hierarchy. Once you have this set to your liking move on to the next step.
    
    You'll also want to replace the placeholder values, namely: `[fileint][dbfile]`, `[general][email]`, and `[report_gen][rendered_html]`.
    
5. Execute the program for each package

    First you will want to check what packages the program detects on your system:
    
```
pkgtst enumerate
```

    If the above command shows the output you expect based on your settings in `./etc/pkgtst.yaml`, proceed with executing the program.

    If your system supports Slurm our default script should work for you:
    
```
./exec_pkgtst.sh
```

    It will launch a Slurm job array with a job array task for each package. If you're not using Slurm, you'll need to somehow loop over each package manually, a simple example would be:
    
```
while read -r PACKAGE_ID; do
    pkgtst test "$PACKAGE_ID"
done < <(pkgtst enumerate)
```

6. Viewing results

    The `pkgtst report` subcommand has all the options you need. By default the results are printed directly to stdout. But you can render the results into an easier to read HTML file by using the `--render-template` option. We've included several templates to choose from in the `./etc/templates` directory.
    
    Some examples:
```
# print all results
pkgtst report

# print only three runs per package
pkgtst report --limit-per 3

# render the default jinja template (specified in ./etc/pkgtst.yaml)
pkgtst report --render-jinja

# render an a different jinja template by specifying the path
pkgtst report --template-path ./etc/templates/collapsible-table-w-dates.html
```
