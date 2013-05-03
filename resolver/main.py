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
from resolver.candidates import get_candidates, get_downloads
from resolver.config import config
from resolver.download import get_files
from resolver.index import load_current_index
from resolver.scores import WeightedScorer


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

    build = (config.get_build_number()
             if args.build is None else int(args.build))
    index = load_current_index(force=args.force)
    candidates = get_candidates(index, build)
    winner = WeightedScorer().choose(candidates)
    downloads = get_downloads(winner)
    get_files(downloads)
    for url, path in downloads:
        print(path)


if __name__ == '__main__':
    main()
