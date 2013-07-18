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

"""DBus service main entry point."""

__all__ = [
    'main',
    ]


import sys
import dbus
import logging
import argparse

from contextlib import ExitStack
from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import BusName, Object, method
from gi.repository import GLib
from pkg_resources import resource_string as resource_bytes
from systemimage.config import config
from systemimage.api import Mediator
from systemimage.logging import initialize
from systemimage.main import DEFAULT_CONFIG_FILE


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)
        self._api = Mediator()

    @property
    def api(self):
        return self._api

    @method('com.canonical.SystemImage', out_signature='i')
    def BuildNumber(self):
        return self.api.get_build_number()

    @method('com.canonical.SystemImage', out_signature='b')
    def IsUpdateAvailable(self):
        return bool(self.api.check_for_update())


class TestableService(Service):
    """For testing purposes only."""

    @property
    def api(self):
        # Reset the api object so that the tests have isolated state.
        current_api = self._api
        self._api = Mediator()
        return current_api


def main():
    global config
    parser = argparse.ArgumentParser(
        prog='system-image-dbus',
        description='Ubuntu System Image Upgrader DBus service')
    parser.add_argument('--version',
                        action='version',
                        version='system-image-cli {}'.format(__version__))
    parser.add_argument('-C', '--config',
                        default=DEFAULT_CONFIG_FILE, action='store',
                        metavar='FILE',
                        help="""Use the given configuration file instead of
                                the default""")
    parser.add_argument('-v', '--verbose',
                        default=0, action='count',
                        help='Increase verbosity')
    # Hidden argument for special setup required by test environment.
    parser.add_argument('--testing',
                        default=False, action='store_true',
                        help=argparse.SUPPRESS)

    args = parser.parse_args(sys.argv[1:])
    try:
        config.load(args.config)
    except FileNotFoundError as error:
        parser.error('\nConfiguration file not found: {}'.format(error))
        assert 'parser.error() does not return'

    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')

    log.info('starting the SystemImage dbus main loop')
    DBusGMainLoop(set_as_default=True)
    GLib.timeout_add_seconds(config.dbus.lifetime.total_seconds(), sys.exit, 0)

    session_bus = dbus.SessionBus()
    bus_name = BusName('com.canonical.SystemImage', session_bus)

    with ExitStack() as stack:
        if args.testing:
            from functools import partial
            from systemimage.testing.helpers import test_data_path
            from unittest.mock import patch
            from urllib.request import urlopen
            stack.enter_context(
                patch('systemimage.download.urlopen',
                      partial(urlopen, cafile=test_data_path('cert.pem'))))
            ServiceClass = TestableService
        else:
            ServiceClass = Service
        # Create the dbus service and enter the main loop.
        service = ServiceClass(session_bus, '/Service')
        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            log.info('SystemImage dbus main loop interrupted')


if __name__ == '__main__':
    sys.exit(main())
