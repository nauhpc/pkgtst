# fileint - file integrity library

import os
import yaml
import sqlite3
import pathlib
import hashlib
import sys
import signal
import shlex
import enum
import pickle
import multiprocessing
import fcntl
import re

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel
from pkgtst.lib.utils import get_pkgtst_root

class MismatchType(enum.Enum):
    MISSING_ROW = 1
    EXTRA_ROW = 2
    MISSING_COLUMN = 3
    EXTRA_COLUMN = 4
    WRONG_VALUE = 5


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

# Used for the package directory hierarchy
class Hierarchy:
    
    def __init__(self, hierarchy_string=None, config_path=None):

        self.depth = 0               # how many directories make up the hierarchy
        self.pattern = None          # a regex pattern
        self.components = []         # named fields within the hierarchy

        if hierarchy_string is None:

            if config_path is None or not isinstance(config_path, str):
        
                config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')

            if not os.path.exists(config_path):
                raise Exception(f'ERROR: Configuration file does not exist at {config_path}')

            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            hierarchy_string = config['general']['hierarchy']

        # We're assuming Unix-like file paths
        # All chars are valid here except for null chars and forward slashes
        
        # Define regex to capture the identifiers and non-identifier text
        token_pattern = r'/|\{(\w+)\}|[^{}/]+'

        if '\x00' in hierarchy_string:
            raise Exception(f"ERROR: in Hierarchy::__init__: null char found!")

        self.pattern = "^"

        tokens = []
        for match in re.finditer(token_pattern, hierarchy_string):
            if match.group(0) == '/':
                tokens.append(('dir_split', match.group(0)))
                self.depth += 1
                self.pattern += r"(/)"
            elif match.group(1):
                if self.depth == 0:
                    self.depth = 1
                tokens.append(('identifier', match.group(1)))
                self.pattern += r"([^\x00/:]+)" # no null chars, forward slashes, or colons
                self.components.append(match.group(1))
            else:
                if self.depth == 0:
                    self.depth = 1
                tokens.append(('literal', match.group(0)))
                self.pattern += "(" + re.escape(match.group(0)) + ")"

        self.pattern += "$"

    def __str__(self):
        return f"Hierarchy(depth={self.depth}, pattern={self.pattern}, components={self.components})"

    def __repr__(self):
        return self.__str__()

    def is_match(self, abs_path=None, rel_path=None):
        if abs_path is not None and rel_path is not None:
            raise Exception(f"ERROR: in Hierarchy::is_match(): must either set abs_path or rel_path, not both")
        elif abs_path is not None:
            abs_path = os.path.normpath(abs_path)
            abs_path = abs_path.split(os.sep)
            rel_path = os.sep.join(abs_path[-self.depth:])

        return bool(re.fullmatch(self.pattern, rel_path))

class FileInt:

    def __init__(self, config=None):

        self.conn = None
        self.cursor = None
        self.invalidated = False
        self.max_diff_prints = None
        self.pool_size = 4

        if config:
            self.config_path = config
        else:
            self.config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')

        if not os.path.exists(self.config_path):
            raise Exception(f'ERROR: Configuration file does not exist at {self.config_path}')
        
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        if not self.config['fileint']['dbfile']:
            if self.config['fileint']['format'] != 'pickle':
                self.dbfile = os.path.join(get_pkgtst_root(), 'var', 'db', 'fileint.sql')
            else:
                self.dbfile = os.path.join(get_pkgtst_root(), 'var', 'db', 'fileint.pkl')
        else:
            self.dbfile = self.config['fileint']['dbfile']

        self.dbformat = self.config['fileint']['format']
        if self.config['fileint']['max_diff_prints']:
            self.max_diff_prints = self.config['fileint']['max_diff_prints']

        if self.config['fileint']['pool_size']:
            self.pool_size = self.config['fileint']['pool_size']

        self.path_limit = self.config['general']['path_limit']

        self.logger = Logger(config_path=config)

    def create_db(self):
        self.conn = sqlite3.connect(self.dbfile)
        self.cursor = self.conn.cursor()

        parent_db_schema = """CREATE TABLE IF NOT EXISTS fileint (
base_path TEXT NOT NULL PRIMARY KEY,"""
        if self.config['fileint']['hierarchy'] is not None and len(self.config['fileint']['hierarchy']) > 0:
            for hierarchy in self.config['fileint']['hierarchy']:
                parent_db_schema += f"\n{hierarchy} TEXT,"
            parent_db_schema += "\nhash_of_blob TEXT\n)"

        self.cursor.execute(parent_db_schema)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS file (
                relative_path TEXT NOT NULL,
                mode INT NOT NULL,
                mod_time INT NOT NULL,
                file_size INT NOT NULL,
                content_hash TEXT,
                base_path TEXT NOT NULL,
                UNIQUE (base_path, relative_path),
                FOREIGN KEY (base_path) REFERENCES fileint(base_path)
            )
        """)

        self.conn.commit()
        self.cursor.close()
        self.conn.close()

        self.logger.log(LogLevel.INFO, f"created database at {self.dbfile}")

    def db_connect(self):
        if not os.path.exists(self.dbfile):
            lock_file = self.dbfile + '.lock'
            with open(lock_file, 'w') as f:
                try:
                    # Acquire an exclusive lock on the lock file
                    fcntl.flock(f, fcntl.LOCK_EX)
                    
                    # Double-check if the database file exists
                    if not os.path.exists(self.dbfile):
                        self.create_db()
                    else:
                        self.logger.log(LogLevel.INFO, f"Database '{self.dbfile}' already exists.")
                finally:
                    # Release the lock
                    fcntl.flock(f, fcntl.LOCK_UN)
        else:
            self.logger.log(LogLevel.INFO, f"Database '{self.dbfile}' already exists.")
        
        # Connect to the SQLite database
        self.conn = sqlite3.connect(self.dbfile)
        
        # Create a cursor object to execute SQL queries
        self.cursor = self.conn.cursor()

    def sha256_checksum(self, filename, block_size=65536):
        sha256 = hashlib.sha256()
        if os.path.isfile(filename):
            try:
                with open(filename, 'rb') as f:
                    for block in iter(lambda: f.read(block_size), b''):
                        sha256.update(block)
            except PermissionError as e:
                self.logger.log(LogLevel.WARNING, f"caught exception, could not obtain hash for file {filename} -- {e}")
            return sha256.hexdigest()
        else:
            return ""

    def sha256_checksum_metadata(self, metadata):
        row_hashes = ""
        for row in metadata:
            row_hashes += hashlib.sha256(", ".join([str(cell) for cell in row]).encode('utf-8')).hexdigest()
        result = hashlib.sha256(row_hashes.encode('utf-8')).hexdigest()
        return result

    def get_file_info(self, filepath):
        p = pathlib.Path(filepath)
        file_stats = p.stat()
        permissions = file_stats.st_mode & 0o777
        mtime = file_stats.st_mtime
        size = file_stats.st_size
        sha256 = self.sha256_checksum(filepath)
        return permissions, p.owner(), p.group(), mtime, size, sha256

    def db_add_row(self, filepath, base_path):

        perms, owner, group, mtime, size, sha256 = self.get_file_info(filepath)

        # TODO: figure out which if any of these are unnecessary
        filepath = str(filepath)
        perms = int(perms)
        mtime = int(mtime)
        size = int(size)
        sha256 = str(sha256)
        base_path = str(base_path)

        # the filepath will start with the base_path
        filepath = str(filepath)[len(base_path):]
        if filepath[0] == '/':
            filepath = filepath[1:]

        self.cursor.execute("""
            INSERT INTO file (relative_path, mode, mod_time, file_size, content_hash, base_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(filepath), int(perms), int(mtime), int(size), sha256, base_path))

        return [filepath, perms, mtime, size, sha256, base_path]

    def db_save(self):
        
        # Commit the changes
        self.conn.commit()

        # Close the connection
        self.conn.close()

    def db_init_tbl(self, fileint_tbl, file_tbl):
        self.db_connect()


        h = len(self.config['fileint']['hierarchy'])
        label_str = ", ".join(self.config['fileint']['hierarchy'])
        placeholder_str = ", ".join(["?" for i in self.config['fileint']['hierarchy']])


        for row in fileint_tbl:

            fpath = row
            hash_of_blob = fileint_tbl[fpath]['hash_of_blob']
            
            if self.config['fileint']['hierarchy'] is not None and len(self.config['fileint']['hierarchy']) > 0:
                fileint_ins_query = "INSERT OR REPLACE INTO fileint (base_path, " + label_str +  ", hash_of_blob)\nVALUES (?, " + placeholder_str + ", ?)", [fpath] + fpath.split("/")[-h:] + [hash_of_blob]
            else:
                fileint_ins_query = "INSERT OR REPLACE INTO fileint (base_path, hash_of_blob)\nVALUES (?, ?)", [fpath, hash_of_blob]

            self.cursor.execute(fileint_ins_query[0], fileint_ins_query[1])

        for row in file_tbl:
            
            file_ins_query = "INSERT OR REPLACE INTO file (relative_path, mode, mod_time, file_size, content_hash, base_path) VALUES (?, ?, ?, ?, ?, ?) ", [row[1]] + [file_tbl[row][column] for column in file_tbl[row]] + [row[0]]
            self.cursor.execute(file_ins_query[0], file_ins_query[1])

        self.db_save()

    def tbl_add_row(self, relative_path, base_path):

        perms, owner, group, mtime, size, sha256 = self.get_file_info(relative_path)

        # TODO: figure out which if any of these are unnecessary
        relative_path = str(relative_path)
        perms = int(perms)
        mtime = int(mtime)
        size = int(size)
        sha256 = str(sha256)
        base_path = str(base_path)

        # the relative_path will start with the base_path
        relative_path = str(relative_path)[len(base_path):]
        if relative_path[0] == '/':
            relative_path = relative_path[1:]

        result = {'mode': perms, 'mod_time': mtime, 'file_size': size, 'content_hash': sha256}

        return result

    def create_baseline(self, filepath):
        # filepath can be either a file or a directory
        pass

    def signal_handler(self, signum, frame):
        signame = signal.Signals(signum).name
        if self.invalidated:
            self.logger.log(LogLevel.WARNING, f"Encountered {signame}, committing changes")
            self.conn.commit()
            self.invalidated = False
            sys.exit(1)

    def db_fetchall(self):
        return self.cursor.execute("SELECT * FROM fileint").fetchall(), self.cursor.execute("SELECT * FROM file").fetchall()

    # this function expects A and B to both be lists of dictionaries
    # it will report a list of elements that are different
    def tbl_compare(self, A, B):

        diffs = []

        extra_rows = set(B.keys()) - set(A.keys())
        for extra_row in extra_rows:
            diffs.append({'A': None, 'B': B[extra_row], 'mismatch_type': MismatchType.EXTRA_ROW, 'row': extra_row, 'column': None})

        for i in A:
            if i not in B:
                diffs.append({'A': A[i], 'B': None, 'mismatch_type': MismatchType.MISSING_ROW, 'row': i, 'column': None})
            else:
                extra_keys = set(B[i].keys()) - set(A[i].keys())
                for extra_key in extra_keys:
                    diffs.append({'A': A[i], 'B': B[i], 'mismatch_type': MismatchType.EXTRA_COLUMN, 'row': i, 'column': extra_key})
                for j in A[i]:
                    if j not in B[i]:
                        diffs.append({'A': A[i], 'B': B[i], 'mismatch_type': MismatchType.MISSING_COLUMN, 'row': i, 'column': j})
                    else:
                        if A[i][j] != B[i][j]:
                            diffs.append({'A': A[i], 'B': B[i], 'mismatch_type': MismatchType.WRONG_VALUE, 'row': i, 'column': j})
                            
        return diffs

    def read_saved_tbls(self, filters=None):

        prev_fileint_tbl, prev_file_tbl = None, None
        
        if os.path.exists(self.dbfile):
            if self.dbformat == 'pickle':
                with open(self.dbfile, 'rb') as pkl_file:
                    prev_fileint_tbl, prev_file_tbl = pickle.load(pkl_file)
            elif self.dbformat == 'sqlite3':
                self.db_connect()

                prev_fileint_tbl = {}
                prev_file_tbl = {}

                self.conn.row_factory = sqlite3.Row
                self.cursor.close()
                self.cursor = self.conn.cursor()
                if filters is None:
                    self.cursor.execute("SELECT * FROM fileint")
                else:
                    fi_query = "SELECT * FROM fileint WHERE "
                    filters_i = 1
                    for myfilter in filters:
                        fi_query += f"{myfilter['hierarchy']} = \"{myfilter['value']}\""
                        if len(filters) == filters_i:
                            break
                        fi_query += " AND "
                        filters_i += 1
                    self.logger.log(LogLevel.TRACE, f"fi_query: {fi_query}")
                    self.cursor.execute(fi_query)

                base_path_set = set()
                # row in this case is a sqlite3.Row object
                for row in self.cursor.fetchall():
                    row = dict(row)
                    base_path_set.add(row['base_path'])
                    key = row['base_path']
                    del row['base_path']
                    prev_fileint_tbl[key] = row

                if filters is None:
                    self.cursor.execute("SELECT * FROM file")
                else:
                    f_query = "SELECT * FROM file WHERE base_path IN ("
                    for base_path_value in base_path_set:
                        base_i = 1
                        f_query += f"\"{base_path_value}\""
                        if len(base_path_set) == base_i:
                            f_query += ")"
                            break
                        f_query += ", "
                    self.logger.log(LogLevel.TRACE, f"f_query = {f_query}")
                    self.logger.log(LogLevel.TRACE, f"filters = {filters}")
                    self.cursor.execute(f_query)
                # row in this case is a sqlite3.Row object
                for row in self.cursor.fetchall():
                    row = dict(row)
                    key = (row['base_path'], row['relative_path'])
                    del row['base_path']
                    del row['relative_path']
                    prev_file_tbl[key] = row

                self.conn.close()
        else:
            return None, None
        
        return prev_fileint_tbl, prev_file_tbl

    def write_tbls(self, fileint_tbl, file_tbl):
        if self.dbformat == 'pickle':
            self.logger.log(LogLevel.INFO, f"{self.dbfile} does not exist, writing baseline")
            with open(self.dbfile, 'wb') as pkl_file:
                pickle.dump([fileint_tbl, file_tbl], pkl_file)
        elif self.dbformat == 'sqlite3':
            self.db_init_tbl(fileint_tbl, file_tbl)
        else:
            raise Exception(f"ERROR: unexpected database format {self.dbformat}!")

    def print_diffs(self, diffs, header):
        self.logger.log(LogLevel.VERBOSE, f"{header} - START")
        if len(diffs):
            limit = len(diffs)
            if self.max_diff_prints:
                limit = self.max_diff_prints
            for i in range(len(diffs)):
                if i >= limit:
                    self.logger.log(LogLevel.VERBOSE, "diff print limit exceeded")
                    break
                self.logger.log(LogLevel.VERBOSE, f"diff #{i} {'mismatch_type'}: {diffs[i]['mismatch_type']}")
                for key in diffs[i]:
                    if key != 'mismatch_type':
                        self.logger.log(LogLevel.VERBOSE, f"diff #{i} - {key}: {diffs[i][key]}")
        self.logger.log(LogLevel.VERBOSE, f"{header} - END")

    def process_file(self, filepath):
        base_path = self.base_path
        relative_path = str(filepath)[len(base_path):]
        if relative_path[0] == '/':
            relative_path = relative_path[1:]
        new_row = self.tbl_add_row(filepath, base_path)
        return (base_path, relative_path), new_row

    def sanitize_identifier(self, string):
        import re
        
        # Allow only letters, digits, underscores, and hyphens
        return re.sub(r'[^a-zA-Z0-9._-]', '', string)

    def delete(self, filters):

        if self.dbformat != 'sqlite3':
            raise Exception(f"ERROR: only sqlite3 is supported for deletion (dbformat: {self.dbformat})")

        # the fileint table is a list of package names
        # - a package is uniquely identified by the tuple of the hierarchy components plus the base_path
        # the file table is a list of files, with only base_path and file-specific fields
        # - we need to remove from this table based only on the base_path

        # 1. get set of base_path value(s) from fileint based on specified filter(s)
        # 2. remove file row(s) containing any of those base_path value(s)
        # 3. remove fileint row(s) based on specified filter(s)

        # STEP 1: get set of base_path value(s) from db

        get_bps_query = "SELECT base_path FROM fileint WHERE "
        
        conditions = []
        for myfilter in filters:
            h = self.sanitize_identifier(myfilter['hierarchy'])
            v = self.sanitize_identifier(myfilter['value'])
            conditions.append(f"{h} = \"{v}\"")

        if len(conditions) == 0:
            raise Exception(f"ERROR: no filters specified in FileInt::delete()")

        get_bps_query += " AND ".join(conditions)

        self.db_connect()
        self.logger.log(LogLevel.VERBOSE, f"get_bps_query = {get_bps_query}")
        data = self.cursor.execute(get_bps_query).fetchall()
        base_paths = set([row[0] for row in data])
        if len(base_paths) == 0:
            self.logger.log(LogLevel.VERBOSE, f"INFO: In FileInt::delete(), no matching entries found in fileint, nothing to do")
            return

        # STEP 2: remove file row(s) containing any of those base_path value(s)
        file_rm_query = "DELETE FROM file WHERE " + " OR ".join([f"base_path = \"{base_path}\"" for base_path in base_paths])
        self.logger.log(LogLevel.VERBOSE, f"file_rm_query = {file_rm_query}")
        self.cursor.execute(file_rm_query)

        # STEP3 3: remove fileint row(s) based on specified filter(s)
        fileint_rm_query = "DELETE FROM fileint WHERE " + " AND ".join(conditions)
        self.logger.log(LogLevel.VERBOSE, f"fileint_rm_query = {fileint_rm_query}")
        self.cursor.execute(fileint_rm_query)

        self.db_save()

    def read_paths(self, filters=None, accept=False):

        # used to avoid symlink duplicates for now, unconditionally, not heeding
        # the config parameter yet
        seen_paths = set()

        h = len(self.config['fileint']['hierarchy'])
        label_str = ", ".join(self.config['fileint']['hierarchy'])
        placeholder_str = ", ".join(["?" for i in self.config['fileint']['hierarchy']])

        fileint_tbl = dict()
        file_tbl = dict()

        for search_path in self.config['general']['base']:
            if h == 1:
                files = pathlib.Path(search_path).iterdir()
            else:
                files = pathlib.Path(search_path).glob("/".join(h * ["*"]))
            for fpath in files:
                metadata = []
                fpath = str(pathlib.Path(fpath))
                # # using resolve here means that if two packages point to eachother, there will only be one entry
                # # not doing so, means that they are treated like entirely unique directories
                fpath = str(pathlib.Path(fpath).resolve())
                d1, d2 = fpath.split('/')[-2:]
                if d1 == 'modulefiles' or \
                   d2 == 'modulefiles' or \
                   not pathlib.Path(fpath).is_dir():
                    continue
                if (fpath not in self.config['general']['base']) and (fpath not in seen_paths):
                    seen_paths.add(fpath)
                    if filters is None:
                        self.logger.log(LogLevel.INFO, f"new package {fpath}")
                    if self.config['fileint']['hierarchy'] is not None and len(self.config['fileint']['hierarchy']) > 0:
                        base_path = fpath

                        new_row = {'hash_of_blob': ''}

                        i = 0
                        for component in fpath.split("/")[-h:]:
                            new_row[self.config['fileint']['hierarchy'][i]] = component
                            i += 1

                        matches_filter = True
                        for myfilter in filters:
                            if myfilter['value'] != new_row[myfilter['hierarchy']]:
                                matches_filter = False
                                break

                        if matches_filter:
                            fileint_tbl[base_path] = new_row
                        else:
                            continue

                    self.base_path = base_path

                    if self.path_limit is not None:
                        pkg_path = pathlib.Path(self.path_limit)
                    else:
                        pkg_path = '\0'

                    with multiprocessing.Pool(self.pool_size) as p:
                        
                        # Create a list of file paths
                        file_paths = [filepath for filepath in pathlib.Path(fpath).rglob('*') if pathlib.Path(filepath).exists()]
                        file_paths = [filepath for filepath in file_paths if not (filepath.is_symlink() and not str(filepath.resolve()).startswith(str(pkg_path)))]

                        # Process each file in parallel
                        results = p.map(self.process_file, file_paths)

                        # Collect the results into file_tbl and metadata
                        for (key, new_row) in results:
                            file_tbl[key] = new_row
                            metadata.append(list(new_row.values()))

                    metadata_hash = self.sha256_checksum_metadata(metadata)
                    fileint_tbl[base_path]['hash_of_blob'] = metadata_hash
                
        if not os.path.exists(self.dbfile) or not self.filters_matched(filters):
            self.write_tbls(fileint_tbl, file_tbl)
            fileint_tbl_diffs = None
            file_tbl_diffs = None
        elif os.path.exists(self.dbfile) and accept:
            self.write_tbls(fileint_tbl, file_tbl)
            fileint_tbl_diffs = None
            file_tbl_diffs = None
        else:

            self.logger.log(LogLevel.INFO, f"{self.dbfile} does exist, comparing with baseline")
            prev_fileint_tbl, prev_file_tbl = self.read_saved_tbls(filters)

            fileint_tbl_diffs = self.tbl_compare(prev_fileint_tbl, fileint_tbl)
            file_tbl_diffs = self.tbl_compare(prev_file_tbl, file_tbl)

            self.print_diffs(fileint_tbl_diffs, "FILEINT_TBL_DIFFS")
            self.print_diffs(file_tbl_diffs, "FILE_TBL_DIFFS")

            file_set = set([diff['row'] for diff in file_tbl_diffs])

            print("==== RESULTS ====")

            if len(fileint_tbl_diffs) == 0:
                print("fileint_tbl [ OK ]")
            else:
                print("fileint_tbl [FAIL]")

            if len(file_tbl_diffs) == 0:
                print("file_tbl [ OK ]")
            else:
                print("file_tbl [FAIL]")

            print(f"files different from the baseline: {len(file_set)} (out of {len(file_tbl)})")

        return fileint_tbl, file_tbl, fileint_tbl_diffs, file_tbl_diffs

    def del_db(self):
        if os.path.exists(self.dbfile):
            self.logger.log(LogLevel.INFO, f"removing previous db: {self.dbfile}")
            os.remove(self.dbfile)

    # iterates through pre-configured paths, prints all paths that match the
    # hierarchy template
    def get_hierarchy(self, ignore_paths=None):

        h = len(self.config['fileint']['hierarchy'])
        label_str = ", ".join(self.config['fileint']['hierarchy'])
        placeholder_str = ", ".join(["?" for i in self.config['fileint']['hierarchy']])

        fileint_tbl = dict()
        file_tbl = dict()

        results = []

        seen_paths = set()

        for search_path in self.config['general']['base']:
            if h == 1:
                files = pathlib.Path(search_path).iterdir()
            else:
                files = pathlib.Path(search_path).glob("/".join(h * ["*"]))
            for fpath in files:
                metadata = []
                fpath = str(pathlib.Path(fpath))
                # # using resolve here means that if two packages point to eachother, there will only be one entry
                # # not doing so, means that they are treated like entirely unique directories
                # fpath = str(pathlib.Path(fpath).resolve())
                d1, d2 = fpath.split('/')[-2:]
                if d1 == 'modulefiles' or \
                   d2 == 'modulefiles' or \
                   not pathlib.Path(fpath).is_dir():
                    continue
                if (fpath not in self.config['general']['base']) and (fpath not in seen_paths):
                    seen_paths.add(fpath)
                    self.logger.log(LogLevel.TRACE, f"new package {fpath}")
                    if self.config['fileint']['hierarchy'] is not None and len(self.config['fileint']['hierarchy']) > 0:

                        base_path = fpath

                        new_row = dict()

                        i = 0
                        for component in fpath.split("/")[-h:]:
                            new_row[self.config['fileint']['hierarchy'][i]] = component
                            i += 1

                        ignore = False
                        if ignore_paths is not None:
                            for ignore_path in ignore_paths:
                                if base_path.startswith(ignore_path):
                                    ignore = True

                        if not ignore:
                            results.append(new_row)

        return results

    def filters_matched(self, filters=None):
        if filters is None:
            return True

        self.db_connect()
        self.cursor = self.conn.cursor()
        
        fi_query = "SELECT COUNT(*) FROM fileint WHERE "
        filters_i = 1
        for myfilter in filters:
            fi_query += f"{myfilter['hierarchy']} = \"{myfilter['value']}\""
            if len(filters) == filters_i:
                break
            fi_query += " AND "
            filters_i += 1

        self.logger.log(LogLevel.VERBOSE, f"fi_query_count: {fi_query}")

        self.cursor.execute(fi_query)
        fetch = self.cursor.fetchall()
        nonzero = False
        try:
            if fetch[0][0] > 0:
                nonzero = True
        except:
            pass
        self.conn.close()

        return nonzero

    def get_filter_matches(self, filters):

        self.db_connect()
        self.cursor = self.conn.cursor()
        
        fi_query = "SELECT base_path FROM fileint WHERE "
        filters_i = 1
        for myfilter in filters:
            fi_query += f"{myfilter['hierarchy']} = \"{myfilter['value']}\""
            if len(filters) == filters_i:
                break
            fi_query += " AND "
            filters_i += 1

        self.cursor.execute(fi_query)
        fetch = self.cursor.fetchall()

        results = []
        for row in fetch:
            if len(row) >= 1:
                results.append(row[0])
        self.conn.close()
        
        return results
