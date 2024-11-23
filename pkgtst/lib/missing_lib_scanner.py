# finds missing libs

import os
import subprocess
import re
from multiprocessing import Pool
import sys


class MissingLibScanner:

    def __init__(self, config=None):

        if config:
            self.config_path = config
        else:
            self.config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'missing_lib_scanner.yaml')
        
        self.cpu_cores = 4
        self.verbose = False
        self.debug = False
        self.elf_magic_number = bytes.fromhex('7f454c46')
        self.ld_library_path = None
        self.silent = False

    def check_libs(self, filepath):
        command = ["ldd", "--", filepath]

        if self.ld_library_path is None:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        else:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, env={'LD_LIBRARY_PATH': self.ld_library_path})

        target = ' => not found'

        bad_libs = []
        
        for line in result.stdout.split('\n'):
            if line.endswith(target):
                match = line[0:len(line) - len(target)]
                match = match.strip()
                bad_libs.append(match)

        return bad_libs

    # all ELF executables are identifiable by their magic number
    # the first four bytes must be: 7f 45 4c 46
    # see: https://unix.stackexchange.com/questions/153352/what-is-elf-magic
    # see: https://en.wikipedia.org/wiki/Executable_and_Linkable_Format
    # or if you're up for some dense reading run "man 5 elf"
    def is_elf(self, filepath):
        try:
            with open(filepath, 'rb') as fp:
                magic_number = fp.read(4)
                return self.elf_magic_number == magic_number
        except:
            return False

    def process_filepath(self, filepath):
        is_elf = self.is_elf(filepath)
        if not self.silent:
            print(f"{filepath} is_elf: {is_elf}")
        if(is_elf):
            bad_libs = self.check_libs(filepath)
            for bad_lib in bad_libs:
                if not self.silent:
                    print(f"library {bad_lib} is missing for ELF executable {filepath}")
            return bad_libs

    def scan(self, filepaths, ld_library_path=None):
        
        old_ld_library_path = self.ld_library_path
        self.ld_library_path = ld_library_path

        results = []

        for filepath in filepaths:
            print(f"filepath: {filepath}")
            if os.path.exists(filepath):
                if os.path.isdir(filepath):
                    directory = filepath
                    for root, dirs, files in os.walk(directory):
                        for myfile in files:
                            fullpath = os.path.join(root, myfile)
                            bad_libs = self.process_filepath(fullpath)
                            if bad_libs:
                                results.append({'path': fullpath,
                                                'missing_libs': bad_libs})
                else:
                    bad_libs = self.process_filepath(filepath)
                    if bad_libs:
                        results.append({'path': filepath,
                                        'missing_libs': bad_libs})
            else:
                sys.stderr.write(f"ERROR: {filepath} does not exist\n")

        # restore old value
        self.ld_library_path = old_ld_library_path

        return results

    def set_silent(self, setting):
        self.silent = setting
