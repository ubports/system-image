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


import argparse

from pkg_resources import resource_string as resource_bytes
from resolver.config import Configuration


__version__ = resource_bytes('resolver', 'version.txt').decode('utf-8').strip()
config = None


def main():
    global config
    parser = argparse.ArgumentParser(
        prog='resolver',
        description='Resolver for Ubuntu phablet updates')
    parser.add_argument('--version',
                        action='version',
                        version='resolver {}'.format(__version__))
    parser.add_argument('-C', '--config', default=None)
    parser.add_argument('-a', '--android-version',
                        default=None,
                        help='Current Android version')
    parser.add_argument('-u', '--ubuntu-version',
                        default=None,
                        help='Current Ubuntu version')

    args = parser.parse_args()
    config = Configuration()
    if args.config is not None:
        config.load(args.config)


if __name__ == '__main__':
    main()
