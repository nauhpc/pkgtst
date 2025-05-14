# custom_test.py

import os
import glob
import pathlib
import yaml
import shlex
import subprocess

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel
from pkgtst.lib.utils import get_pkgtst_root

class CustomTest:

    def __init__(self, config_path=None):
        self.logger = Logger(config_path=config_path)

        if config_path:
            self.config_path = config_path
        else:
            self.config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')

        if not os.path.exists(self.config_path):
            self.logger.log(LogLevel.ERROR, f"Configuration file does not exist at {self.config_path}")

        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.script_dir = self.config['custom_test']['script_dir']
        self.output_dir = self.config['custom_test']['output_dir']
        self.jobid = None
        self.results_dir = None

        self.logger.log(LogLevel.INFO, f"self.script_dir = {self.script_dir}")

        if self.script_dir is None or \
           not isinstance(self.script_dir, str) or \
           not os.path.exists(self.script_dir):
            self.logger.log(LogLevel.ERROR, f"custom_test:script_dir does not point to a valid path")

        if self.output_dir is None or \
           not isinstance(self.output_dir, str) or \
           not os.path.exists(self.output_dir):
            self.logger.log(LogLevel.ERROR, f"custom_test:output_dir does not point to a valid path")

        if self.config['custom_test']['results_dir'] is not None:
            if isinstance(self.config['custom_test']['results_dir'], str):
                self.results_dir = self.config['custom_test']['results_dir']

    def list_tests(self):

        for script in glob.glob(self.script_dir + "/*.sh"):
            self.logger.log(LogLevel.TRACE, f"found {script}")
            script = script[len(self.script_dir)+1:]
            basename = script[0:-3]
            yaml_file = None
            variants = None
            ypath = os.path.join(self.script_dir, basename + ".yaml")
            if os.path.exists(ypath):
                variants = []
                self.logger.log(LogLevel.TRACE, f'found {ypath}')
                yaml_file = basename + ".yaml"
                with open(ypath) as fp:
                    settings = yaml.safe_load(fp)
                if 'variants' in settings:
                    if settings['variants']['type'] == 'slurm_feature':
                        for element in settings['variants']['value']:
                            variants.append(element)
                    elif settings['variants']['type'] == 'slurm_feature_w_args':
                        for element in settings['variants']['value']:
                            variants.append(element['feature'])
            print(f"test_name: {basename}\n\tscript: {script}\n\tyaml: {yaml_file}\n\tvariants: {variants}\n")

    def get_test_names(self):
        tests = []
        for script in glob.glob(self.script_dir + "/*.sh"):
            self.logger.log(LogLevel.TRACE, f"found {script}")
            script = script[len(self.script_dir)+1:]
            basename = script[0:-3]
            yaml_file = None
            variants = None
            ypath = os.path.join(self.script_dir, basename + ".yaml")
            if os.path.exists(ypath):
                variants = []
                self.logger.log(LogLevel.TRACE, f'found {ypath}')
                yaml_file = basename + ".yaml"
                with open(ypath) as fp:
                    settings = yaml.safe_load(fp)
                if 'variants' in settings:
                    if settings['variants']['type'] == 'slurm_feature':
                        for element in settings['variants']['value']:
                            variants.append(element)
                    elif settings['variants']['type'] == 'slurm_feature_w_args':
                        for element in settings['variants']['value']:
                            variants.append(element['feature'])
            if variants is None or len(variants) == 0:
                tests.append(basename)
            else:
                for variant in variants:
                    tests.append(f"{basename}:{variant}")

        return tests

    def add_prefix_to_lines(self, input_string, prefix):

        # Split the input string into lines
        lines = input_string.split('\n')

        # Add the prefix to each line
        prefixed_lines = [prefix + line for line in lines]

        # Join the lines back together into a single string
        output_string = '\n'.join(prefixed_lines)

        return output_string

    def run_cmd(self, cmd):

        self.logger.log(LogLevel.VERBOSE, self.add_prefix_to_lines(cmd, "CMD: "))

        # Execute the cmd in a bash shell
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Capture stdout and stderr
        stdout, stderr = process.communicate()

        # Get the exit code
        exit_code = process.returncode

        # Decode stdout and stderr from bytes to string
        stdout = stdout.decode('utf-8')
        stderr = stderr.decode('utf-8')

        self.logger.log(LogLevel.VERBOSE, self.add_prefix_to_lines(stdout, "STDOUT: "))
        self.logger.log(LogLevel.VERBOSE, self.add_prefix_to_lines(stderr, "STDERR: "))
        self.logger.log(LogLevel.VERBOSE, self.add_prefix_to_lines(str(exit_code), "EXIT_CODE: "))

        return stdout, stderr, exit_code

    def run_test(self, test_name, extra_args=None, do_wait=True):

        if test_name is None or not isinstance(test_name, str):
            self.logger.log(LogLevel.ERROR, f"{test_name} must be a string")

        variant = None

        if ":" in test_name:
            index = test_name.find(":")
            variant = test_name[index + 1:]
            test_name = test_name[:index]

        script_name = test_name + '.sh'
        script_path = os.path.join(self.script_dir, script_name)

        if not os.path.exists(script_path):
            self.logger.log(LogLevel.ERROR, f"{script_path} does not exist")

        # define sbatch arguments
        sbatch_args = [ f"--job-name={shlex.quote(test_name)}" ]
        sbatch_args += [ "--parsable" ]

        if do_wait:
            sbatch_args += [ "--wait" ]

        # placeholder, to be populated if we see a slurm_feature_w_args variant
        script_args = []

        # check if we have a slurm variant to use
        yaml_path = os.path.join(self.script_dir, test_name + ".yaml")
        if not os.path.exists(yaml_path):
            self.logger.log(LogLevel.INFO, f"{yaml_path} does not exist (proceeding with defaults)")
        else:
            
            with open(yaml_path) as fp:
                settings = yaml.safe_load(fp)

            if self.results_dir is not None:
                # check that this arg isn't configured to be ignored
                if 'ignore_results_dir' not in settings or not settings['ignore_results_dir']:
                    results_dir = os.path.join(self.results_dir, test_name)
                    if not os.path.exists(results_dir):
                        os.makedirs(results_dir)
                    script_args += [ f"--results-dir={results_dir}" ]

            if 'variants' in settings:
            
                if settings['variants']['type'] == 'slurm_feature':
                    if variant is not None and variant in settings['variants']['value']:
                        sbatch_args += [ f"--constraint={variant}" ]
                if settings['variants']['type'] == 'slurm_feature_w_args':

                    if variant is None:
                        self.logger.log(LogLevel.ERROR, f"ERROR: you must specify a variant for test_name '{test_name}'")
                    
                    possible_variants = set()
                    arg_lists = dict()
                    sbatch_arg_lists = dict()
                    for element in settings['variants']['value']:
                        possible_variants.add(element['feature'])
                        arg_lists[element['feature']] = element['args']
                        sbatch_arg_lists[element['feature']] = element['sbatch_args']
                    if variant is not None and variant in possible_variants:

                        sbatch_args += [ f"--constraint={variant}" ]

                        script_args += arg_lists[variant]
                        sbatch_args += sbatch_arg_lists[variant]

        if variant is not None:
            sbatch_args += [f"--output={self.output_dir}/{test_name}.{variant}_%A.txt"]
        else:
            sbatch_args += [f"--output={self.output_dir}/{test_name}_%A.txt"]

        # finally, add anything from the extra_args argument for this function
        if extra_args is not None and isinstance(extra_args, list):
            sbatch_args += [shlex.quote(i) for i in extra_args]

        sbatch_args = [shlex.quote(i) for i in sbatch_args]
        script_args = [shlex.quote(i) for i in script_args]

        cmd = f"sbatch {' '.join(sbatch_args)} {shlex.quote(script_path)} {' '.join(script_args)}"

        # run the script
        self.logger.log(LogLevel.INFO, f"launching job with cmd: {cmd} (this may take a while)")
        stdout, stderr, exit_code = self.run_cmd(cmd)

        try:
            stdout = stdout.strip()
            jobid = int(stdout)
        except:
            self.logger.log(LogLevel.ERROR, f"unable to parse jobid, custom_test submission likely failed for {test_name}")

        if exit_code == 0:
            # SUCCESS :))
            passed = True
            if do_wait:
                print(f"{test_name} -- PASS")
        else:
            # FAIL :((
            passed = False
            if do_wait:
                print(f"{test_name} -- FAIL")

        if do_wait:
            return passed
        else:
            
            # submit dependent job that waits for the current jobid, and runs the cmd:
            # pkgtst custom_test TESTNAME --write-result=JOBID

            test_id = test_name
            if variant:
                test_id += f":{variant}"

            sbatch_args = [ '--time=1' ]
            sbatch_args += [ f"--output={self.output_dir}/{test_name}_waiter_%A.txt" ]
            sbatch_args += [ f"--dependency=afterany:{shlex.quote(str(jobid))}" ]
            sbatch_args += [ f"--wrap=pkgtst custom_test {shlex.quote(test_id)} --write-result --jobid={shlex.quote(str(jobid))}" ]

            sbatch_args = [shlex.quote(i) for i in sbatch_args]
            
            cmd = f"sbatch {' '.join(sbatch_args)} | awk '{{ print $4 }}'"

            self.logger.log(LogLevel.INFO, f"launching job with cmd: {cmd} (this may take a while)")
            stdout, stderr, exit_code = self.run_cmd(cmd)

            try:
                waiter_jobid = int(stdout.strip())
            except:
                self.logger.log(LogLevel.ERROR, f"unable to parse waiter_jobid, custom_test submission likely failed for write_results job for test name {test_name}")

            return waiter_jobid

    def get_job_result(self, jobid):

        if not isinstance(jobid, int):
            self.logger.log(LogLevel.ERROR, f"in CustomTest::get_job_result() jobid must be an int!")

        cmd = f'sacct -j {shlex.quote(str(jobid))} -n -X -P -o ExitCode'

        stdout, stderr, exit_code = self.run_cmd(cmd)

        stdout = stdout.strip()

        if stdout == "0:0":
            passed = True
        else:
            passed = False

        return passed
