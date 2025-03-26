# slurm_ezec_all.py

import re
import os
import yaml
import subprocess
import pathlib
import shlex
import datetime
import glob

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel

class SlurmRunner:
    def __init__(self, config_path=None):
        self.logger = Logger(config_path=config_path)

        if config_path:
            self.config_path = config_path
        else:
            self.config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'pkgtst.yaml')

        if not os.path.exists(self.config_path):
            self.logger.log(LogLevel.ERROR, f"Configuration file does not exist at {self.config_path}")

        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.array_task_throttle = self.config['fileint']['array_task_throttle']

        self.email = self.config['general']['email']

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

    # def exec_all(self, pkgs, skip_custom_tests=False):
    def exec_all(self, pkgs=None, skip_package_tests=False, skip_custom_tests=False):

        if self.email is not None and isinstance(self.email, str):
            if self.is_valid_email(self.email):
                self.run_cmd(f"printf '%s\\n' \"$(date)\" \"Running as $(whoami)\" | mailx -s 'executing '\\''pkgtst slurm_exec_all (skip_package_tests: {skip_package_tests}, skip_custom_tests: {skip_custom_tests})'\\''' {self.email}")

        self.logger.log(LogLevel.INFO, f"in SlurmRunner::exec_all() -- skip_package_tests: {skip_package_tests}, skip_custom_tests: {skip_custom_tests}")

        if skip_package_tests and skip_custom_tests:
            self.logger.log(LogLevel.INFO, f"Nothing to do")

        if not skip_package_tests:

            if pkgs is None or not isinstance(pkgs, list):
                self.logger.log(LogLevel.ERROR, 'the pkgs argument for SlurmRunner::exec_all() must be a list in order to test packages')

            DIRNAME = str(pathlib.Path(__file__).resolve().parent.parent.parent)
            N = len(pkgs)
            output_file = os.path.join(DIRNAME, 'logs', 'pkgtst_combined.log')

            # clean up log files from previous runs of this function
            logdir = os.path.join(DIRNAME, 'logs')
            for old_logfile in glob.glob(f"{logdir}/pkgtst_test_*.log"):
                # redundant checks for safety
                
                if not os.path.isfile(old_logfile):
                    continue
                
                basename = os.path.basename(old_logfile)
                if not (basename.startswith('pkgtst_test_') or basename.endswith('.log')):
                    continue

                self.logger.log(LogLevel.VERBOSE, f"Removing: {old_logfile}")
                os.remove(old_logfile)

            array_arg = f"1-{N}%{int(self.array_task_throttle)}"
            job_script = os.path.join(DIRNAME, 'etc', 'job_script.sh')

            cmd = f"sbatch --array={shlex.quote(array_arg)} --output={shlex.quote(output_file)} {shlex.quote(job_script)} | awk '{{ print $4 }}'"
            stdout, stderr, exit_code = self.run_cmd(cmd)
            try:
                jobid = int(stdout.strip())
            except:
                self.logger.log(LogLevel.ERROR, "unable to parse jobid, per-package job array submission likely failed")

            self.logger.log(LogLevel.INFO, f"Package test job array's jobid: {jobid}")

            date_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            output_file = os.path.join(DIRNAME, "logs", f"render_jinja_{date_str}.log")
            dep_str = f"afterany:{jobid}"

            cmd = f"sbatch --time=5 --job-name='render_jinja' --dependency={shlex.quote(dep_str)} --wrap='pkgtst report --render-jinja' --output={shlex.quote(output_file)}"
            stdout, stderr, exit_code = self.run_cmd(cmd)

            if exit_code != 0:
                self.logger.log(LogLevel.ERROR, 'cmd to submit render-jinja job failed')

        if not skip_custom_tests:
            response = input("Are you sure that you want to continue with executing all custom_test runs? (yes/no): ")
            if response == 'yes':
                sys.stdout.write(f"Sorry, not yet able to fulfill this request\n")
            else:
                sys.stdout.write(f"Okay, bye\n")

    def exec_one(self, package_id):

        if package_id is None or not isinstance(package_id, str):
            self.logger.log(LogLevel.ERROR, 'package_id must be a string')

        DIRNAME = str(pathlib.Path(__file__).resolve().parent.parent.parent)
        job_script = os.path.join(DIRNAME, 'etc', 'test_pkg.sh')

        cmd = f"sbatch {shlex.quote(job_script)} {shlex.quote(package_id)} | awk '{{ print $4 }}'"
        stdout, stderr, exit_code = self.run_cmd(cmd)
        try:
            jobid = int(stdout.strip())
        except:
            self.logger.log(LogLevel.ERROR, "unable to parse jobid, single-package job submission likely failed")

        self.logger.log(LogLevel.INFO, f"Package test job jobid (for {package_id}): {jobid}")

    def render_job(self, dep_str):
        DIRNAME = str(pathlib.Path(__file__).resolve().parent.parent.parent)
        output_file = os.path.join(DIRNAME, 'logs', 'custom_test_watier_%A.log')
        
        cmd = f"sbatch --time=5 --job-name='render_jinja' --dependency={shlex.quote(dep_str)} --wrap='pkgtst report --render-jinja' --output={shlex.quote(output_file)}"
        stdout, stderr, exit_code = self.run_cmd(cmd)

        if exit_code != 0:
            self.logger.log(LogLevel.ERROR, 'cmd to submit render-jinja job failed')
