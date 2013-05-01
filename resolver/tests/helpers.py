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

"""Test helpers."""

__all__ = [
    'get_channels',
    'get_index',
    'make_http_server',
    'make_temporary_cache',
    ]


import os
import shutil
import tempfile

from http.server import HTTPServer, SimpleHTTPRequestHandler
from pkg_resources import resource_string as resource_bytes
from resolver.cache import Cache
from resolver.channel import Channels
from resolver.config import Configuration
from resolver.helpers import atomic
from resolver.index import Index
from textwrap import dedent
from threading import Thread
from unittest.mock import patch


def get_index(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Index.from_json(json_bytes.decode('utf-8'))


def get_channels(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Channels.from_json(json_bytes.decode('utf-8'))


class RequestHandler(SimpleHTTPRequestHandler):
    directory = None

    def translate_path(self, path):
        with patch('http.server.os.getcwd', return_value=self.directory):
            return super().translate_path(path)

    def log_message(self, *args, **kws):
        # Please shut up.
        pass


def make_http_server(directory):
    # We need an HTTP/S server to vend the file system, or at least parts of
    # it, that we want to test.  Since all the files are static, and we're
    # only going to GET files, this makes our lives much easier.  We'll just
    # vend all the files in the directory.
    #
    # Create the server in the main thread, but start it in the sub-thread.
    # This lets the main thread call .shutdown() to stop everything.  Return
    # just the shutdown method to the caller.
    RequestHandler.directory = directory
    server = HTTPServer(('localhost', 8909), RequestHandler)
    server.allow_reuse_address = True
    thread = Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    def shutdown():
        nonlocal server
        server.shutdown()
        thread.join()
        # This should reference count the server away, allowing for the
        # address to be properly reusable immediately.
        server.socket.close()
        server = None
    return shutdown


def make_temporary_cache(cleaner):
        tempdir = tempfile.mkdtemp()
        cleaner(shutil.rmtree, tempdir)
        ini_file = os.path.join(tempdir, 'config.ini')
        with atomic(ini_file) as fp:
            print("""\
[service]
base: http://localhost:8909/
[cache]
directory: {}
lifetime: 1d
[upgrade]
channel: stable
device: nexus7
""".format(tempdir), file=fp)
        config = Configuration()
        config.load(ini_file)
        return Cache(config)
