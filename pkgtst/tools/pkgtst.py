from pkgtst.lib.fileint import FileInt
from pkgtst.lib.fileint import Hierarchy
from pkgtst.lib.missing_lib_scanner import MissingLibScanner
from pkgtst.lib.report_gen import ReportGen
from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel
from pkgtst.lib.custom_test import CustomTest
from pkgtst.lib.slurm_runner import SlurmRunner
from pkgtst.lib.utils import get_pkgtst_root
from pkgtst.lib.config import ConfigUtil

import argparse
import sys
import subprocess
import os
import yaml
import shlex
import pathlib

def get_command_output(command):
    # Execute the command and get the output
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    # Return the output as a single line
    return result.stdout.strip()

# returns a set of filters for a package id string
def get_filters(package_id_string, config_path=None):

    if package_id_string is None:
        return None
    
    components = package_id_string.split(":")

    h = Hierarchy(config_path=config_path)

    if len(h.components) != len(components):
        raise Exception(f"ERROR: package_id '{package_id_string}' does not match hierarchy {h.components}")

    filters = []
    for i in range(len(h.components)):
        component = h.components[i]
        value = components[i]
        filters.append({"hierarchy": component, "value": value})

    return filters

def do_test(package_id_string, do_reset=False, config_path=None):

    filters = get_filters(package_id_string, config_path)

    # read config file
    if config_path is None:
        config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            ignore_paths = config['general']['ignore_paths']
    else:
        ignore_paths = None

    # 1. check the file integrity
    fi = FileInt(config=config_path)
    fi_results = fi.read_paths(filters, do_reset)

    logger = Logger(config_path=config_path)
    logger.log(LogLevel.INFO, f"PROCESSING PACKAGE: {package_id_string}")

    # 2. find a modulefile and use its LD_LIBRARY_PATH if any for the
    #    next step

    # we'll assume a module name to be "{component1}/{component2}/..."
    h = Hierarchy(config_path=config_path)
    lmod_arg = shlex.quote(package_id_string.replace(":", "/"))
    stdout = get_command_output(f"module display {lmod_arg} &> /dev/null && echo -n exists")
    if len(stdout) > 0 and stdout == "exists":
        module_name = lmod_arg
        stdout = get_command_output(f"module load {module_name} &> /dev/null && printenv LD_LIBRARY_PATH 2> /dev/null")
        if len(stdout) > 0:
            ld_lib_path = stdout
        else:
            ld_lib_path = None
    else:
        module_name = ""
        ld_lib_path = None

    # 3. run lnfs against the root dir of the package
    mlc = MissingLibScanner(config=config_path)
    pkg_base_paths = fi.get_filter_matches(filters)
    if len(pkg_base_paths) != 1:
        logger.log(LogLevel.ERROR, f"pkg_base_path resolution ambiguous for package_id {package_id}, cannot proceed, revise the config file (possible hierarchy settings mistake, or a path needs to be added to ignore_paths)")
    lib_scan_results = mlc.scan(pkg_base_paths, ld_lib_path)

    if (fi_results[2] is None or len(fi_results[2]) == 0) and (fi_results[3] is None or len(fi_results[3]) == 0):
        passed_fileint = True
        print("FILEINT -- [PASSED]")
    else:
        passed_fileint = False
        print("FILEINT -- [FAILED]")

    if lib_scan_results is None or len(lib_scan_results) == 0:
        passed_lnfs = True
        print("LIBSCAN -- [PASSED]")
    else:
        passed_lnfs = False
        print("LIBSCAN -- [FAILED]")

    x = ReportGen(config_path=config_path)
    x.write_result([row['value'] for row in filters], pkg_base_paths[0], module_name, {'passed_fileint': passed_fileint, 'passed_lnfs': passed_lnfs})

def main():

    # Create the top-level parser
    parser = argparse.ArgumentParser(description='pkgtst - The Software Package Tester')
    parser.add_argument('-c', '--config-path', type=str, help='If this arg is not set, will evaluate the PKGTST_CONFIG_PATH environment variable, and if that is not set then this program will look for a etc/pkgtst.yaml file in the CWD')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    # Create a subparser for the 'test' command
    parser_test = subparsers.add_parser('test', help='Test a specific version of a package')
    parser_test.add_argument('package_id', nargs='?', type=str, help='Identifier of package to test, separate hierarchy components with a colon')
    parser_test.add_argument('-a', '--all', action='store_true', help='Set this argument to test all packages')
    parser_test.add_argument('-s', '--slurm', action='store_true', help='Set this argument to run package test(s) in a Slurm job')

    # Create a subparser for the 'print' command
    parser_print = subparsers.add_parser('report', help='Report test results')
    parser_print.add_argument('package_id', nargs='?', type=str, help='Identifier of package to print, separate hierarchy components with a colon')
    parser_print.add_argument('--render-jinja', action='store_true', help='Render the default jinja template')
    parser_print.add_argument('--template-path', type=str, help='Specify the path to the template instead of using the default template')
    parser_print.add_argument('--sort-keys', type=str, help='Colon-separated hierarchy components to sort by')
    parser_print.add_argument('--reverse', action='store_true', help='Reverse the order of the sort')
    parser_print.add_argument('--limit', type=int, help='The max number of runs to show')
    parser_print.add_argument('--limit-per', type=int, help='The max number of runs to show for each unique package')
    parser_print.add_argument('-p', '--parsable', action='store_true', help='Parsable table output')
    parser_print.add_argument('--field-delimiter', type=str, default='|', help='Only used if --parsable is specified, default is \'|\'')
    parser_print.add_argument('--fails-only', action='store_true', help='Only show rows where there is at least one failed test')
    parser_print.add_argument('--case-insensitive', action='store_true', help='Any field sorts will be case insensitive')
    # These edit the config file
    parser_print.add_argument('--set-warn-only', action='store_true', help='If package_id is set, will edit config to persistently set the package as warn-only (meaning it will not appear as an error in output)')
    parser_print.add_argument('--reset-warn-only', action='store_true', help='If package_id is set, will edit config to persistently remove the setting which specifies the package as warn-only (meaning it will appear as an error in output)')
    parser_print.add_argument('--show-warn-only', action='store_true', help='Show packages set to be \'warn-only\'')
    parser_print.add_argument('-n', '--no-truncation', action='store_true', help='Print results without truncating columns to the width of the terminal (has no effect if --render-jinja is set)')
    parser_print.add_argument('-l', '--last-log', action='store_true', help='Print the contents of the last Slurm log file generated for a particular package')

    # Create a subparser for the 'enumerate' command
    parser_enumerate = subparsers.add_parser('enumerate', help='Print all package ids')
    parser_enumerate.add_argument('-s', '--show-required-constraints', action='store_true', help='Show Slurm constraint mappings for packages that a constraint argument (dumps the [slurm_runner][req_constraints] config parameter instead of printing all package ids)')
    parser_enumerate.add_argument('-f', '--filter-constraint', type=str, help='Print only the package ids of packages for which the specified constraint is required')
    parser_enumerate.add_argument('-n', '--filter-no-constraint', action='store_true', help='Print only the package ids of packages for which an additional constraint argument is not required')

    # Create a subparser for the 'delete' command
    parser_delete = subparsers.add_parser('delete', help='Delete a specific version of a package')
    parser_delete.add_argument('package_id', type=str, help='Identifier of package to delete, separate hierarchy components with a colon')

    # Create a subparser for the 'reset' command
    parser_reset = subparsers.add_parser('reset', help='Reset a specific version of a package')
    parser_reset.add_argument('package_id', type=str, help='Identifier of package to reset, separate hierarchy components with a colon')

    # Create a subparser for the 'custom_test' command
    parser_custom_test = subparsers.add_parser('custom_test', help='Reset a specific version of a package')
    parser_custom_test.add_argument('-l', '--list', action='store_true', help='Show available custom tests')
    parser_custom_test.add_argument('-p', '--print', action='store_true', help='Print previous results for selected test')
    parser_custom_test.add_argument('-w', '--write-result', action='store_true', help='Write result for previously completed jobid (this action is intended for internal use, note: -j/--jobid MUST be set)')
    parser_custom_test.add_argument('-j', '--jobid', type=int, help='Slurm jobid (must be an int, this parameter is ignored if -w/--write-result is not set)')
    parser_custom_test.add_argument('-a', '--all', action='store_true', help='Run all custom tests (including all variants)')
    parser_custom_test.add_argument('-v', '--variant', action='store_true', help='Specify a variant of a test')
    parser_custom_test.add_argument('test_name', nargs='?', type=str, help='Selected test (format: TEST_NAME[:VARIANT])')
    parser_custom_test.add_argument('-P', '--parsable', action='store_true', help='Use a parsable table format (only applicable if -p/--print is specified)')
    parser_custom_test.add_argument('--field-delimiter', type=str, default='|', help='Only used if -P/--parsable is specified, default is \'|\'')
    parser_custom_test.add_argument('-i', '--limit-per', type=int, help='Only used if -p/--print is specified')
    parser_custom_test.add_argument('--sbatch-args', action='append', help='Additional sbatch arg to be used for custom_test single-instance runs (invoke once per sbatch arg [i.e.: -s arg1 -s arg2 ... ])')
    parser_custom_test.add_argument('-d', '--delete', action='store_true', help='Delete test results for specified TEST_NAME[:VARIANT]')

    # Create a subparser for the 'config' command
    parser_config = subparsers.add_parser('config', help='Get a config value')
    parser_config.add_argument('specifier', type=str, help='Specifier to apply to the config file (example: \'general:debug_level\')')
    parser_config.add_argument('-p', '--parsable', action='store_true', help='Will print primitive types without any formatting')

    args = parser.parse_args()

    if args.config_path is None:
        if os.environ.get('PKGTST_CONFIG_PATH'):
            args.config_path = os.environ.get('PKGTST_CONFIG_PATH')
        else:
            args.config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')

    logger = Logger(config_path=args.config_path)

    logger.log(LogLevel.INFO, f"using config {args.config_path}")

    # Handle the arguments based on the command
    if args.command == 'report':
        reporter = ReportGen(config_path=args.config_path)
        if args.set_warn_only or args.reset_warn_only or args.show_warn_only:
            if args.show_warn_only:
                reporter.show_warn_only()
            elif (args.set_warn_only or args.reset_warn_only) and args.package_id:
                filters = get_filters(args.package_id)
                reporter.set_warn_only(filters, args.set_warn_only)
            else:
                sys.stderr(f"ERROR: package_id must be specified on the command-line\n")
                return 1
        elif args.last_log:
            runner = SlurmRunner(config_path=args.config_path)
            runner.dump_last_log(args.package_id)
        else:
            filters = get_filters(args.package_id)
            reporter.print_table(
                filters=filters,
                sort_keys=args.sort_keys,
                reverse=args.reverse,
                limit=args.limit,
                limit_per=args.limit_per,
                parsable=args.parsable,
                field_delimiter=args.field_delimiter,
                fails_only=args.fails_only,
                case_insensitive=args.case_insensitive,
                render_jinja=args.render_jinja,
                template_path=args.template_path,
                no_truncation=args.no_truncation
            )
        return 0
    elif args.command == 'enumerate' or args.command == 'test':

        if args.command == 'test' or not args.show_required_constraints:

            # read config file
            config_path = args.config_path
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    ignore_paths = config['general']['ignore_paths']
            else:
                ignore_paths = None

            fi = FileInt(config=args.config_path)
            h = Hierarchy(config_path=args.config_path)

            pkgs = fi.get_hierarchy(ignore_paths)

        if args.command == 'enumerate':

            if not args.show_required_constraints:

                if args.filter_constraint or args.filter_no_constraint:
                    runner = SlurmRunner(config_path=args.config_path)
                    constraint_mappings = runner.req_constraints
                    # constraints[package_id]: constraint
                    constraints = dict()
                    for row in constraint_mappings:
                        for p in row['package_ids']:
                            constraints[p] = row['constraint']

                for row in pkgs:

                    package_id = ':'.join([row[component] for component in h.components])

                    if args.filter_constraint and \
                       (package_id not in constraints or \
                        constraints[package_id] != args.filter_constraint):
                        continue

                    if args.filter_no_constraint and package_id in constraints:
                        continue
                    
                    try:
                        sys.stdout.write(f"{package_id}\n")
                    except BrokenPipeError:
                        pass
                return 0

            else:
                runner = SlurmRunner(config_path=args.config_path)
                runner.print_req_constraints()
                return 0
                
        elif args.command == 'test':

            # 4 scenarios:
            # 1. all + no_slurm
            # 2. all + slurm
            # 3. one + no_slurm
            # 4. one + slurm

            if args.all:

                if not args.slurm:
                    for row in pkgs:
                        package_id = ':'.join([row[component] for component in h.components])
                        do_test(package_id, False, args.config_path)
                elif args.slurm:
                    runner = SlurmRunner(config_path=args.config_path)
                    pkgs = [ ':'.join([row[component] for component in h.components]) for row in pkgs ]
                    runner.exec_all(pkgs)

            else:

                if not args.package_id:
                    logger.log(LogLevel.ERROR, f"if not using the -a/--all option, must set package_id on the cmd-line")
                    return
                
                if not args.slurm:
                    do_test(args.package_id, False, args.config_path)
                else:
                    runner = SlurmRunner(config_path=args.config_path)
                    runner.exec_one(args.package_id)
        else:
            raise Exception(f"unexpected args.command ({args.command})")
            return 1
    
    elif args.command == 'delete':

        filters = get_filters(args.package_id)

        fi = FileInt(config=args.config_path)
        fi.delete(filters)
        reporter = ReportGen(config_path=args.config_path)
        reporter.delete_package(args.package_id.split(":"))
        return 0
    elif args.command == 'reset':
        do_test(args.package_id, True, args.config_path)
        return 0
    elif args.command == 'custom_test':
        ct = CustomTest(config_path=args.config_path)

        if args.list:
            ct.list_tests()
        elif args.print:
            reporter = ReportGen(config_path=args.config_path)
            reporter.print_ct_table(test_name=args.test_name,
                                    parsable=args.parsable,
                                    field_delimiter=args.field_delimiter,
                                    limit_per=args.limit_per)
        elif args.write_result:
            reporter = ReportGen(config_path=args.config_path)
            passed = ct.get_job_result(args.jobid)
            print(f"custom_test {args.test_name} Slurm job with jobid #{args.jobid} passed?: {passed}")
            reporter.write_ct_result(args.test_name, passed)
        elif args.delete:
            reporter = ReportGen(config_path=args.config_path)
            reporter.delete_ct(args.test_name)
        else:

            # The default action will be to run the selected test
            reporter = ReportGen(config_path=args.config_path)
            if not args.all:
                passed = ct.run_test(args.test_name, extra_args=args.sbatch_args)
                reporter.write_ct_result(args.test_name, passed)
            else:
                jobids = []
                for test_name in ct.get_test_names():
                    jobid = ct.run_test(test_name, do_wait=False)
                    jobids.append(jobid)
                dep_str = f"afterany:{':'.join([str(jobid) for jobid in jobids])}"
                runner = SlurmRunner(config_path=args.config_path)
                runner.render_job(dep_str)
        return 0
    elif args.command == 'config':
        cu = ConfigUtil(config_path=args.config_path)
        cu.print_value(args.specifier, parsable=args.parsable)
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    main()
