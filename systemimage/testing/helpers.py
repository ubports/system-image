# Copyright (C) 2013-2015 Canonical Ltd.
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
    'ServerTestBase',
    'chmod',
    'configuration',
    'copy',
    'data_path',
    'debug',
    'debuggable',
    'descriptions',
    'find_dbus_process',
    'get_channels',
    'get_index',
    'make_http_server',
    'reset_envar',
    'setup_index',
    'setup_keyring_txz',
    'setup_keyrings',
    'sign',
    'touch_build',
    'write_bytes',
    ]


import os
import ssl
import json
import gnupg
import psutil
import shutil
import inspect
import tarfile
import unittest

from contextlib import ExitStack, contextmanager, suppress
from functools import partial, partialmethod, wraps
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from pkg_resources import resource_filename, resource_string as resource_bytes
from socket import SHUT_RDWR
from systemimage.channel import Channels
from systemimage.config import Configuration, config
from systemimage.helpers import MiB, atomic, makedirs, temporary_directory
from systemimage.index import Index
from threading import Thread
from unittest.mock import patch


EMPTYSTRING = ''
SPACE = ' '


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

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except ConnectionResetError:
                super().handle_one_request()

        def do_HEAD(self):
            # Just tell the client we have the magic file.
            if self.path == '/user-agent.txt':
                self.send_response(200)
                self.end_headers()
            else:
                # Canceling a download can cause our internal server to
                # see various ignorable errors.  No worries.
                with suppress(BrokenPipeError, ConnectionResetError):
                    super().do_HEAD()

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
                # Canceling a download can cause our internal server to
                # see various ignorable errors.  No worries.
                with suppress(BrokenPipeError, ConnectionResetError):
                    super().do_GET()
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
    # This subclass specializes connection requests so that we can keep track
    # of connections and force shutting down both sides of the socket.  The
    # download service has a hack to clear its connection hack during the test
    # suite (specifically, when -stoppable is given), but this just ensures
    # that we do everything we can on our end to close the connections.  If we
    # don't our HTTP/S servers hang around for 2+ minutes due to issues with
    # the Qt networking stack, causing huge slowdowns on our test teardown
    # methods.
    connections = []
    class Server(HTTPServer):
        def get_request(self):
            conn, addr = super().get_request()
            connections.append(conn)
            return conn, addr
    # Define a small class with a method that arranges for the self-signed
    # certificates to be valid in the client.
    with ExitStack() as resources:
        server = Server(('localhost', port), RequestHandler)
        server.allow_reuse_address = True
        resources.callback(server.server_close)
        if ssl_context is not None:
            server.socket = ssl_context.wrap_socket(
                server.socket, server_side=True)
        thread = Thread(target=server.serve_forever)
        thread.daemon = True
        def shutdown():
            for conn in connections:
                if conn.fileno() != -1:
                    # Disallow sends and receives.
                    try:
                        conn.shutdown(SHUT_RDWR)
                    except OSError:
                        # I'm ignoring all OSErrors here, although the only
                        # one I've seen semi-consistency is ENOTCONN [107]
                        # "Transport endpoint is not connected".  I don't know
                        # why this happens, but it tells me that the client
                        # has already exited.  We're shutting down, so who
                        # cares?  (Or am I masking a real error?)
                        pass
                conn.close()
            server.shutdown()
            thread.join()
        resources.callback(shutdown)
        thread.start()
        # Everything succeeded, so transfer the resource management to a new
        # ExitStack().  This way, when the with statement above completes, the
        # server will still be running and urlopen() will still be patched.
        # The caller is responsible for closing the new ExitStack.
        return resources.pop_all()


# This defines the @configuration decorator used in various test suites to
# create a temporary config.d/ directory for a test.  This is all fairly
# complicated, but here's what's going on.
#
# The _wrapper() function is the inner part of the decorator, and it does the
# heart of the operation, which is to create a temporary directory for
# config.d, along with temporary var and tmp directories.  These latter two
# will be interpolated into any configuration file copied into config.d.
#
# The outer decorator function differs depending on whether @configuration was
# given without arguments, or called with arguments at the time of the
# function definition.
#
# In the former case, e.g.
#
# @configuration
# def test_something(self):
#
# The default 00.ini file is interpolated and copied into config.d.  Simple.
#
# In the latter case, e.g.
#
# @configuration('some-config.ini')
# def test_something(self):
#
# There's actually another level of interior function, because the outer
# decorator itself is getting called.  Here, any named configuration file is
# additionally copied to the config.d directory, renaming it sequentionally to
# something like 01_override.ini, with the numeric part incrementing
# monotonically.
#
# The implementation is tricky because we want the call sites to be simple.
def _wrapper(self, function, ini_files, *args, **kws):
    start = 0
    with ExitStack() as resources:
        # Create the config.d directory and copy all the source ini files to
        # this directory in sequential order, interpolating in the temporary
        # tmp and var directories.
        config_d = resources.enter_context(temporary_directory())
        temp_tmpdir = resources.enter_context(temporary_directory())
        temp_vardir = resources.enter_context(temporary_directory())
        for ini_file in ini_files:
            dst = os.path.join(config_d, '{:02d}_override.ini'.format(start))
            start += 1
            template = resource_bytes(
                'systemimage.tests.data', ini_file).decode('utf-8')
            with atomic(dst) as fp:
                print(template.format(tmpdir=temp_tmpdir,
                                      vardir=temp_vardir), file=fp)
        # Patch the global configuration object so that it can be used
        # directly, which is good enough in most cases.  Also patch the bit of
        # code that detects the device name.
        config = Configuration(config_d)
        resources.enter_context(
            patch('systemimage.config._config', config))
        resources.enter_context(
            patch('systemimage.device.check_output',
                  return_value='nexus7'))
        # Make sure the cache_partition and data_partition exist.
        makedirs(config.updater.cache_partition)
        makedirs(config.updater.data_partition)
        # The method under test is allowed to specify some additional
        # keyword arguments, in order to pass some variables in from the
        # wrapper.
        signature = inspect.signature(function)
        if 'config_d' in signature.parameters:
            kws['config_d'] = config_d
        if 'config' in signature.parameters:
            kws['config'] = config
        # Call the function with the given arguments and return the result.
        return function(self, *args, **kws)


def configuration(*args):
    """Outer decorator which can be called or not at function definition time.

    If called, the arguments are positional only, and name the test data .ini
    files which are to be copied to config.d directory.  If none are given,
    then 00.ini is used.
    """
    if len(args) == 1 and callable(args[0]):
        # We assume this was the bare @configuration decorator flavor.
        function = args[0]
        inner = partialmethod(_wrapper, function, ('00.ini',))
        return wraps(function)(inner)
    else:
        # We assume this was the called @configuration(...) decorator flavor,
        # so create the actual decorator that wraps the _wrapper function.
        def decorator(function):
            inner = partialmethod(_wrapper, function, args)
            return wraps(function)(inner)
        return decorator


def sign(filename, pubkey_ring):
    """GPG sign the given file, producing an armored detached signature.

    :param filename: The path to the file to sign.
    :param pubkey_ring: The public keyring containing the key to sign the file
        with.  This keyring must contain only one key, and its key id must
        exist in the master secret keyring.
    """
    # filename could be a Path object.  For now, just str-ify it.
    filename = str(filename)
    with ExitStack() as resources:
        home = resources.enter_context(temporary_directory())
        secring = data_path('master-secring.gpg')
        pubring = data_path(pubkey_ring)
        ctx = gnupg.GPG(gnupghome=home, keyring=pubring,
                        #verbose=True,
                        secret_keyring=secring)
        public_keys = ctx.list_keys()
        assert len(public_keys) != 0, 'No keys found'
        assert len(public_keys) == 1, 'Too many keys'
        key_id = public_keys[0]['keyid']
        dfp = resources.enter_context(open(filename, 'rb'))
        signed_data = ctx.sign_file(dfp, keyid=key_id, detach=True)
        sfp = resources.enter_context(open(filename + '.asc', 'wb'))
        sfp.write(signed_data.data)


def copy(filename, todir, dst=None):
    src = data_path(filename)
    dst = os.path.join(str(todir), filename if dst is None else dst)
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


def setup_keyrings(*keyrings, use_config=None, **data):
    """Copy the named keyrings to the right place.

    Also, set up the .xz.tar and .xz.tar.asc files which must exist in order
    to be copied to the updater partitions.

    :param keyrings: When given, names the keyrings to set up.  When not
        given, all keyrings are set up.  Each entry should be the name of the
        configuration variable inside the `config.gpg` namespace,
        e.g. 'archive_master'.
    :param use_config: If given, use this as the config object, otherwise use
        the global config object.
    :param data: Additional key/value data to insert into the keyring.json
        dictionary.
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
        # The local keyrings live in the .gpg file with the same keyring name
        # as the .tar.xz file, but cached in the temporary directory.
        copy(keyring + '.gpg', (config.tempdir if use_config is None
                                else use_config.tempdir))
        # Now set up the .tar.xz and .tar.xz.asc files in the destination.
        json_data = dict(type=keyring)
        json_data.update(data)
        dst = getattr((config.gpg if use_config is None
                       else use_config.gpg),
                      keyring.replace('-', '_'))
        setup_keyring_txz(keyring + '.gpg', signing_kr, json_data, dst)


def setup_index(index, todir, keyring, write_callback=None):
    for image in get_index(index).images:
        for filerec in image.files:
            path = (filerec.path[1:]
                    if filerec.path.startswith('/')
                    else filerec.path)
            dst = os.path.join(todir, path)
            makedirs(os.path.dirname(dst))
            if write_callback is None:
                contents = EMPTYSTRING.join(
                    os.path.splitext(filerec.path)[0].split('/'))
                with open(dst, 'w', encoding='utf-8') as fp:
                    fp.write(contents)
            else:
                write_callback(dst)
            # Sign with the specified signing key.
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


@contextmanager
def chmod(path, new_mode):
    old_mode = os.stat(path).st_mode
    try:
        os.chmod(path, new_mode)
        yield
    finally:
        os.chmod(path, old_mode)


def touch_build(version, timestamp=None, use_config=None):
    # LP: #1220238 - assert that no old-style version numbers are being used.
    assert 0 <= version < (1 << 16), (
        'Old style version number: {}'.format(version))
    if use_config is None:
        use_config = config
    override = Path(use_config.config_d) / '99_build.ini'
    with override.open('wt', encoding='utf-8') as fp:
        print("""\
[service]
build_number: {}
""".format(version), file=fp)
    # We have to touch the mtimes for all the files in the config directory.
    if timestamp is not None:
        timestamp = int(timestamp)
        for path in Path(use_config.config_d).iterdir():
            os.utime(str(path), (timestamp, timestamp))
    use_config.reload()


def write_bytes(path, size_in_mib):
    # Write size_in_mib * 1MiB number of bytes to the file in path.
    with open(path, 'wb') as fp:
        for chunk in range(size_in_mib):
            fp.write(b'x' * MiB)


def debuggable(fn):
    def wrapper(*args, **kws):
        try:
            path = Path('/tmp/debug.enabled')
            path.touch()
            return fn(*args, **kws)
        finally:
            path.unlink()
    return wrapper


@contextmanager
def debug(*, check_flag=False, end='\n'):
    if not check_flag or os.path.exists('/tmp/debug.enabled'):
        path = Path('/tmp/debug.log')
    else:
        path = Path(os.devnull)
    with path.open('a', encoding='utf-8') as fp:
        function = partial(print, file=fp, end=end)
        function.fp = fp
        yield function
        fp.flush()


def find_dbus_process(ini_path):
    """Return the system-image-dbus process running the given ini file."""
    # This method searches all processes for the one matching the
    # system-image-dbus service.  This is harder than it should be because
    # while dbus-launch gives us the PID of the dbus-launch process itself,
    # that can't be used to find the appropriate child process, because
    # D-Bus activated processes are orphaned to init as their parent.
    #
    # This then does a brute-force search over all the processes, looking one
    # that has a particular command line indicating that it's the
    # system-image-dbus service.  We don't run this latter by that name
    # though, since that's a wrapper created by setup.py's entry points.
    #
    # To make doubly certain we're not going to get the wrong process (in case
    # there are multiple system-image-dbus processes running), we'll also look
    # for the specific ini_path for the instance we care about.  Yeah, this
    # all kind of sucks, but should be effective in finding the one we need to
    # track.
    from systemimage.testing.controller import Controller
    for process in psutil.process_iter():
        cmdline = SPACE.join(process.cmdline())
        if Controller.MODULE in cmdline and ini_path in cmdline:
            return process
    return None


class ServerTestBase(unittest.TestCase):
    # Must override in base classes.
    INDEX_FILE = None
    CHANNEL_FILE = None
    CHANNEL = None
    DEVICE = None
    SIGNING_KEY = 'device-signing.gpg'

    # For more detailed output.
    maxDiff = None

    @classmethod
    def setUpClass(self):
        # Avoid circular imports.
        from systemimage.testing.nose import SystemImagePlugin
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        # Avoid circular imports.
        from systemimage.state import State
        self._resources = ExitStack()
        self._state = State()
        try:
            self._serverdir = self._resources.enter_context(
                temporary_directory())
            # Start up both an HTTPS and HTTP server.  The data files are
            # vended over the latter, everything else, over the former.
            self._resources.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
            self._resources.push(make_http_server(self._serverdir, 8980))
            # Set up the server files.
            assert self.CHANNEL_FILE is not None, (
                'Subclasses must set CHANNEL_FILE')
            copy(self.CHANNEL_FILE, self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            assert self.CHANNEL is not None, 'Subclasses must set CHANNEL'
            assert self.DEVICE is not None, 'Subclasses must set DEVICE'
            index_path = os.path.join(
                self._serverdir, self.CHANNEL, self.DEVICE, 'index.json')
            head, tail = os.path.split(index_path)
            assert self.INDEX_FILE is not None, (
                'Subclasses must set INDEX_FILE')
            copy(self.INDEX_FILE, head, tail)
            sign(index_path, self.SIGNING_KEY)
            setup_index(self.INDEX_FILE, self._serverdir, self.SIGNING_KEY)
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()

    def _setup_server_keyrings(self, *, device_signing=True):
        # Only the archive-master key is pre-loaded.  All the other keys
        # are downloaded and there will be both a blacklist and device
        # keyring.  The four signed keyring tar.xz files and their
        # signatures end up in the proper location after the state machine
        # runs to completion.
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        if device_signing:
            setup_keyring_txz(
                'device-signing.gpg', 'image-signing.gpg',
                dict(type='device-signing'),
                os.path.join(self._serverdir, self.CHANNEL, self.DEVICE,
                             'device-signing.tar.xz'))


def descriptions(path):
    descriptions = []
    for image in path:
        # There's only one description per image so order doesn't
        # matter.
        descriptions.extend(image.descriptions.values())
    return descriptions
