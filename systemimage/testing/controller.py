# Copyright (C) 2013-2014 Canonical Ltd.
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
import dbus
import time
import psutil
import pycurl
import subprocess

from contextlib import ExitStack
from distutils.spawn import find_executable
from pkg_resources import resource_string as resource_bytes
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import (
    data_path, find_dbus_process, reset_envar)
from unittest.mock import patch


SPACE = ' '
OVERRIDE = os.environ.get('SYSTEMIMAGE_DBUS_DAEMON_HUP_SLEEP_SECONDS')
HUP_SLEEP = (0 if OVERRIDE is None else int(OVERRIDE))


def start_system_image(controller):
    bus = dbus.SystemBus()
    service = bus.get_object('com.canonical.SystemImage', '/Service')
    iface = dbus.Interface(service, 'com.canonical.SystemImage')
    iface.Info()
    process = find_dbus_process(controller.ini_path)
    if process is None:
        raise RuntimeError('Could not start system-image-dbus')


def stop_system_image(controller):
    if controller.ini_path is None:
        process = None
    else:
        process = find_dbus_process(controller.ini_path)
    try:
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        iface = dbus.Interface(service, 'com.canonical.SystemImage')
        iface.Exit()
    except dbus.DBusException:
        # The process might not be running at all.
        return
    if process is not None:
        process.wait(60)


def _find_udm_process():
    for process in psutil.process_iter():
        cmdline = SPACE.join(process.cmdline())
        if 'ubuntu-download-manager' in cmdline and '-stoppable' in cmdline:
            return process
    return None


def start_downloader(controller):
    bus = dbus.SystemBus()
    service = bus.get_object('com.canonical.applications.Downloader', '/')
    iface = dbus.Interface(
        service, 'com.canonical.applications.DownloadManager')
    # Something innocuous.
    iface.defaultThrottle()
    process = _find_udm_process()
    if process is None:
        raise RuntimeError('Could not start ubuntu-download-manager')


def stop_downloader(controller):
    # See find_dbus_process() for details.
    process = _find_udm_process()
    try:
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.applications.Downloader', '/')
        iface = dbus.Interface(
            service, 'com.canonical.applications.DownloadManager')
        iface.exit()
    except dbus.DBusException:
        # The process might not be running at all.
        return
    if process is not None:
        process.wait(60)


DLSERVICE = '/usr/bin/ubuntu-download-manager'
# For debugging the in-tree version of u-d-m.
#DLSERVICE = '/bin/sh /home/barry/projects/phone/runme'


SERVICES = [
   ('com.canonical.SystemImage',
    '{python} -m {self.MODULE} -C {self.ini_path} --testing {self.mode}',
    start_system_image,
    stop_system_image,
   ),
   ('com.canonical.applications.Downloader',
    DLSERVICE +
        ' {self.certs} -disable-timeout -stoppable -log-dir {self.tmpdir}',
    start_downloader,
    stop_downloader,
   ),
   ]


class Controller:
    """Start and stop D-Bus service under test."""

    MODULE = 'systemimage.testing.service'

    def __init__(self, logfile=None, loglevel='info'):
        # Non-public.
        self._stack = ExitStack()
        self._stoppers = []
        # Public.
        self.tmpdir = self._stack.enter_context(temporary_directory())
        self.config_path = os.path.join(self.tmpdir, 'dbus-system.conf')
        self.ini_path = None
        self.serverdir = self._stack.enter_context(temporary_directory())
        self.daemon_pid = None
        self.mode = 'live'
        self.certs = ''
        self.patcher = None
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
        ini_logfile = (os.path.join(ini_tmpdir, 'client.log')
                       if logfile is None
                       else logfile)
        self.ini_path = os.path.join(self.tmpdir, 'client.ini')
        template = resource_bytes(
            'systemimage.tests.data', 'config_03.ini').decode('utf-8')
        with open(self.ini_path, 'w', encoding='utf-8') as fp:
            print(template.format(tmpdir=ini_tmpdir,
                                  vardir=ini_vardir,
                                  logfile=ini_logfile,
                                  loglevel=loglevel),
                  file=fp)

    def _configure_services(self):
        self.stop_children()
        # Now we have to set up the .service files.  We use the Python
        # executable used to run the tests, executing the entry point as would
        # happen in a deployed script or virtualenv.
        for service, command_template, starter, stopper in SERVICES:
            command = command_template.format(python=sys.executable, self=self)
            service_file = service + '.service'
            path = data_path(service_file + '.in')
            with open(path, 'r', encoding='utf-8') as fp:
                template = fp.read()
            config = template.format(command=command)
            service_path = os.path.join(self.tmpdir, service_file)
            with open(service_path, 'w', encoding='utf-8') as fp:
                fp.write(config)
            self._stoppers.append(stopper)
        # If the dbus-daemon is running, reload its configuration files.
        if self.daemon_pid is not None:
            service = dbus.SystemBus().get_object('org.freedesktop.DBus', '/')
            iface = dbus.Interface(service, 'org.freedesktop.DBus')
            iface.ReloadConfig()
            time.sleep(HUP_SLEEP)

    def set_mode(self, *, cert_pem=None, service_mode=''):
        self.mode = service_mode
        certificate_path = data_path(cert_pem)
        self.certs = (
            '' if cert_pem is None
            else '-self-signed-certs ' + certificate_path)
        if self.patcher is not None:
            self.patcher.stop()
        if cert_pem is not None:
            from systemimage.download import _make_curl
            def self_signed_make_curl(url):
                c = _make_curl(url)
                c.setopt(pycurl.CAINFO, certificate_path)
                return c
            self.patcher = patch('systemimage.download._make_curl',
                                 self_signed_make_curl)
            self.patcher.start()
        self._configure_services()

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
        #print('DBUS_LAUNCH PID:', self.daemon_pid)
        self._stack.callback(self._kill, self.daemon_pid)
        #print("DBUS_SYSTEM_BUS_ADDRESS='{}'".format(dbus_address))
        # Set the service's address into the environment for rendezvous.
        self._stack.enter_context(reset_envar('DBUS_SYSTEM_BUS_ADDRESS'))
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = dbus_address
        # Try to start the DBus services.
        for service, command_template, starter, stopper in SERVICES:
            starter(self)

    def start(self):
        if self.daemon_pid is not None:
            # Already started.
            return
        try:
            self._configure_services()
            self._start()
        except:
            self._stack.close()
            raise

    def stop_children(self):
        # If the dbus-daemon is already running, kill all the children.
        if self.daemon_pid is not None:
            for stopper in self._stoppers:
                stopper(self)
        del self._stoppers[:]

    def _kill(self, pid):
        self.stop_children()
        process = psutil.Process(pid)
        process.terminate()
        process.wait(60)
        self.daemon_pid = None

    def stop(self):
        self._stack.close()
