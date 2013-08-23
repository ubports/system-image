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
import pwd
import sys
import time
import signal
import datetime
import subprocess

from contextlib import ExitStack
from distutils.spawn import find_executable
from pkg_resources import resource_string as resource_bytes
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import data_path, reset_envar


SPACE = ' '
SERVICES = [
    'com.canonical.SystemImage',
    ]


class Controller:
    """Start and stop the SystemImage dbus service under test."""

    def __init__(self):
        self._stack = ExitStack()
        self.tmpdir = self._stack.enter_context(temporary_directory())
        self.config_path = os.path.join(self.tmpdir, 'dbus-system.conf')
        self.ini_path = None
        self.serverdir = self._stack.enter_context(temporary_directory())
        self.daemon_pid = None
        # Set up the dbus-daemon system configuration file.
        path = data_path('dbus-system.conf.in')
        with open(path, 'r', encoding='utf-8') as fp:
            template = fp.read()
        username = pwd.getpwuid(os.getuid()).pw_name
        config = template.format(tmpdir=self.tmpdir, user=username)
        with open(self.config_path, 'w', encoding='utf-8') as fp:
            fp.write(config)
        # We need a client.ini file for the subprocess.
        ini_tmpdir = self._stack.enter_context(temporary_directory())
        ini_vardir = self._stack.enter_context(temporary_directory())
        self.ini_path = os.path.join(self.tmpdir, 'client.ini')
        template = resource_bytes(
            'systemimage.tests.data', 'config_03.ini').decode('utf-8')
        with open(self.ini_path, 'w', encoding='utf-8') as fp:
            print(template.format(tmpdir=ini_tmpdir, vardir=ini_vardir),
                  file=fp)

    def set_testing_mode(self, mode):
        """Set up a new testing mode and SIGHUP dbus-daemon."""
        # Now we have to set up the .service files.  We use the Python
        # executable used to run the tests, executing the entry point as would
        # happen in a deployed script or virtualenv.
        command = [sys.executable,
                   '-m', 'systemimage.service',
                   '-C', self.ini_path,
                   '--testing', mode,
                   ]
        for service in SERVICES:
            service_file = service + '.service'
            path = data_path(service_file + '.in')
            with open(path, 'r', encoding='utf-8') as fp:
                template = fp.read()
            config = template.format(command=SPACE.join(command))
            service_path = os.path.join(self.tmpdir, service_file)
            with open(service_path, 'w', encoding='utf-8') as fp:
                fp.write(config)
        # Only if the daemon is already running.
        if self.daemon_pid is not None:
            os.kill(self.daemon_pid, signal.SIGHUP)

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
        self.daemon_pid = int(lines[1].strip())
        self._stack.callback(self._kill, self.daemon_pid)
        #print("DBUS_SYSTEM_BUS_ADDRESS='{}'".format(dbus_address))
        # Set the service's address into the environment for rendezvous.
        self._stack.enter_context(reset_envar('DBUS_SYSTEM_BUS_ADDRESS'))
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = dbus_address

    def start(self):
        if self.daemon_pid is not None:
            # Already started.
            return
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
        self.daemon_pid = None

    def shutdown(self):
        self._stack.close()
