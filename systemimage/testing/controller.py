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

"""Helper for testing the dbus service via dbus over a separate test bus."""


__all__ = [
    'Controller',
    ]


import os
import sys
import time
import shutil
import signal
import datetime
import subprocess

from contextlib import ExitStack
from distutils.spawn import find_executable
from pkg_resources import resource_string as resource_bytes
from systemimage.config import Configuration
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import (
    copy, make_http_server, reset_envar, setup_index, setup_keyring_txz,
    setup_keyrings, sign, test_data_path)


SPACE = ' '
SERVICES = [
    'com.canonical.SystemImage',
    ]


class Controller:
    """Start and stop the SystemImage dbus service under test."""

    def __init__(self, index_file):
        self._stack = ExitStack()
        self.index_file = index_file
        self.tmpdir = self._stack.enter_context(temporary_directory())
        self.config_path = os.path.join(self.tmpdir, 'dbus-session.conf')
        self.ini_path = None

    def _setup(self):
        # Set up the dbus-daemon session configuration file.
        with open(test_data_path('dbus-session.conf.in'),
                  'r', encoding='utf-8') as fp:
            template = fp.read()
        config = template.format(tmpdir=self.tmpdir)
        with open(self.config_path, 'w', encoding='utf-8') as fp:
            fp.write(config)
        # We need a client.ini file for the subprocess.
        ini_tmpdir = self._stack.enter_context(temporary_directory())
        ini_vardir = self._stack.enter_context(temporary_directory())
        self.ini_path = os.path.join(self.tmpdir, 'client.ini')
        template = resource_bytes(
            'systemimage.tests.data', 'config_00.ini').decode('utf-8')
        with open(self.ini_path, 'w', encoding='utf-8') as fp:
            print(template.format(tmpdir=ini_tmpdir, vardir=ini_vardir),
                  file=fp)
        # Now we have to set up the .service files.  We use the Python
        # executable used to run the tests, executing the entry point as would
        # happen in a deployed script or virtualenv.
        command = [sys.executable,
                   '-m', 'systemimage.service',
                   '-C', self.ini_path,
                   '--testing',
                   ]
        for service in SERVICES:
            service_file = service + '.service'
            with open(test_data_path(service_file + '.in'),
                      'r', encoding='utf-8') as fp:
                template = fp.read()
            config = template.format(command=SPACE.join(command))
            service_path = os.path.join(self.tmpdir, service_file)
            with open(service_path, 'w', encoding='utf-8') as fp:
                fp.write(config)
        # Next piece of the puzzle is to set up the http/https servers that
        # the dbus client will talk to.
        serverdir = self._stack.enter_context(temporary_directory())
        # Start up both an HTTPS and HTTP server.  The data files are
        # vended over the latter, everything else, over the former.
        self._stack.push(make_http_server(
            serverdir, 8943, 'cert.pem', 'key.pem'))
        self._stack.push(make_http_server(serverdir, 8980))
        # Set up the server files.
        copy('channels_06.json', serverdir, 'channels.json')
        sign(os.path.join(serverdir, 'channels.json'), 'image-signing.gpg')
        index_path = os.path.join(serverdir, 'stable', 'nexus7', 'index.json')
        head, tail = os.path.split(index_path)
        copy(self.index_file, head, tail)
        sign(index_path, 'device-signing.gpg')
        setup_index(self.index_file, serverdir, 'device-signing.gpg')
        # Only the archive-master key is pre-loaded.  All the other keys
        # are downloaded and there will be both a blacklist and device
        # keyring.  The four signed keyring tar.xz files and their
        # signatures end up in the proper location after the state machine
        # runs to completion.
        config = Configuration()
        config.load(self.ini_path)
        setup_keyrings('archive-master', use_config=config)
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(serverdir, 'gpg', 'image-signing.tar.xz'))
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(serverdir, 'stable', 'nexus7',
                         'device-signing.tar.xz'))

    def _start(self):
        """Start the SystemImage service in a subprocess.

        Use the output from dbus-daemon to gather the address and pid of the
        service in the subprocess.  We'll use those in the foreground process
        to talk to our test instance of the service (rather than any similar
        service running normally on the development desktop).
        """
        daemon_exe = find_executable('dbus-daemon')
        if daemon_exe is None:
            print('Cannot find the `dbus-daemon` executable', file=sys.stderr)
            return
        self._setup()
        os.environ['DBUS_VERBOSE'] = '1'
        dbus_args = [
            daemon_exe,
            #'/usr/lib/x86_64-linux-gnu/dbus-1.0/debug-build/bin/dbus-daemon',
            '--fork',
            '--config-file=' + self.config_path,
            # Return the address and pid on stdout.
            '--print-address=1',
            '--print-pid=1',
            ]
        stdout = subprocess.check_output(dbus_args, bufsize=4096,
                                         universal_newlines=True)
        lines = stdout.splitlines()
        dbus_address = lines[0].strip()
        daemon_pid = int(lines[1].strip())
        self._stack.callback(self._kill, daemon_pid)
        #print('address:', dbus_address, 'pid:', daemon_pid)
        # Set the service's address into the environment for rendezvous.
        self._stack.enter_context(reset_envar('DBUS_SESSION_BUS_ADDRESS'))
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus_address

    def start(self):
        try:
            self._start()
        except:
            self._stack.close()
            raise

    def _kill(self, pid):
        os.kill(pid, signal.SIGTERM)
        # Wait for it to die.
        until = datetime.datetime.now() + datetime.timedelta(seconds=10)
        while datetime.datetime.now() < until:
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break

    def shutdown(self):
        self._stack.close()
