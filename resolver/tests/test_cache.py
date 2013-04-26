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

"""Test the cache."""

__all__ = [
    'TestCache',
    ]


import os
import shutil
import tempfile
import unittest

from datetime import datetime, timedelta
from pkg_resources import resource_filename
from resolver.cache import Cache
from resolver.config import Configuration
from resolver.helpers import atomic
from unittest.mock import patch


class TestCache(unittest.TestCase):
    def setUp(self):
        self._config = Configuration()
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        ini_file = os.path.join(tempdir, 'config.ini')
        with atomic(ini_file) as fp:
            print("""\
[service]
base: https://phablet.example.com
[cache]
directory: {}
lifetime: 1d
[upgrade]
channel: stable
device: nexus7
""".format(tempdir), file=fp)
        self._config.load(ini_file)
        self._cache = Cache(self._config)

    def test_cache_miss(self):
        # Getting a file that does not exist in the cache returns None.
        self.assertIsNone(self._cache.get_path('missing'))

    def test_cache_hit(self):
        # The file doesn't actually have to exist for the cache to hit, it
        # just needs to be in the timestamps file with a non-expired
        # timestamp.  Because the lifetime above is 1 day, updating the cache
        # will provide this.
        self._cache.update('somefile')
        filename = self._cache.get_path('somefile')
        self.assertEqual(os.path.basename(filename), 'somefile')

    def test_cache_expired(self):
        # Put an entry in the cache, then mock the current time to two days in
        # the future.  The cache will then miss.
        self._cache.update('somefile')
        # First, it hits.
        self.assertIsNotNone(self._cache.get_path('somefile'))
        # Fast forward the clock.
        future = datetime.now() + timedelta(days=2)
        with patch('resolver.cache._now', return_value=future):
            self.assertIsNone(self._cache.get_path('somefile'))
        # Because the cache entry expired, it got evicted.  Thus even though
        # we've unmocked the current time, the cache misses.
        self.assertIsNone(self._cache.get_path('somefile'))
