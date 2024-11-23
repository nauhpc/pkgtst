#!/usr/bin/env python3

from lib.fileint import FileInt
from lib.fileint import Hierarchy
from lib.missing_lib_scanner import MissingLibScanner
from lib.report_gen import ReportGen

import argparse
import sys
import subprocess
import os
import yaml
import shlex

def get_command_output(command):
    # Execute the command and get the output
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    
    # Return the output as a single line
    return result.stdout.strip()

# returns a set of filters for a package id string
def get_filters(package_id_string):

    if package_id_string is None:
        return None
    
    components = package_id_string.split(":")

    h = Hierarchy()

    if len(h.components) != len(components):
        raise Exception(f"ERROR: package_id '{package_id_string}' does not match hierarchy {h.components}")

    filters = []
    for i in range(len(h.components)):
        component = h.components[i]
        value = components[i]
        filters.append({"hierarchy": component, "value": value})

    return filters

def do_test(package_id_string, do_reset=False):

    filters = get_filters(package_id_string)

    # read config file
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'pkgtst.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            ignore_paths = config['general']['ignore_paths']
    else:
        ignore_paths = None

    # 1. check the file integrity
    fi = FileInt()
    fi_results = fi.read_paths(filters, do_reset)

    print(f"PROCESSING PACKAGE: {package_id_string}")

    # 2. find a modulefile and use its LD_LIBRARY_PATH if any for the
    #    next step

    # we'll assume a module name to be "{component1}/{component2}/..."
    h = Hierarchy()
    lmod_arg = shlex.quote("/".join(h.components))
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
    mlc = MissingLibScanner()
    mlc.set_silent(True)
    pkg_base_paths = fi.get_filter_matches(filters)
    if len(pkg_base_paths) != 1:
        raise Exception(f"cancelling run, pkg_base_paths is {pkg_base_paths} (length is not one)")
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

    x = ReportGen()
    x.write_result([v for (k, v) in filters], pkg_base_paths[0], module_name, {'passed_fileint': passed_fileint, 'passed_lnfs': passed_lnfs})

def main():

    # Create the top-level parser
    parser = argparse.ArgumentParser(description='pkgtst - The Software Package Tester')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    # Create a subparser for the 'test' command
    parser_test = subparsers.add_parser('test', help='Test a specific version of a package')
    parser_test.add_argument('package_id', type=str, help='Identifier of package to test, separate hierarchy components with a colon')

    # Create a subparser for the 'print' command
    parser_print = subparsers.add_parser('report', help='Report test results')
    parser_print.add_argument('package_id', type=str, nargs='?', help='Identifier of package to print, separate hierarchy components with a colon')
    parser_print.add_argument('--render-jinja', action='store_true', help='Render the default jinja template')
    parser_print.add_argument('--template-path', type=str, help='Specify the path to the template instead of using the default template')
    parser_print.add_argument('--sort-keys', type=str, help='Colon-separated hierarchy components to sort by')
    parser_print.add_argument('--reverse', action='store_true', help='Reverse the order of the sort')
    parser_print.add_argument('--limit', type=int, help='The max number of runs to show')
    parser_print.add_argument('--limit-per', type=int, help='The max number of runs to show for each unique package')
    parser_print.add_argument('--parsable', action='store_true', help='Parsable table output')
    parser_print.add_argument('--field-delimiter', type=str, help='Only used if --parsable is specified, default is \'|\'')
    parser_print.add_argument('--fails-only', action='store_true', help='Only show rows where there is at least one failed test')
    parser_print.add_argument('--case-insensitive', action='store_true', help='Any field sorts will be case insensitive')
    # These edit the config file
    parser_print.add_argument('--set-warn-only', action='store_true', help='If package_id is set, will edit config to persistently set the package as warn-only (meaning it will not appear as an error in output)')
    parser_print.add_argument('--reset-warn-only', action='store_true', help='If package_id is set, will edit config to persistently remove the setting which specifies the package as warn-only (meaning it will appear as an error in output)')
    parser_print.add_argument('--show-warn-only', action='store_true', help='Show packages set to be \'warn-only\'')

    # Create a subparser for the 'enumerate' command
    parser_enumerate = subparsers.add_parser('enumerate', help='Enumerate packages')

    # Create a subparser for the 'delete' command
    parser_delete = subparsers.add_parser('delete', help='Delete a specific version of a package')
    parser_delete.add_argument('package_id', type=str, help='Identifier of package to delete, separate hierarchy components with a colon')

    # Create a subparser for the 'reset' command
    parser_reset = subparsers.add_parser('reset', help='Reset a specific version of a package')
    parser_reset.add_argument('package_id', type=str, help='Identifier of package to reset, separate hierarchy components with a colon')

    args = parser.parse_args()

    # Handle the arguments based on the command
    if args.command == 'test':
        do_test(args.package_id)
        return 0
    elif args.command == 'report':
        reporter = ReportGen()
        if args.set_warn_only or args.reset_warn_only or args.show_warn_only:
            if args.show_warn_only:
                reporter.show_warn_only()
            elif (args.set_warn_only or args.reset_warn_only) and args.package_id:
                filters = get_filters(args.package_id)
                reporter.set_warn_only(filters, args.set_warn_only)
            else:
                sys.stderr(f"ERROR: package_id must be specified on the command-line\n")
                return 1
        else:
            filters = get_filters(args.package_id)
            reporter.print_table(
                filters=filters,
                sort_keys=args.sort_keys,
                reverse=args.reverse,
                limit=args.limit,
                limit_per=args.limit_per,
                parseable=args.parsable,
                field_delimiter=args.field_delimiter,
                fails_only=args.fails_only,
                case_insensitive=args.case_insensitive,
                render_jinja=args.render_jinja,
                template_path=args.template_path
            )
        return 0
    elif args.command == 'enumerate':
        
        # read config file
        config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'pkgtst.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                ignore_paths = config['general']['ignore_paths']
        else:
            ignore_paths = None

        fi = FileInt()
        h = Hierarchy()
        
        for row in fi.get_hierarchy(ignore_paths):
            try:
                sys.stdout.write(f"{':'.join([row[component] for component in h.components])}\n")
            except BrokenPipeError:
                pass
        
        return 0
    
    elif args.command == 'delete':

        filters = get_filters(args.package_id)

        fi = FileInt()
        fi.delete(filters)
        return 0
    elif args.command == 'reset':
        do_test(args.package_id, True)
        return 0
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    main()
FileInt()
        fi.delete(filters)
        return 0
    elif args.command == 'reset':
        do_test(args.package_id, True)
        return 0
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    main()
