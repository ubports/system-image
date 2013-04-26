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

"""Cache management."""

__all__ = [
    'Cache',
    ]


import os
import json

from datetime import datetime
from resolver.helpers import ExtendedEncoder, as_utcdatetime, atomic


def _object_hook(original):
    # For JSON decoding.  Turn timestamp values into datetimes.
    converted = {}
    for key, value in original.items():
        try:
            # Cache datetimes are local and naive.
            converted[key] = as_utcdatetime(value, utc=False)
        except ValueError:
            converted[key] = value
    return converted


class Cache:
    def __init__(self, config=None):
        # Load the current timestamps.
        if config is None:
            from resolver.config import config
        self._config = config
        # Ensure that the cache directory exists.  The parent must exist.
        try:
            os.mkdir(config.cache.directory, 0o700)
        except FileExistsError:
            pass
        self._path = os.path.join(config.cache.directory, 'timestamps.json')
        try:
            with open(self._path, encoding='utf-8') as fp:
                self._timestamps = json.load(fp, object_hook=_object_hook)
        except FileNotFoundError:
            self._timestamps = {}

    def update(self, key, when=None):
        """Write a new timestamp entry and save it to disk.

        Note that the timestamp written is generally the date at which the
        cache entry for the key expires, i.e. now + lifetime.  You can
        override this by providing a `when` argument.

        :param key: The timestamp key to update.
        :param when: Override the expiration date for this key.
        :type when: datetime
        """
        if when is None:
            # Cache datetimes are local and naive.
            when = datetime.now() + self._config.cache.lifetime
        self._timestamps[key] = when
        with atomic(self._path) as fp:
            json.dump(self._timestamps, fp, cls=ExtendedEncoder)

    def get_path(self, filename):
        """Return the full path to the file from the cache.

        If the file's lifetime has expired, or the file is not in the cache,
        return None.
        """
        lifetime = self._timestamps.get(filename)
        if lifetime is None:
            # The file is not in the cache.
            return None
        if lifetime < datetime.now():
            # The cache entry has expired.
            del self._timestamps[filename]
            with atomic(self._path) as fp:
                json.dump(self._timestamps, fp, cls=ExtendedEncoder)
            return None
        # It makes no sense to check if the file exists, since race conditions
        # prevent that from being useful.  The caller of .get_path() will just
        # have to catch the case when the named file for some reason does not
        # exist.
        return os.path.join(self._config.cache.directory, filename)
