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


import sys
import logging
import argparse

from pkg_resources import resource_string as resource_bytes
from systemimage.config import config
from systemimage.helpers import makedirs
from systemimage.logging import initialize
from systemimage.state import State


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()

DEFAULT_CONFIG_FILE = '/etc/system-image/client.ini'


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

    # Create the temporary directory if it doesn't exist.
    makedirs(config.system.tempdir)
    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')
    # We assume the cache_partition already exists, as does the /etc directory
    # (i.e. where the archive master key lives).

    build = (config.build_number
             if args.upgrade is None
             else int(args.upgrade))
    if args.build:
        print('build number:', build)
        return
    if args.channel:
        print('channel/device: {}/{}'.format(
            config.system.channel, config.device))
        return

    # Run the state machine to conclusion.  Suppress all exceptions, but note
    # that the state machine will log them.  If an exception occurs, exit with
    # a non-zero status.
    log.info('running state machine [{}/{}]',
             config.system.channel, config.device)
    try:
        list(State())
    except KeyboardInterrupt:
        return 0
    except:
        return 1
    else:
        return 0


if __name__ == '__main__':
    sys.exit(main())
