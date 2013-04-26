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
    parser.add_argument('-a', '--android-version',
                        default=None,
                        help='Current Android version')
    parser.add_argument('-u', '--ubuntu-version',
                        default=None,
                        help='Current Ubuntu version')
    parser.add_argument('-f', '--force',
                        default=False, action='store_true',
                        help='Ignore any cached data, forcing a download')

    args = parser.parse_args()
    if args.config is not None:
        config.load(args.config)

    index = load_current_index(args.force)
    ubuntu_version, android_version = get_current_versions()
    if args.ubuntu_version == 'ignore':
        ubuntu_version = None
    elif args.ubuntu_version is not None:
        ubuntu_version = args.ubuntu_version
    if args.android_version == 'ignore':
        android_version = None
    elif args.android_version is not None:
        android_version = args.android_version
    ubuntu_candidates, android_candidates = get_candidates(
        index, ubuntu_version, android_version)
    policy = get_policy()
    ubuntu_path = policy.choose(ubuntu_candidates)
    android_path = policy.choose(android_candidates)
    # Convert the individual paths to download files, and download them.
    ubuntu_files = download_path(ubuntu_path)
    android_files = download_path(android_path)
    # Print the results as JSON.
    print(json.dumps(dict(ubuntu_files=ubuntu_files,
                          android_files=android_files)))


if __name__ == '__main__':
    main()
