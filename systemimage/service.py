# Copyright (C) 2013-2016 Canonical Ltd.
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
from pkg_resources import resource_string as resource_bytes
from systemimage.config import config
from systemimage.dbus import Loop
from systemimage.helpers import makedirs
from systemimage.logging import initialize
from systemimage.main import DEFAULT_CONFIG_D


# --testing is only enabled when the systemimage.testing package is
# available.  This will be the case for the upstream source package, and when
# the systemimage-dev binary package is installed in Ubuntu.
try:
    from systemimage.testing.dbus import instrument, get_service
except ImportError: # pragma: no cover
    instrument = None
    get_service = None


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()


def main():
    # If enabled, start code coverage collection as early as possible.
    # Parse arguments.
    parser = argparse.ArgumentParser(
        prog='system-image-dbus',
        description='Ubuntu System Image Upgrader DBus service')
    parser.add_argument('--version',
                        action='version',
                        version='system-image-dbus {}'.format(__version__))
    parser.add_argument('-C', '--config',
                        default=DEFAULT_CONFIG_D, action='store',
                        metavar='DIRECTORY',
                        help="""Use the given configuration directory instead
                                of the default""")
    parser.add_argument('-v', '--verbose',
                        default=0, action='count',
                        help='Increase verbosity')
    # Hidden argument for special setup required by test environment.
    if instrument is not None: # pragma: no branch
        parser.add_argument('--testing',
                            default=None, action='store',
                            help=argparse.SUPPRESS)
        parser.add_argument('--self-signed-cert',
                            default=None, action='store',
                            help=argparse.SUPPRESS)

    args = parser.parse_args(sys.argv[1:])
    try:
        config.load(args.config)
    except TypeError as error:
        parser.error('\nConfiguration directory not found: {}'.format(error))
        assert 'parser.error() does not return' # pragma: no cover

    # Create the temporary directory if it doesn't exist.
    makedirs(config.system.tempdir)
    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')

    DBusGMainLoop(set_as_default=True)

    system_bus = dbus.SystemBus()
    # Ensure we're the only owner of this bus name.
    code = system_bus.request_name(
        'com.canonical.SystemImage',
        dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
    if code == dbus.bus.REQUEST_NAME_REPLY_EXISTS:
        # Another instance already owns this name.  Exit.
        log.error('Cannot get exclusive ownership of bus name.')
        return 2

    log.info('SystemImage dbus main loop starting [{}/{}]',
             config.channel, config.device)

    with ExitStack() as stack:
        loop = Loop()
        testing_mode = getattr(args, 'testing', None)
        if testing_mode:
            instrument(config, stack, args.self_signed_cert)
            config.dbus_service = get_service(
                testing_mode, system_bus, '/Service', loop)
        else:
            from systemimage.dbus import Service
            config.dbus_service = Service(system_bus, '/Service', loop)

        try:
            loop.run()
        except KeyboardInterrupt:                   # pragma: no cover
            log.info('SystemImage dbus main loop interrupted')
        except:                                     # pragma: no cover
            log.exception('D-Bus loop exception')
            raise
        else:
            log.info('SystemImage dbus main loop exited')


if __name__ == '__main__':                        # pragma: no cover
    sys.exit(main())
