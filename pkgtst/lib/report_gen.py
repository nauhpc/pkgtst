# report_gen - report generator library

import os
import jinja2
from jinja2 import Environment, FileSystemLoader
import datetime
import sqlite3
import fcntl
import yaml
import sys
import shutil

from pkgtst.lib.logger import Logger
from pkgtst.lib.logger import LogLevel
from pkgtst.lib.fileint import Hierarchy
from pkgtst.lib.custom_test import CustomTest
from pkgtst.lib.utils import get_pkgtst_root

class ReportGen():

    def __init__(self, config_path=None):
        self.template_dir = os.path.join(get_pkgtst_root(), 'etc', 'templates')
        self.tbl_template_basename = 'template.html'

        self.dbfile = os.path.join(get_pkgtst_root(), 'var', 'db', 'results.sql')
        self.rendered_html = os.path.join(get_pkgtst_root(), 'var', 'html', 'test_results.html')

        if config_path is None:
            self.config_path = os.path.join(get_pkgtst_root(), 'etc', 'pkgtst.yaml')
        else:
            self.config_path = config_path

        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                if self.config['report_gen']['dbfile']:
                    self.dbfile = self.config['report_gen']['dbfile']
                if self.config['report_gen']['rendered_html']:
                    self.rendered_html = self.config['report_gen']['rendered_html']
                if self.config['report_gen']['warn_only']:
                    self.warn_only = self.config['report_gen']['warn_only']
                else:
                    self.warn_only = []
                if self.config['report_gen']['ct_warn_only']:
                    self.ct_warn_only = self.config['report_gen']['ct_warn_only']
                else:
                    self.ct_warn_only = []
                if self.config['report_gen']['retention']:
                    self.retention = self.config['report_gen']['retention']
                if self.config['report_gen']['output_limit_per']:
                    # the output limit per package
                    self.output_limit_per = self.config['report_gen']['output_limit_per']

        self.hierarchy = Hierarchy(config_path=self.config_path)
        self.column_string = ""
        self.column_create_string = ""
        for i in range(len(self.hierarchy.components)):
            if i > 0:
                self.column_string += ', '
                self.column_create_string += ' ' * 4
            component = self.hierarchy.components[i]
            component = component.replace('"', '')
            component = f'"{component}"'
            self.column_string += component
            self.column_create_string += f"{component} TEXT NOT NULL,"
            if i < len(self.hierarchy.components) - 1:
                self.column_create_string += "\n"

        # env var overrides
        if os.environ.get('PKGTST_RETENTION'):
            self.retention = os.environ.get('PKGTST_RETENTION')

        if os.environ.get('PKGTST_OUTPUT_LIMIT_PER'):
            self.output_limit_per = os.environ.get('PKGTST_OUTPUT_LIMIT_PER')

        self.logger = Logger(config_path=self.config_path)

    def create_db(self):
        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        query = '''
CREATE TABLE IF NOT EXISTS results (
    datetime TEXT NOT NULL,
    %s
    package_base TEXT NOT NULL,
    module_name TEXT NOT NULL,
    passed_fileint BOOLEAN NOT NULL CHECK (passed_fileint IN (0, 1)),
    passed_lnfs BOOLEAN NOT NULL CHECK (passed_lnfs IN (0, 1))
)
''' % (self.column_create_string)

        self.logger.log(LogLevel.VERBOSE, f"query: {query}")
        cursor.execute(query)

        conn.commit()

        cursor.close()
        conn.close()

        self.logger.log(LogLevel.INFO, f"created database at {self.dbfile}")

    def create_db_with_lock(self):
        lock_file = self.dbfile + '.lock'
        with open(lock_file, 'w') as f:
            try:
                # Acquire an exclusive lock on the lock file
                fcntl.flock(f, fcntl.LOCK_EX)
                
                # check if the database file exists
                if not os.path.exists(self.dbfile):
                    self.create_db()
                else:
                    self.logger.log(LogLevel.INFO, f"Database '{self.dbfile}' already exists.")
            finally:
                # Release the lock
                fcntl.flock(f, fcntl.LOCK_UN)

    def trim_results(self, package_id):
        self.logger.log(LogLevel.INFO, f"INFO: self.retention: {self.retention}")
        
        if len(package_id) != len(self.hierarchy.components):
            # retention rules only apply to individual packages
            return

        if self.retention is None:
            return

        n, units = self.retention.split(" ")

        try:
            n = int(n)
        except:
            raise Exception(f"ERROR: unable to parse n as an integer from retention value (value: {self.retention}, should read as '<n> <units>')")

        if units not in {'runs', 'days', 'weeks', 'months', 'years'}:
            raise Exception(f"ERROR: invalid units in retention value (value: {self.retention}, should read as '<n> <units>')")

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        if units == 'runs':
            query = """
DELETE FROM results WHERE ROWID IN (
    SELECT ROWID
    FROM results
    WHERE %s
    ORDER BY datetime ASC
    LIMIT -1 OFFSET %s
);""" % (" AND ".join([f"{component} = ?" for component in self.hierarchy.components]), n)
            values = package_id
        else:
            if units == 'days':
                scalar = 1
            elif units == 'weeks':
                scalar = 7
            elif units == 'months':
                scalar = 30
            elif units == 'years':
                scalar = 365
            days = n * scalar
            mydate = datetime.datetime.now() - datetime.timedelta(days=days)
            timestamp = mydate.strftime('%Y-%m-%d 00:00:00')
            self.logger.log(LogLevel.TRACE, f"days = {days}, timestamp = '{timestamp}'")
            query = "DELETE FROM results WHERE datetime < ?"
            values = [timestamp]
            self.logger.log(LogLevel.TRACE, f"query = {query}")

        self.logger.log(LogLevel.TRACE, f"query: '{query}', values: '{values}'")

        cursor.execute(query, values)

        self.logger.log(LogLevel.INFO, 'The results database may have been changed (operation: trim), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

        conn.commit()

        cursor.close()
        conn.close()

    def write_result(self, package_id, pkg_base, module_name, results):

        if not isinstance(package_id, list):
            raise Exception(f"ERROR: in report_gen::write_result package_id must be a list")

        if not os.path.exists(self.dbfile):
            self.create_db_with_lock()

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        values = [ts] + package_id + [pkg_base, module_name, results['passed_fileint'], results['passed_lnfs']]

        query = '''INSERT INTO results (datetime, %s, package_base, module_name, passed_fileint, passed_lnfs)
VALUES (%s)''' % (self.column_string, ", ".join("?" * len(values)))

        self.logger.log(LogLevel.INFO, 'The results database has been changed (operation: insert), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

        # edits
        cursor.execute(query, values)
        
        conn.commit()

        cursor.close()
        conn.close()

        self.trim_results(package_id)

    def create_ct_tbl(self):
        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        query = '''
CREATE TABLE IF NOT EXISTS ct_results (
    datetime TEXT NOT NULL,
    test_name TEXT NOT NULL,
    variant TXT NOT NULL,
    passed BOOLEAN NOT NULL CHECK (passed IN (0, 1))
)
'''

        self.logger.log(LogLevel.VERBOSE, f"query: {query}")
        cursor.execute(query)

        conn.commit()

        cursor.close()
        conn.close()

    def trim_ct_results(self, test_name):
        self.logger.log(LogLevel.INFO, f"self.retention: {self.retention}")

        if test_name is None or not isinstance(test_name, str):
            self.logger.log(LogLevel.ERROR, "test_name is not a string")

        if self.retention is None:
            return

        n, units = self.retention.split(" ")

        try:
            n = int(n)
        except:
            raise Exception(f"ERROR: unable to parse n as an integer from retention value (value: {self.retention}, should read as '<n> <units>')")

        if units not in {'runs', 'days', 'weeks', 'months', 'years'}:
            raise Exception(f"ERROR: invalid units in retention value (value: {self.retention}, should read as '<n> <units>')")

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        if units == 'runs':
            query = """
DELETE FROM ct_results WHERE ROWID IN (
    SELECT ROWID
    FROM ct_results
    WHERE test_name = ?
    ORDER BY datetime ASC
    LIMIT -1 OFFSET ?
);"""
            values = [test_name, n]
        else:
            if units == 'days':
                scalar = 1
            elif units == 'weeks':
                scalar = 7
            elif units == 'months':
                scalar = 30
            elif units == 'years':
                scalar = 365
            days = n * scalar
            mydate = datetime.datetime.now() - datetime.timedelta(days=days)
            timestamp = mydate.strftime('%Y-%m-%d 00:00:00')
            self.logger.log(LogLevel.TRACE, f"days = {days}, timestamp = '{timestamp}'")
            query = "DELETE FROM ct_results WHERE datetime < ?"
            values = [timestamp]
            self.logger.log(LogLevel.TRACE, f"query = {query}")

        self.logger.log(LogLevel.TRACE, f"query: '{query}', values: '{values}'")

        cursor.execute(query, values)

        self.logger.log(LogLevel.INFO, 'The results database may have been changed (operation: trim), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

        conn.commit()

        cursor.close()
        conn.close()

    def write_ct_result(self, test_name, passed, jobid=None):
        if not os.path.exists(self.dbfile):
            self.create_db_with_lock()
        self.create_ct_tbl()

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        variant = ""

        if ":" in test_name:
            index = test_name.find(":")
            variant = test_name[index + 1:]
            test_name = test_name[:index]

        query = '''INSERT INTO ct_results (datetime, test_name, variant, passed) VALUES (?, ?, ?, ?)'''
        values = [ts, test_name, variant, passed]
        cursor.execute(query, values)
        
        conn.commit()

        cursor.close()
        conn.close()

        self.logger.log(LogLevel.INFO, 'The ct_results database has been changed (operation: insert), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

        self.trim_ct_results(test_name)

    def delete_package(self, package_id):

        if not isinstance(package_id, list):
            raise Exception(f"ERROR: in report_gen::delete_package package_id must be a list")

        if not os.path.exists(self.dbfile):
            self.create_db_with_lock()

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        column_names = self.hierarchy.components
        values = package_id

        if len(column_names) != len(package_id):
            raise Exception(f"ERROR: in report_gen::delete_package package_id must be fully qualified")

        where_clause = " AND ".join([f"{column} = ?" for column in column_names])

        query = f"DELETE FROM results WHERE {where_clause}"
        cursor.execute(query, values)

        conn.commit()

        cursor.close()
        conn.close()

        self.logger.log(LogLevel.INFO, 'The results database may have been changed (operation: delete), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

    def delete_ct(self, test_name):

        if not isinstance(test_name, str):
            raise Exception(f"ERROR: in report_gen::delete_ct test_name must be a string")

        if not os.path.exists(self.dbfile):
            self.create_db_with_lock()

        conn = sqlite3.connect(self.dbfile)
        cursor = conn.cursor()

        variant = None

        if ":" in test_name:
            index = test_name.find(":")
            variant = test_name[index + 1:]
            test_name = test_name[:index]

        column_names = ['test_name']
        values = [test_name]

        if variant is not None:
            column_names.append('variant')
            values.append(variant)

        where_clause = " AND ".join([f"{column} = ?" for column in column_names])

        query = f"DELETE FROM ct_results WHERE {where_clause}"
        cursor.execute(query, values)

        conn.commit()

        cursor.close()
        conn.close()

        self.logger.log(LogLevel.INFO, 'The results database may have been changed (operation: delete), consider updating the results page (i.e. by executing pkgtst report --render-jinja')

    def pprint_table_helper(self, data, no_truncation=False):
        if not data:
            print("No data to display.")
            return

        # Determine the maximum width for each column, including the header
        try:
            headers = list(data[0].keys())
        except IndexError:
            headers = []

        max_widths = {key: max(len(str(row[key])) for row in data) for key in headers}
        max_widths = {key: max(max_widths[key], len(key)) for key in headers}

        if not no_truncation:
            terminal_width = shutil.get_terminal_size().columns
            decorator_width = 3 * (len(headers) - 1)
            content_width = sum(max_widths.values())
            total_width = decorator_width + content_width
            if total_width > terminal_width:
                max_content_width = (terminal_width - decorator_width) // len(headers)
                max_widths = {key: min(max_widths[key], max_content_width) for key in headers}

        # Print the header
        # header = " | ".join(f"{key:{max_widths[key]}}" for key in headers)
        header = " | ".join(f"{key[:max_widths[key]]:<{max_widths[key]}}" for key in headers)
        print(header)
        print("-" * len(header))

        try:
            # let's save some ANSI codes
            GREEN_BG_BLACK_TEXT = "\033[42;30m"
            RED_BG_BLACK_TEXT = "\033[41;30m"
            YELLOW_BG_BLACK_TEXT = "\033[43;30m"
            RESET = "\033[0m"
            # Print each row
            for row in data:
                for i in range(len(headers)):
                    key = headers[i]
                    cell = f"{str(row[key])[:max_widths[key]]:<{max_widths[key]}}"
                    if key.startswith("passed_"):
                        if row[key]:
                            cell = f"{GREEN_BG_BLACK_TEXT}{cell}{RESET}"
                        else:
                            if row['warn_only']:
                                cell = f"{YELLOW_BG_BLACK_TEXT}{cell}{RESET}"
                            else:
                                cell = f"{RED_BG_BLACK_TEXT}{cell}{RESET}"
                    if i < len(headers) - 1:
                        cell += " "
                        sys.stdout.write(f"{cell}| ")
                    else:
                        sys.stdout.write(f"{cell}\n")

        except BrokenPipeError:
            sys.stderr.close()

    def get_ct_data(self):

        if os.path.exists(self.dbfile):
        
            conn = sqlite3.connect(self.dbfile)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM ct_results')
            data = cursor.fetchall()
            data = [dict(row) for row in data]
            cursor.close()
            conn.close()
        else:
           self.logger.log(LogLevel.VERBOSE, f"Results sqlite file not found at {self.dbfile}, have you executed any custom tests yet?")
           data = []

        # apply warning filter
        for row in data:
            row['warn_only'] = False
            for filter_set in self.ct_warn_only:
                is_match = True
                for component, value in filter_set.items():
                    if row[component] != value:
                        is_match = False
                if is_match:
                    row['warn_only'] = True
                    break

        data = sorted(data, key=lambda x: (x['test_name'], x['variant'], x['datetime']), reverse=True)

        return data

    def render_data(self, data, template_path=None):

        summary = dict()

        summary['updated'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        
        # holds summary keys: pass/fail/warn counts
        summary['fileint'] = {'pass': 0, 'fail': 0, 'warn': 0, 'total': 0}
        summary['lnfs'] = {'pass': 0, 'fail': 0, 'warn': 0, 'total': 0}
        summary['ct'] = {'pass': 0, 'fail': 0, 'warn': 0, 'total': 0}

        seen_pkgs = set()

        for row in data:

            package_id = ""
            for c in self.hierarchy.components:
                if len(package_id) == 0:
                    package_id = row[c]
                else:
                    package_id += f":{c}"

            if not package_id in seen_pkgs:

                if row['passed_fileint']:
                    summary['fileint']['pass'] += 1
                elif row['warn_only']:
                    summary['fileint']['warn'] += 1
                else:
                    summary['fileint']['fail'] += 1
                summary['fileint']['total'] += 1

                if row['passed_lnfs']:
                    summary['lnfs']['pass'] += 1
                elif row['warn_only']:
                    summary['lnfs']['warn'] += 1
                else:
                    summary['lnfs']['fail'] += 1
                summary['lnfs']['total'] += 1

                seen_pkgs.add(package_id)

        if template_path is None:
            search_path = self.template_dir
            basename = self.tbl_template_basename
        else:
            search_path = os.path.dirname(template_path)
            basename = os.path.basename(template_path)

        env = Environment(loader=FileSystemLoader(search_path))
        import hashlib
        def sha256_hash(value):
            return hashlib.sha256(value.encode('utf-8')).hexdigest()
        env.filters['hash'] = sha256_hash
        template = env.get_template(basename)

        ct_data = self.get_ct_data()

        seen_cts = set()

        for row in ct_data:

            test_id = f"{row['test_name']}:{row['variant']}"

            if not test_id in seen_cts:

                if row['passed']:
                    summary['ct']['pass'] += 1
                elif row['warn_only']:
                    summary['ct']['warn'] += 1
                else:
                    summary['ct']['fail'] += 1
                summary['ct']['total'] += 1

                seen_cts.add(test_id)
        
        rendered_html = template.render(data=data, summary=summary, ct_data=ct_data)
        with open(self.rendered_html, 'w') as fp:
            fp.write(rendered_html + "\n")
            self.logger.log(LogLevel.INFO, f"Wrote: {self.rendered_html}")

    def print_table(self, filters=None, sort_keys=None, reverse=False, limit=None, limit_per=None, parsable=False, field_delimiter='|', fails_only=False, case_insensitive=False, render_jinja=False, template_path=None, no_truncation=False):

        if limit_per is None and self.output_limit_per is not None:
            limit_per = self.output_limit_per

        if os.path.exists(self.dbfile):
            conn = sqlite3.connect(self.dbfile)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM results')
            data = cursor.fetchall()
            data = [dict(row) for row in data]
            cursor.close()
            conn.close()
        else:
           self.logger.log(LogLevel.VERBOSE, f"Results sqlite file not found at {self.dbfile}, have you executed any package tests yet?")
           data = []

        h = Hierarchy(config_path=self.config_path)

        if filters is not None:
            rm_indices = set()
            for i in range(len(data)):
                row = data[i]
                for myfilter in filters:
                    if row[myfilter['hierarchy']] != myfilter['value']:
                        rm_indices.add(i)
            data = [data[i] for i in range(len(data)) if i not in rm_indices]


        if sort_keys is None:
            sort_keys = ":".join(h.components + ["datetime"])

        def invert_string(s):
            max_val = 255
            inverted_string = ''.join(chr(max_val - ord(c)) for c in s)
            return inverted_string

        if 'datetime' in set(sort_keys.split(':')):
            # we want to invert the order of date timestamps
            for i in range(len(data)):
                data[i]['datetime'] = invert_string(data[i]['datetime'])

        # Sort the data using the dynamically created sort key
        data = sorted(
            data,
            key=lambda x: tuple(
                str(x[key]).lower() if case_insensitive else str(x[key])
                for key in sort_keys.split(":")
            ),
            reverse=reverse
        )

        if 'datetime' in set(sort_keys.split(':')):
            # we want to undo invert the previous invert operation
            for i in range(len(data)):
                data[i]['datetime'] = invert_string(data[i]['datetime'])

        if limit_per is not None:
            # indices[(component1, component2, ...)] = <list-of-valid-indices>
            # rm_indices = <set-of-indices-to-remove>
            indices = dict()
            rm_indices = set()
            for i in range(len(data)):
                row = data[i]
                key = tuple([row[component] for component in h.components])
                if key not in indices:
                    indices[key] = [i]
                else:
                    # is there a potential for smarter filters here?
                    if len(indices[key]) >= limit_per:
                        rm_indices.add(i)
                    else:
                        indices[key].append(i)
            data = [data[i] for i in range(len(data)) if i not in rm_indices]

        if limit is not None:
            data = data[0:limit]

        # apply warning filter
        for row in data:
            row['warn_only'] = False
            for filter_set in self.warn_only:
                is_match = True
                for component, value in filter_set.items():
                    if row[component] != value:
                        is_match = False
                if is_match:
                    row['warn_only'] = True
                    break
        try:
            header = data[0].keys()
        except IndexError:
            header = []

        if render_jinja:
            
            self.render_data(data, template_path=template_path)
            
        else:
            
            if parsable:

                try:

                    sys.stdout.write(f"{field_delimiter.join(header)}\n")

                    i = 1
                    for row in data:
                        fields = [str(row[key]) for key in row]
                        sys.stdout.write(f"{field_delimiter.join(fields)}\n")
                        sys.stdout.flush()
                        i += 1

                except BrokenPipeError:
                    sys.stderr.close()
                    sys.exit(0)

            else:
                self.pprint_table_helper(data, no_truncation=no_truncation)

    def set_warn_only(self, filters, value=True):
        if not isinstance(value, bool):
            raise Exception(f"Cannot set warn-only to the non-bool value: {value}")

        edit = False
        selected = {}
        for myfilter in filters:
            selected[myfilter['hierarchy']] = myfilter['value']

        indices = set()
        for i in range(len(self.warn_only)):
            if self.warn_only[i] == selected:
                indices.add(i)
        if not indices and value:
            self.warn_only.append(selected)
            edit = True
        if indices and not value:
            self.warn_only = [self.warn_only[i] for i in range(len(self.warn_only)) if i not in indices]
            edit = True

        if edit and os.path.exists(self.config_path):
            with open(self.config_path, 'w') as f:
                self.config['report_gen']['warn_only'] = self.warn_only
                yaml.dump(self.config, f, default_flow_style=False)

    def show_warn_only(self):
        self.pprint_table_helper(self.warn_only)

    def print_ct_table(self, test_name=None, parsable=None, field_delimiter='|', limit_per=None):

        ct_data = self.get_ct_data()

        if test_name is not None and isinstance(test_name, str):

            variant = None

            if ":" in test_name:
                index = test_name.find(":")
                variant = test_name[index + 1:]
                test_name = test_name[:index]
                ct_data = [row for row in ct_data if row['test_name'] == test_name and row['variant'] == variant]
            else:
                ct_data = [row for row in ct_data if row['test_name'] == test_name]

        if limit_per is not None:
            # indices[(component1, component2, ...)] = <list-of-valid-indices>
            # rm_indices = <set-of-indices-to-remove>
            indices = dict()
            rm_indices = set()
            for i in range(len(ct_data)):
                row = ct_data[i]
                key = tuple([row['test_name'], row['variant']])
                if key not in indices:
                    indices[key] = [i]
                else:
                    # is there a potential for smarter filters here?
                    if len(indices[key]) >= limit_per:
                        rm_indices.add(i)
                    else:
                        indices[key].append(i)
            ct_data = [ct_data[i] for i in range(len(ct_data)) if i not in rm_indices]

        if parsable:
            try:

                data = ct_data

                try:
                    header = data[0].keys()
                except IndexError:
                    header = []

                sys.stdout.write(f"{field_delimiter.join(header)}\n")

                i = 1
                for row in data:
                    fields = [str(row[key]) for key in row]
                    sys.stdout.write(f"{field_delimiter.join(fields)}\n")
                    sys.stdout.flush()
                    i += 1

            except BrokenPipeError:
                sys.stderr.close()
                sys.exit(0)
        else:
            self.pprint_table_helper(ct_data)
