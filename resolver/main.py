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

__all__ = [
    'main',
    ]


import logging
import argparse

from pkg_resources import resource_string as resource_bytes
from resolver.config import config
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
    level = {0: logging.ERROR,
             1: logging.INFO,
             2: logging.DEBUG}.get(args.verbose, logging.ERROR)
    logging.basicConfig(level=level,
                        datefmt='%b %d %H:%M:%S %Y',
                        format='%(asctime)s (%(process)d) %(message)s')
    log = logging.getLogger('resolver')
    log.setLevel(level)

    # Please be quiet gnupg.
    gnupg_log = logging.getLogger('gnupg')
    gnupg_log.propagate = False

    # Run the state machine to conclusion.
    log.info('running state machine')
    list(State())


if __name__ == '__main__':
    main()
