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


import json
import argparse

from pkg_resources import resource_string as resource_bytes
from resolver.config import config
from resolver.index import load_current_index


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
                        default=None,
                        help='Current build number')
    parser.add_argument('-f', '--force',
                        default=False, action='store_true',
                        help='Ignore any cached data, forcing a download')

    args = parser.parse_args()
    if args.config is not None:
        config.load(args.config)

    index = load_current_index(args.force)
    build = get_current_version() if args.build is None else args.build
    candidates = get_candidates(index, build)
    scorer = get_scorer()
    winner = scorer.choose(candidates)


if __name__ == '__main__':
    main()
