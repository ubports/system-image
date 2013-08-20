# Copyright (C) 2013 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Persistent settings - used by the DBus API."""

__all__ = [
    'Settings',
    ]


import sqlite3

from contextlib import contextmanager
from systemimage.config import config

SCHEMA_VERSION = '1'


@contextmanager
def cursor():
    with sqlite3.connect(config.system.settings_db) as conn:
        yield conn.cursor()


class Settings:
    def __init__(self):
        # If the database file does not yet exist, create it.
        with cursor() as c:
            c.execute('select tbl_name from sqlite_master')
            if len(c.fetchall()) == 0:
                # The database file has no tables.
                c.execute('create table settings (key, value)''')
            # Hopefully we won't ever need to migrate this schema, but just in
            # case we do, set a version value.
            c.execute('insert into settings values ("__version__", ?)',
                      (SCHEMA_VERSION,))

    def set(self, key, value):
        with cursor() as c:
            c.execute('select value from settings where key = ?', (key,))
            row = c.fetchone()
            if row is None:
                c.execute('insert into settings values (?, ?)',
                          (key, value))
            else:
                c.execute('update settings set value = ? where key = ?',
                          (value, key))

    def get(self, key):
        with cursor() as c:
            c.execute('select value from settings where key = ?', (key,))
            row = c.fetchone()
            if row is None:
                return ''
            return row[0]
