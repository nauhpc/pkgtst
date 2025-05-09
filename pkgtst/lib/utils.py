# utils.py

# For common utility functions across multiple scripts

import os

def get_pkgtst_root():

    root = os.getenv("PKGTST_ROOT")

    if root is not None and os.path.isdir(root):
        return root
    else:
        # We are not using the logger class here, because it depends on reading
        # values from the config file
        from pkgtst.lib.logger import LogLevel
        from pkgtst.lib.logger import Logger
        logger = Logger(skip_config_parse=True)
        logger.log(LogLevel.ERROR, f"PKGTST_ROOT is not set to a valid directory (value: {root})")
