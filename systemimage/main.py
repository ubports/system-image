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

"""Main script entry point."""


__all__ = [
    'main',
    ]


import os
import sys
import logging
import argparse

from pkg_resources import resource_string as resource_bytes
from systemimage.bindings import DBusClient
from systemimage.candidates import delta_filter, full_filter
from systemimage.config import config
from systemimage.helpers import makedirs
from systemimage.logging import initialize
from systemimage.state import State


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()

DEFAULT_CONFIG_FILE = '/etc/system-image/client.ini'
COLON = ':'


def main():
    global config
    parser = argparse.ArgumentParser(
        prog='system-image-cli',
        description='Ubuntu System Image Upgrader')
    parser.add_argument('--version',
                        action='version',
                        version='system-image-cli {}'.format(__version__))
    parser.add_argument('-C', '--config',
                        default=DEFAULT_CONFIG_FILE, action='store',
                        metavar='FILE',
                        help="""Use the given configuration file instead of
                                the default""")
    parser.add_argument('-b', '--build',
                        default=False, action='store_true',
                        help='Show the current build number and exit')
    parser.add_argument('-c', '--channel',
                        default=False, action='store_true',
                        help='Show the current channel/device name and exit')
    parser.add_argument('--dbus',
                        default=False, action='store_true',
                        help='Run in D-Bus client mode.')
    parser.add_argument('-f', '--filter',
                        default=None, action='store',
                        help="""Filter the candidate paths to contain only
                                full updates or only delta updates.  The
                                argument to this option must be either `full`
                                or `delta`""")
    parser.add_argument('-n', '--dry-run',
                        default=False, action='store_true',
                        help="""Calculate and print the upgrade path, but do
                                not download or apply it""")
    parser.add_argument('-u', '--upgrade',
                        default=None, metavar='NUMBER',
                        help="""Upgrade from this build number instead of the
                                system's current build number""")
    parser.add_argument('-v', '--verbose',
                        default=0, action='count',
                        help='Increase verbosity')

    args = parser.parse_args(sys.argv[1:])
    try:
        config.load(args.config)
    except FileNotFoundError as error:
        parser.error('\nConfiguration file not found: {}'.format(error))
        assert 'parser.error() does not return'
    # Load the optional channel.ini file, which must live next to the
    # configuration file.  It's okay if this file does not exist.
    channel_ini = os.path.join(os.path.dirname(args.config), 'channel.ini')
    try:
        config.load(channel_ini, override=True)
    except FileNotFoundError:
        pass

    # Sanity check -f/--filter.
    if args.filter is None:
        candidate_filter = None
    elif args.filter == 'full':
        candidate_filter = full_filter
    elif args.filter == 'delta':
        candidate_filter = delta_filter
    else:
        parser.error('Bad filter type: {}'.format(args.filter))
        assert 'parser.error() does not return'

    # Create the temporary directory if it doesn't exist.
    makedirs(config.system.tempdir)
    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')
    # We assume the cache_partition already exists, as does the /etc directory
    # (i.e. where the archive master key lives).

    if args.build:
        print('build number:', config.build_number)
        return
    if args.channel:
        print('channel/device: {}/{}'.format(
            config.service.channel, config.device))
        return

    # We can either run the API directly or through DBus.
    if args.dbus:
        client = DBusClient()
        client.check_for_update()
        if not client.is_available:
            log.info('No update is available')
            return 0
        if not client.downloaded:
            log.info('No update was downloaded')
            return 1
        if client.failed:
            log.info('Update failed')
            return 2
        client.reboot()
        # We probably won't get here..
        return 0

    state = State(candidate_filter=candidate_filter)
    if args.dry_run:
        state.run_thru('persist')
        if len(state.winner) > 0:
            winning_path = [str(image.version) for image in state.winner]
            print('Upgrade path is {}'.format(COLON.join(winning_path)))
        else:
            print('Already up-to-date')
        return
    else:
        # Run the state machine to conclusion.  Suppress all exceptions, but
        # note that the state machine will log them.  If an exception occurs,
        # exit with a non-zero status.
        log.info('running state machine [{}/{}]',
                 config.service.channel, config.device)
        try:
            list(state)
        except KeyboardInterrupt:
            return 0
        except:
            return 1
        else:
            return 0


if __name__ == '__main__':
    sys.exit(main())
