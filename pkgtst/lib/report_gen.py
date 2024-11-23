# report_gen - report generator library

import os
import jinja2
from jinja2 import Environment, FileSystemLoader
import datetime
import sqlite3
import fcntl
import yaml
import sys
from .fileint import Hierarchy

class ReportGen():

    def __init__(self):
        self.template_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'templates')
        self.tbl_template_basename = 'template.html'

        self.dbfile = os.path.join(os.path.dirname(__file__), '..', '..', 'var', 'db', 'results.sql')
        self.rendered_html = os.path.join(os.path.dirname(__file__), '..', '..', 'var', 'html', 'test_results.html')

        self.config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'etc', 'pkgtst.yaml')
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                if self.config['report_gen']['dbfile']:
                    self.dbfile = self.config['report_gen']['dbfile']
                if self.config['report_gen']['rendered_html']:
                    self.rendered_html = self.config['report_gen']['rendered_html']
                if self.config['report_gen']['warn_only']:
                    self.warn_only = self.config['report_gen']['warn_only']

        self.hierarchy = Hierarchy()
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

        print(f"query: {query}")
        cursor.execute(query)

        conn.commit()

        cursor.close()
        conn.close()

        print(f"created database at {self.dbfile}")

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
                    print(f"Database '{self.dbfile}' already exists.")
            finally:
                # Release the lock
                fcntl.flock(f, fcntl.LOCK_UN)

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

        # edits
        cursor.execute(query, values)
        
        conn.commit()

        cursor.close()
        conn.close()

    def pprint_table_helper(self, data):
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

        # Print the header
        header = " | ".join(f"{key:{max_widths[key]}}" for key in headers)
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
                    cell = f"{str(row[key]):{max_widths[key]}}"
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

    def render_data(self, data, template_path=None):
        
        summary = dict()
        summary['fileint_fail_count'] = 0
        summary['lnfs_fail_count'] = 0
        for row in data:
            if not row['passed_fileint']:
                summary['fileint_fail_count'] += 1
            if not row['passed_lnfs']:
                summary['lnfs_fail_count'] += 1

        if len(data) > 0:
            summary['fileint_fail_percentage'] = 100 * summary['fileint_fail_count'] / len(data)
            summary['lnfs_fail_percentage'] = 100 * summary['lnfs_fail_count'] / len(data)
        else:
            summary['fileint_fail_percentage'] = 100
            summary['lnfs_fail_percentage'] = 100
        summary['last_run'] = max([row['datetime'] for row in data])

        if template_path is None:
            env = Environment(loader=FileSystemLoader(self.template_dir))
            template = env.get_template(self.tbl_template_basename)
        else:
            env = Environment(loader=FileSystemLoader(os.path.dirname(template_path)))
            import hashlib
            def sha256_hash(value):
                return hashlib.sha256(value.encode('utf-8')).hexdigest()
            env.filters['hash'] = sha256_hash
            template = env.get_template(os.path.basename(template_path))

        # print(f"data: {data}")

        data = sorted(data, key=lambda x: (x['passed_fileint'], x['passed_fileint']))
        rendered_html = template.render(data=data, summary=summary)
        with open(self.rendered_html, 'w') as fp:
            fp.write(rendered_html + "\n")
            sys.stderr.write(f"Wrote: {self.rendered_html}\n")

    def print_table(self, filters=None, sort_keys=None, reverse=False, limit=None, limit_per=None, parseable=False, field_delimiter='|', fails_only=False, case_insensitive=False, render_jinja=False, template_path=None):

        conn = sqlite3.connect(self.dbfile)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM results')

        data = cursor.fetchall()
        data = [dict(row) for row in data]

        cursor.close()
        conn.close()

        h = Hierarchy()

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

        # Sort the data using the dynamically created sort key
        data = sorted(
            data,
            key=lambda x: tuple(
                str(x[key]).lower() if case_insensitive else str(x[key])
                for key in sort_keys.split(":")
            ),
            reverse=reverse
        )

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
            
            if parseable:

                try:

                    sys.stdout.write(f"{field_delimiter.join(header)}\n")

                    i = 1
                    for row in data:
                        fields = [str(row[key]) for key in row]
                        sys.stdout.write(f"{i}{field_delimiter}{field_delimiter.join(fields)}\n")
                        sys.stdout.flush()
                        i += 1

                except BrokenPipeError:
                    sys.stderr.close()
                    sys.exit(0)

            else:
                self.pprint_table_helper(data)

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
