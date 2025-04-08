# config.py

# For the config subcommand

import os
import yaml
import pprint
import sys

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel

class ConfigUtil:
    def __init__(self, config_path=None):

        self.logger = Logger(config_path=config_path)
        
        if config_path is None:
            self.config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')
        else:
            self.config_path = config_path

        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        else:
            self.logger.log(LogLevel.ERROR, 'No config file found :\'(')

    def get_value(self, specifier):
        if not isinstance(specifier, str):
            self.logger.log(LogLevel.ERROR, f'in ConfigUtil::get_value() the specifier argument must be a string')

        specifier = specifier.strip()

        data = self.config

        for key in specifier.split(':'):
            try:
                key = int(key)
            except ValueError:
                pass
            data = data[key]

        return data

    def is_primitive(self, value):
        return isinstance(value, (int, float, bool, str, bytes))

    def print_value(self, specifier, parsable=False):

        value = self.get_value(specifier)

        if parsable and self.is_primitive(value):
            sys.stdout.write(f"{value}\n")
        else:
            pprint.pprint(value)
