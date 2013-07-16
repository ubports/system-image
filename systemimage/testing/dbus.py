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
import shutil
import signal
import subprocess

from contextlib import ExitStack
from distutils.spawn import find_executable
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import test_data_path


SERVICES = [
    'com.canonical.SystemImage',
    ]


class Controller:
    """Start and stop the SystemImage dbus service under test."""

    def __init__(self):
        self._stack = ExitStack()
        self.tmpdir = self._stack.enter_context(temporary_directory())
        self.config_path = os.path.join(self.tmpdir, 'dbus-session.conf')
        self.is_runnable = False

    def _setup(self):
        # Set up the dbus-daemon session configuration file.
        with open(test_data_path('dbus-session.conf.in'),
                  'r', encoding='utf-8') as fp:
            template = fp.read()
        config = template.format(tmpdir=self.tmpdir)
        with open(self.config_path, 'w', encoding='utf-8') as fp:
            fp.write(config)
        # Now we have to set up the .service files.  We use the Python
        # executable used to run the tests, executing the entry point as would
        # happen in a deployed script or virtualenv.
        command = [sys.executable, '-m', 'systemimage.service']
        for service in SERVICES:
            service_file = service + '.service'
            with open(test_data_path(service_file + '.in'),
                      'r', encoding='utf-8') as fp:
                template = fp.read()
            config = template.format(command=command)
            service_path = os.path.join(self.tmpdir, service_file)
            with open(service_path, 'w', encoding='utf-8') as fp:
                fp.write(config)

    def start(self):
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
        dbus_args = [
            daemon_exe,
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
        self._stack.callback(os.kill, daemon_pid, signal.SIGTERM)
        print('address:', dbus_address, 'pid:', daemon_pid)
        # Set the service's address into the environment for rendezvous.
        self._stack.enter_context(reset_envar('DBUS_SESSION_BUS_ADDRESS'))
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus_address
        self.is_runnable = True

    def shutdown(self):
        self._stack.close()
