# slurm_runner.py

import re
import os
import sys
import yaml
import subprocess
import pathlib
import shlex
import datetime
import glob
import shlex
import pprint

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel
from pkgtst.lib.utils import get_pkgtst_root

class SlurmRunner:
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

        self.array_task_throttle = self.config['slurm_runner']['array_task_throttle']
        self.req_constraints = self.config['slurm_runner']['req_constraints']
        self.output_dir = self.config['slurm_runner']['output_dir']

        self.email = self.config['general']['email']

        if not os.path.isdir(self.output_dir):
            self.logger.log(LogLevel.ERROR, f"SlurmRunner's output_dir ({self.output_dir}) does not exist or is not a directory")

    def is_valid_email(self, email):
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(email_regex, email) is not None

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

    def exec_all(self, pkgs):

        if self.email is not None and isinstance(self.email, str):
            if self.is_valid_email(self.email):
                self.run_cmd(f"printf '%s\\n' \"$(date)\" \"Running as $(whoami)\" | mailx -s 'executing '\\''pkgtst is running SlurmRunner::exec_all (#pkgs: {len(pkgs)})'\\''' {self.email}")

        # clean up log files from previous runs of this function
        for old_logfile in glob.glob(f"{self.output_dir}/pkgtst_test_*.log"):

            # redundant checks for safety
            
            if not os.path.isfile(old_logfile):
                continue

            basename = os.path.basename(old_logfile)
            if not (basename.startswith('pkgtst_test_') or basename.endswith('.log')):
                continue

            self.logger.log(LogLevel.VERBOSE, f"Removing: {old_logfile}")
            os.remove(old_logfile)

        # we have to categorize these packages based on the self.req_constraints (if set)
        if self.req_constraints is not None and isinstance(self.req_constraints, list):

            # constraints[constraint] = <list-of-pkgs>
            constraints = dict()
            seen_pkgs = set()
            for row in self.req_constraints:
                constraint = row['constraint']
                constraints[constraint] = row['package_ids']
                seen_pkgs |= set(row['package_ids'])

            pkgs = [pkg for pkg in pkgs if pkg not in seen_pkgs]
            self.exec_array(pkgs, script_args=['--filter-no-constraint'])

            for constraint in constraints:
                self.exec_array(constraints[constraint], sbatch_args=[f"--constraint={constraint}"], script_args=[f"--filter-constraint={constraint}"])
                    
        else:
            self.exec_array(pkgs)
        

    def exec_array(self, pkgs, sbatch_args=[], script_args=[]):

        self.logger.log(LogLevel.VERBOSE, f"in SlurmRunner::exec_array() -- #pkgs: {len(pkgs)}, sbatch_args: {sbatch_args}, script_args={script_args}")

        if pkgs is None or not isinstance(pkgs, list):
            self.logger.log(LogLevel.ERROR, 'the pkgs argument for SlurmRunner::exec_all() must be a list in order to test packages')

        DIRNAME = get_pkgtst_root()
        N = len(pkgs)
        output_file = os.path.join(self.output_dir, 'arrays', 'pkgtst_combined_%A.log')

        array_arg = f"1-{N}%{int(self.array_task_throttle)}"
        job_script = os.path.join(DIRNAME, 'etc', 'pkgtst_array.sh')

        sbatch_args = [shlex.quote(sbatch_arg) for sbatch_arg in sbatch_args]
        script_args = [shlex.quote(script_arg) for script_arg in script_args]
        
        cmd = f"sbatch {' '.join(sbatch_args)} --array={shlex.quote(array_arg)} --output={shlex.quote(output_file)} {shlex.quote(job_script)} {' '.join(script_args)} | awk '{{ print $4 }}'"
        stdout, stderr, exit_code = self.run_cmd(cmd)
        try:
            jobid = int(stdout.strip())
        except:
            self.logger.log(LogLevel.ERROR, "unable to parse jobid, per-package job array submission likely failed")

        self.logger.log(LogLevel.INFO, f"Package test job array's jobid: {jobid}")

        date_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        output_file = os.path.join(self.output_dir, 'render_jobs', f"render_jinja_{date_str}.log")
        dep_str = f"afterany:{jobid}"

        cmd = f"sbatch --time=5 --job-name='render_jinja' --dependency={shlex.quote(dep_str)} --wrap='pkgtst report --render-jinja' --output={shlex.quote(output_file)}"
        stdout, stderr, exit_code = self.run_cmd(cmd)

        if exit_code != 0:
            self.logger.log(LogLevel.ERROR, 'cmd to submit render-jinja job failed')

    def exec_one(self, package_id):

        if package_id is None or not isinstance(package_id, str):
            self.logger.log(LogLevel.ERROR, 'package_id must be a string')

        DIRNAME = get_pkgtst_root()
        job_script = os.path.join(DIRNAME, 'etc', 'pkgtst_single.sh')

        sbatch_args = []

        for setting in self.req_constraints:
            constraint_arg = setting['constraint']
            if package_id in setting['package_ids']:
                sbatch_args = [ f'--constraint={constraint_arg}' ]

        sbatch_args = [shlex.quote(arg) for arg in sbatch_args]

        cmd = f"sbatch {' '.join(sbatch_args)} {shlex.quote(job_script)} {shlex.quote(package_id)} | awk '{{ print $4 }}'"
        stdout, stderr, exit_code = self.run_cmd(cmd)
        try:
            jobid = int(stdout.strip())
        except:
            self.logger.log(LogLevel.ERROR, "unable to parse jobid, single-package job submission likely failed")

        self.logger.log(LogLevel.INFO, f"Package test job jobid (for {package_id}): {jobid}")

    def render_job(self, dep_str):
        DIRNAME = get_pkgtst_root()
        output_file = os.path.join(self.output_dir, 'custom_test_watier_%A.log')
        
        cmd = f"sbatch --time=5 --job-name='render_jinja' --dependency={shlex.quote(dep_str)} --wrap='pkgtst report --render-jinja' --output={shlex.quote(output_file)}"
        stdout, stderr, exit_code = self.run_cmd(cmd)

        if exit_code != 0:
            self.logger.log(LogLevel.ERROR, 'cmd to submit render-jinja job failed')

    def print_req_constraints(self):

        pprint.pprint(self.req_constraints)

    def dump_last_log(self, package_id):
        if not isinstance(package_id, str):
            self.logger.log(LogLevel.ERROR, "in SlurmRunner::dump_last_log() -- package_id must be a string")

        package_id = package_id.replace(':', '_')
        
        files = [f for f in glob.glob(f"{self.output_dir}/tests/pkgtst_test_{package_id}_*.log")]
        files = sorted(files)

        try:
            last_log_file = files[-1]
        except IndexError:
            self.logger.log(LogLevel.INFO, 'No last log file')
            return

        self.logger.log(LogLevel.VERBOSE, f"last_log: {last_log_file}")
        with open(last_log_file, 'r') as fp:
            try:
                sys.stdout.write(f"{fp.read()}\n")
                sys.stdout.flush()
            except BrokenPipeError:
                sys.stdout.close()
