# logger.py

import os
import sys
import yaml
import enum

from pkgtst.lib.utils import get_pkgtst_root

class LogLevel(enum.IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    VERBOSE = 4
    TRACE = 5

class Logger:
    def __init__(self, config_path=None, skip_config_parse=False):

        # only in case we need to log something before this function completes
        self.debug_level = LogLevel.ERROR

        if skip_config_parse:
            return

        if config_path is None or not isinstance(config_path, str):
            if os.environ.get('PKGTST_CONFIG_PATH'):
                config_path = os.environ.get('PKGTST_CONFIG_PATH')
            else:
                config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')

        try:

            if not os.path.exists(config_path):
                self.log(LogLevel.ERROR, f"Configuration file does not exist at {config_path}")

            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            if config['general']['debug_level'] is None or not isinstance(config['general']['debug_level'], str):
                self.debug_level = LogLevel.ERROR
            else:
                if config['general']['debug_level'] == 'ERROR':
                    self.debug_level = LogLevel.ERROR
                elif config['general']['debug_level'] == 'WARNING':
                    self.debug_level = LogLevel.WARNING
                elif config['general']['debug_level'] == 'INFO':
                    self.debug_level = LogLevel.INFO
                elif config['general']['debug_level'] == 'VERBOSE':
                    self.debug_level = LogLevel.VERBOSE
                elif config['general']['debug_level'] == 'TRACE':
                    self.debug_level = LogLevel.TRACE
                else:
                    self.log(LogLevel.ERROR, f"bad debug_level: {config['general']['debug_level']}")

        except Exception as e:
            self.log(LogLevel.ERROR, f"Unexpected exception in Logger::__init__, self.debug_level {self.debug_level.name}")

    def log(self, level, msg):

        msg = str(msg) # attempt to convert to string
        
        if level <= self.debug_level:
            for line in msg.splitlines():
                sys.stderr.write(f"{level.name}: {line}\n")

        if level == LogLevel.ERROR:
            sys.stderr.flush()
            exit(1)
