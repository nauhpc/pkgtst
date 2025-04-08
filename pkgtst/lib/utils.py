# utils.py

# For common utility functions across multiple scripts

import os

def get_pkgtst_root():
    
    root = os.getcwd()

    var = os.getenv("PKGTST_ROOT")

    if var is not None and os.path.isdir(var):
        root = var

    return root
