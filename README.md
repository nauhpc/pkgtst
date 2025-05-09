# pkgtst - The Software Package Tester

This project aims to help verify that a set of software packages is working
properly, especially after software updates or file system changes.

It does this with three types of software tests:

1. File Integrity

    Walks the contents of a package and checks if any of the attributes such as the POSIX file permissions, size, date, and hashes have changed from that which was recorded in pkgtst's database

2. Missing Library Scan

    Checks for missing shared libraries libraries by running the "ldd" command against each ELF executable in the package

3. Custom Tests

    Ad-hoc [sbatch](https://slurm.schedmd.com/sbatch.html) test jobs, intended for various performance and usage tests

# Quickstart Tutorial

1. Navigate to the desired directory, clone the project, the project and `cd` into it:

    ```
    git clone https://github.com/nauhpc/pkgtst.git
    cd pkgtst
    ```

    This directory will serve as your package test root directory. Later, to use the project you will have to set the environment variable `PKGTST_ROOT` to this path.

2. Environment setupy

    We highly recommend installing this package in a python venv:

    ```
    python3 -m venv ./p-env
    . ./p-env/bin/activate
    ```
    
    You can consider making an Lmod modulefile too, which would load and unload this venv:
    ```
    -- -*- pkgtst 0.2.0 -*- --
    whatis("Description: Provides pkgtst, version 0.2.0")
    execute{cmd=". /path/to/pkgtst/p-env/bin/activate", modeA={"load"}}
    execute{cmd="deactivate", modeA={"unload"}}
    setenv("PKGTST_ROOT","/path/to/pkgtst")
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
    #      `export PKGTST_ROOT='/path/to/pkgtst'`)
    ./post-install
    ```

4. Review the default configuration in `./etc/pkgtst.yaml`

    The most important parts are the `[general][base]` and `[general][hierarchy]` settings. The former should point to the base of a package tree. We set this to be the base of our package tree for our loadable [Lmod](https://github.com/TACC/Lmod) modules. The latter setting should match your file system hierarchy. Also, edit the placeholder value for `[general][email]`. Once you have this set to your liking move on to the next step.
    
    ```
    # view all discoverable packages, verify configuration
    pkgtst enumerate
    ```
    
    For example, if you were to use the default configuration, and your directory looked like this:
    
    ```
    /packages/python/3.13.3
    /packages/python/2.7.18
    /packages/r/4.4.1
    ```
    
    Then with the `pkgtst enumerate` command, you should see:
    
    ```
    $ pkgtst enumerate
    python:3.13.3
    python:2.7.18
    r:4.4.1
    $
    ```
    
    Also, let's say for example that you want to exclude that 2nd python package, because you only want to test the newer version, you can add a path to the ignore_path config parameter:
    
    ```
    ignore_paths:
    - /packages/python/2.7.18
    ```
    
5. Test packages

    ```
    # test a single package
    # the PACKAGE_ID is a colon-separated identifier string, run "pkgtst enumerate" to list all possibilities
    pkgtst test PACKAGE_ID
    
    # view results (you should see one new row)
    pkgtst report PACKAGE_ID
    
    # test a single package in a Slurm job (instead of running directly on current host)
    pkgtst test --slurm PACKAGE_ID
    
    # test all packages
    pkgtst test --all
    
    # test all packages in a Slurm job
    pkgtst test --all --slurm
    
    # view all results
    pkgtst report
    ```

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
    
    # render a different jinja template by specifying the path
    pkgtst report --template-path ./etc/templates/static-table-wo-dates.html
    ```

7. (Bonus) Running custom tests

    Custom tests are a collection of `sbatch` job scripts, intended for running various performance benchmarks and usage tests. `pkgtst` will determine if the test passes or fails based on the `exit_code` (0 indicates a pass, and non-zero values indicate failure).
    
    As the name suggests, these tests are customizable.
    
    For example, by creating an `ior.yaml` in the same directory as the `ior.sh` script:

    ```
	# ior.yaml
	variants:
	  type: slurm_feature_w_args
	  value:
	    - feature: CHANGE_ME # this command will list Slurm features on your site: sinfo -h -a -e -o '%n %f'
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
	#
	# But some scripts handle additional arguments, to view all of the command-line options that ior.sh can handle for example, then execute: ./var/custom_test/scripts/ior.sh --help
	```

    Generally all of these custom tests will need some configuration, for the evaluation parameters if nothing else. But the most important part is that all of these custom tests use Slurm and the pass/fail test result is determined by the exit code of the script.

    Walkthrough:
    ```
    # In the ior.yaml, we've decided to configure ior.yaml for our nodes with the "epyc" slurm feature
    # Variants in custom_test work like versions, for the ior test, there can be multiple variants where the variant can be any of the Slurm features available.
    # This is helpful if you have multiple generations of nodes, and want to specify different test parameters for different ones.
    
    $ pkgtst custom_test -l
	test_name: elbencho
		script: elbencho.sh
		yaml: None
		variants: None
	 
	test_name: osu_mb
		script: osu_mb.sh
		yaml: None
		variants: None
	 
	test_name: ior
		script: ior.sh
		yaml: ior.yaml
		variants: ['hw']
	 
	test_name: gpu_burn
		script: gpu_burn.sh
		yaml: None
		variants: None
	 
	test_name: stream
		script: stream.sh
		yaml: None
		variants: None
    $ 
    ```
    
    So to fill in "epyc" for that Slurm feature, we'd use this config:
    ```
    # ior.yaml
	variants:
	  type: slurm_feature_w_args
	  value:
	    - feature: hw # this command will list Slurm features on your site: sinfo -h -a -e -o '%n %f'
	      sbatch_args: # set cmd-line args for the sbatch program, run 'man sbatch' to view all options
	        - '--ntasks=20'
	      args: # set cmd-line args for the ior.sh script, run './ior.sh --help' to view all options
	        - '--min-write=10000'
	        - '--min-read=5000'
    ```

    ```
    # List available custom tests
    pkgtst custom_test -l
    
    # Run one custom test
    pkgtst custom_test ior:epyc
    
    # View the results
    pkgtst custom_test -p ior:epyc

    # To view all test results:
    pkgtst custom_test -p
    ```
