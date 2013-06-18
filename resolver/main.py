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
from resolver.config import config
from resolver.logging import initialize
from resolver.state import State


__version__ = resource_bytes('resolver', 'version.txt').decode('utf-8').strip()


def main():
    global config
    parser = argparse.ArgumentParser(
        prog='resolver',
        description='Resolver for Ubuntu phablet updates')
    parser.add_argument('--version',
                        action='version',
                        version='resolver {}'.format(__version__))
    parser.add_argument('-C', '--config', default=None)
    parser.add_argument('-b', '--build',
                        default=False, action='store_true',
                        help='Show the current build number and exit')
    parser.add_argument('-u', '--upgrade',
                        default=None,
                        help='Upgrade from this build number')
    parser.add_argument('-v', '--verbose',
                        default=0, action='count',
                        help='Increase verbosity')

    args = parser.parse_args()
    if args.config is not None:
        config.load(args.config)

    build = (config.build_number
             if args.upgrade is None
             else int(args.upgrade))
    if args.build:
        print('build number:', build)
        return

    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('resolver')

    # Run the state machine to conclusion.  Suppress all exceptions, but note
    # that the state machine will log them.  If an exception occurs, exit with
    # a non-zero status.
    log.info('running state machine')
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
