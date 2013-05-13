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
    'copy',
    'get_channels',
    'get_index',
    'make_http_server',
    'makedirs',
    'sign',
    'test_configuration',
    ]


import os
import gnupg
import shutil
import tempfile

from contextlib import ExitStack
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pkg_resources import resource_filename, resource_string as resource_bytes
from resolver.channel import Channels
from resolver.config import Configuration
from resolver.helpers import atomic
from resolver.index import Index
from threading import Thread
from unittest.mock import patch


def get_index(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Index.from_json(json_bytes.decode('utf-8'))


def get_channels(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Channels.from_json(json_bytes.decode('utf-8'))


def make_http_server(directory, port, ssl_context=None):
    # We need an HTTP/S server to vend the file system, or at least parts of
    # it, that we want to test.  Since all the files are static, and we're
    # only going to GET files, this makes our lives much easier.  We'll just
    # vend all the files in the directory.
    class RequestHandler(SimpleHTTPRequestHandler):
        # The base class hardcodes the use of os.getcwd() to vend the
        # files from, but we want to be able to pass in any directory.  I
        # suppose we could chdir in the server thread, but let's hack the
        # path instead.
        def translate_path(self, path):
            with patch('http.server.os.getcwd', return_value=directory):
                return super().translate_path(path)

        def log_message(self, *args, **kws):
            # Please shut up.
            pass
    # Create the server in the main thread, but start it in the sub-thread.
    # This lets the main thread call .shutdown() to stop everything.  Return
    # just the shutdown method to the caller.
    RequestHandler.directory = directory
    server = HTTPServer(('localhost', port), RequestHandler)
    server.allow_reuse_address = True
    # Wrap the socket in the SSL context if given.
    if ssl_context is not None:
        server.socket = ssl_context.wrap(server.socket, server_side=True)
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


def test_configuration(function):
    """Test decorator that produces a temporary configuration.

    The config_00.ini template is copied to a temporary file and the
    [system]tempdir variable is filled in with the location for a, er,
    temporary temporary directory.  This temporary configuration file is
    loaded up and the global configuration object is patched so that all
    other code will see it instead of the default global configuration
    object.

    Everything is properly cleaned up after the test method exits.
    """
    def wrapper(*args, **kws):
        with ExitStack() as stack:
            fd, ini_file = tempfile.mkstemp(suffix='.ini')
            os.close(fd)
            stack.callback(os.remove, ini_file)
            temp_tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, temp_tempdir)
            template = resource_bytes(
                'resolver.tests.data', 'config_00.ini').decode('utf-8')
            with atomic(ini_file) as fp:
                print(template.format(tmpdir=temp_tempdir), file=fp)
            config = Configuration()
            config.load(ini_file)
            stack.enter_context(patch('resolver.config._config', config))
            return function(*args, **kws)
    return wrapper


def sign(homedir, filename, ring_files=None):
    """GPG sign the given file, producing an armored detached signature."""
    # The version of python3-gnupg in Ubuntu 13.04 is too old to support the
    # `options` constructor keyword, so hack around it.
    if ring_files is None:
        pubring = 'pubring_01.gpg'
        secring = 'secring_01.gpg'
    else:
        pubring, secring = ring_files
    class Signing(gnupg.GPG):
        def _open_subprocess(self, args, passphrase=False):
            args.append('--secret-keyring {}'.format(secring))
            return super()._open_subprocess(args, passphrase)
    ctx = Signing(gnupghome=homedir,
                  keyring=os.path.join(homedir, pubring))
    with open(filename, 'rb') as dfp:
        signed_data = ctx.sign_file(dfp, detach=True)
    with open(filename + '.asc', 'wb') as sfp:
        sfp.write(signed_data.data)


def makedirs(dir):
    try:
        os.makedirs(dir)
    except FileExistsError:
        pass


def copy(filename, todir, dst=None):
    src = resource_filename('resolver.tests.data', filename)
    dst = os.path.join(todir, filename if dst is None else dst)
    makedirs(os.path.dirname(dst))
    shutil.copy(src, dst)
