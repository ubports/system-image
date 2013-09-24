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
    'configuration',
    'copy',
    'data_path',
    'debug',
    'get_channels',
    'get_index',
    'make_http_server',
    'patience',
    'reset_envar',
    'setup_index',
    'setup_keyring_txz',
    'setup_keyrings',
    'sign',
    'touch_build',
    ]


import os
import ssl
import json
import time
import gnupg
import shutil
import inspect
import tarfile

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from functools import partial, wraps
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pkg_resources import resource_filename, resource_string as resource_bytes
from systemimage.channel import Channels
from systemimage.config import Configuration, config
from systemimage.helpers import atomic, makedirs, temporary_directory
from systemimage.index import Index
from threading import Thread
from unittest.mock import patch


EMPTYSTRING = ''


def get_index(filename):
    json_bytes = resource_bytes('systemimage.tests.data', filename)
    return Index.from_json(json_bytes.decode('utf-8'))


def get_channels(filename):
    json_bytes = resource_bytes('systemimage.tests.data', filename)
    return Channels.from_json(json_bytes.decode('utf-8'))


def data_path(filename):
    return os.path.abspath(
        resource_filename('systemimage.tests.data', filename))


def make_http_server(directory, port, certpem=None, keypem=None):
    """Create an HTTP/S server to vend from the file system.

    :param directory: The file system directory to vend files from.
    :param port: The port to listen on for the server.
    :param certpem: For HTTPS servers, the path to the certificate PEM file.
        If the file name does not start with a slash, it is considered
        relative to the test data directory.
    :param keypem: For HTTPS servers, the path to the key PEM file.  If the
        file name does not start with a slash, it is considered relative to
        the test data directory.
    :return: A context manager that when closed, stops the server.
    """
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

        def do_GET(self):
            # If we requested the magic 'user-agent.txt' file, send back the
            # value of the User-Agent header.  Otherwise, vend as normal.
            if self.path == '/user-agent.txt':
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                user_agent = self.headers.get('user-agent', 'no agent')
                self.end_headers()
                self.wfile.write(user_agent.encode('utf-8'))
            else:
                try:
                    super().do_GET()
                except BrokenPipeError:
                    # Canceling a download can cause our internal server to
                    # see a broken pipe.  No worries.
                    pass
    # Create the server in the main thread, but start it in the sub-thread.
    # This lets the main thread call .shutdown() to stop everything.  Return
    # just the shutdown method to the caller.
    RequestHandler.directory = directory
    # Wrap the socket in the SSL context if given.
    ssl_context = None
    if certpem is not None and keypem is not None:
        data_dir = os.path.dirname(data_path('__init__.py'))
        if not os.path.isabs(certpem):
            certpem = os.path.join(data_dir, certpem)
        if not os.path.isabs(keypem):
            keypem = os.path.join(data_dir, keypem)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_context.load_cert_chain(certfile=certpem, keyfile=keypem)
    # Define a small class with a method that arranges for the self-signed
    # certificates to be valid in the client.
    import sys
    connections = []
    class S(HTTPServer):
        def get_request(self):
            conn, addr = super().get_request()
            #print('CONN:', conn, 'ADDR:', addr, file=sys.stderr)
            connections.append(conn)
            return conn, addr
    with ExitStack() as stack:
        server = S(('localhost', port), RequestHandler)
        server.allow_reuse_address = True
        stack.callback(server.server_close)
        if ssl_context is not None:
            server.socket = ssl_context.wrap_socket(
                server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.daemon = True
        def shutdown():
            #import sys; print('SHUTDOWN', file=sys.stderr); sys.stderr.flush()
            import time; start = time.time()
            #print('CONN:', connections, file=sys.stderr)
            for conn in connections:
                conn.close()
            server.shutdown()
            end = time.time()
            if end - start > 5:
                import sys; print('SLOW', end - start, file=sys.stderr)
            thread.join()
        stack.callback(shutdown)
        thread.start()
        # Everything succeeded, so transfer the resource management to a new
        # ExitStack().  This way, when the with statement above completes, the
        # server will still be running and urlopen() will still be patched.
        # The caller is responsible for closing the new ExitStack.
        return stack.pop_all()


def configuration(function):
    """Decorator that produces a temporary configuration for testing.

    The config_00.ini template is copied to a temporary file and the
    [system]tempdir variable is filled in with the location for a, er,
    temporary temporary directory.  This temporary configuration file is
    loaded up and the global configuration object is patched so that all
    other code will see it instead of the default global configuration
    object.

    Everything is properly cleaned up after the test method exits.
    """
    @wraps(function)
    def wrapper(*args, **kws):
        with ExitStack() as stack:
            etc_dir = stack.enter_context(temporary_directory())
            ini_file = os.path.join(etc_dir, 'client.ini')
            temp_tmpdir = stack.enter_context(temporary_directory())
            temp_vardir = stack.enter_context(temporary_directory())
            template = resource_bytes(
                'systemimage.tests.data', 'config_00.ini').decode('utf-8')
            with atomic(ini_file) as fp:
                print(template.format(tmpdir=temp_tmpdir,
                                      vardir=temp_vardir), file=fp)
            config = Configuration()
            config.load(ini_file)
            stack.enter_context(patch('systemimage.config._config', config))
            stack.enter_context(patch('systemimage.device.check_output',
                                      return_value='nexus7'))
            # 2013-07-23 BAW: Okay, this is wicked.  If the test method takes
            # an 'ini_file' argument, pass the temporary ini file path to it
            # as a keyword argument.  Mostly I do this so that I don't have to
            # change the signature of every existing test method.
            signature = inspect.signature(function)
            if 'ini_file' in signature.parameters:
                kws['ini_file'] = ini_file
            return function(*args, **kws)
    return wrapper


def sign(filename, pubkey_ring):
    """GPG sign the given file, producing an armored detached signature.

    :param filename: The path to the file to sign.
    :param pubkey_ring: The public keyring containing the key to sign the file
        with.  This keyring must contain only one key, and its key id must
        exist in the master secret keyring.
    """
    with ExitStack() as stack:
        home = stack.enter_context(temporary_directory())
        secring = data_path('master-secring.gpg')
        pubring = data_path(pubkey_ring)
        ctx = gnupg.GPG(gnupghome=home, keyring=pubring,
                        #verbose=True,
                        secret_keyring=secring)
        public_keys = ctx.list_keys()
        assert len(public_keys) != 0, 'No keys found'
        assert len(public_keys) == 1, 'Too many keys'
        key_id = public_keys[0]['keyid']
        dfp = stack.enter_context(open(filename, 'rb'))
        signed_data = ctx.sign_file(dfp, keyid=key_id, detach=True)
        sfp = stack.enter_context(open(filename + '.asc', 'wb'))
        sfp.write(signed_data.data)


def copy(filename, todir, dst=None):
    src = data_path(filename)
    dst = os.path.join(todir, filename if dst is None else dst)
    makedirs(os.path.dirname(dst))
    shutil.copy(src, dst)


def setup_keyring_txz(keyring_src, signing_keyring, json_data, dst):
    """Set up the <keyring>.tar.xz and .asc files.

    The source keyring and json data is used to create a .tar.xz file
    and an associated .asc signature file.  These are then copied to the
    given destination path name.

    :param keyring_src: The name of the source keyring (i.e. .gpg file), which
        should be relative to the test data directory.  This will serve as the
        keyring.gpg file inside the tarball.
    :param signing_keyring: The name of the keyring to sign the resulting
        tarball with, again, relative to the test data directory.
    :param json_data: The JSON data dictionary, i.e. the contents of the
        keyring.json file inside the tarball.
    :param dst: The destination path of the .tar.xz file.  For the resulting
        signature file, the .asc suffix will be automatically appended and
        copied next to the dst file.
    """
    with temporary_directory() as tmpdir:
        copy(keyring_src, tmpdir, 'keyring.gpg')
        json_path = os.path.join(tmpdir, 'keyring.json')
        with open(json_path, 'w', encoding='utf-8') as fp:
            json.dump(json_data, fp)
        # Tar up the .gpg and .json files into a .tar.xz file.
        tarxz_path = os.path.join(tmpdir, 'keyring.tar.xz')
        with tarfile.open(tarxz_path, 'w:xz') as tf:
            tf.add(os.path.join(tmpdir, 'keyring.gpg'), 'keyring.gpg')
            tf.add(json_path, 'keyring.json')
        sign(tarxz_path, signing_keyring)
        # Copy the .tar.xz and .asc files to the proper directory under
        # the path the https server is vending them from.
        makedirs(os.path.dirname(dst))
        shutil.copy(tarxz_path, dst)
        shutil.copy(tarxz_path + '.asc', dst + '.asc')


def setup_keyrings(*keyrings, use_config=None):
    """Copy the named keyrings to the right place.

    Also, set up the .xz.tar and .xz.tar.asc files which must exist in order
    to be copied to the updater partitions.

    :param keyrings: When given, names the keyrings to set up.  When not
        given, all keyrings are set up.  Each entry should be the name of the
        configuration variable inside the `config.gpg` namespace,
        e.g. 'archive_master'.
    :param use_config: If given, use this as the config object, otherwise use
        the global config object.
    """
    if len(keyrings) == 0:
        keyrings = ('archive-master', 'image-master', 'image-signing',
                    'device-signing')
    for keyring in keyrings:
        if keyring in ('archive-master', 'image-master'):
            # Yes, the archive master is signed by itself.
            signing_kr = 'archive-master.gpg'
        elif keyring == 'image-signing':
            signing_kr = 'image-master.gpg'
        elif keyring == 'device-signing':
            signing_kr = 'image-signing.gpg'
        else:
            raise AssertionError('unknown key type: {}'.format(keyring))
        # The local keyrings life in the .gpg file with the same keyring name
        # as the .tar.xz file, but cached in the temporary directory.
        copy(keyring + '.gpg', (config.system.tempdir if use_config is None
                                else use_config.system.tempdir))
        # Now set up the .tar.xz and .tar.xz.asc files in the destination.
        json_data = dict(type=keyring)
        dst = getattr((config.gpg if use_config is None
                       else use_config.gpg),
                      keyring.replace('-', '_'))
        setup_keyring_txz(keyring + '.gpg', signing_kr, json_data, dst)


def setup_index(index, todir, keyring):
    for image in get_index(index).images:
        for filerec in image.files:
            path = (filerec.path[1:]
                    if filerec.path.startswith('/')
                    else filerec.path)
            dst = os.path.join(todir, path)
            makedirs(os.path.dirname(dst))
            contents = EMPTYSTRING.join(
                os.path.splitext(filerec.path)[0].split('/'))
            with open(dst, 'w', encoding='utf-8') as fp:
                fp.write(contents)
            # Sign with the imaging signing key.  Some tests will
            # re-sign all these files with the device key.
            sign(dst, keyring)


@contextmanager
def reset_envar(name):
    missing = object()
    old_value = os.environ.get(name, missing)
    try:
        yield
    finally:
        if old_value is missing:
            try:
                del os.environ[name]
            except KeyError:
                pass
        else:
            os.environ[name] = old_value


def touch_build(version, timestamp=None):
    with open(config.system.build_file, 'w', encoding='utf-8') as fp:
        print(version, file=fp)
    if timestamp is not None:
        timestamp = int(timestamp)
        os.utime(config.system.build_file, (timestamp, timestamp))
        channel_ini = os.path.join(
            os.path.dirname(config.config_file), 'channel.ini')
        try:
            os.utime(channel_ini, (timestamp, timestamp))
        except FileNotFoundError:
            pass


@contextmanager
def debug():
    with open('/tmp/debug.log', 'a', encoding='utf-8') as fp:
        yield partial(print, file=fp)


@contextmanager
def patience(exception):
    until = datetime.now() + timedelta(seconds=60)
    while datetime.now() < until:
        time.sleep(0.1)
        try:
            yield
        except exception:
            break
    else:
        raise RuntimeError('Process did not exit')
