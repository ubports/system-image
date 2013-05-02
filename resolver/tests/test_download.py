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

"""Test asynchronous downloads."""

__all__ = [
    'TestDownloads',
    ]


import os
import unittest

from collections import defaultdict
from pkg_resources import resource_filename
from resolver.download import get_files
from resolver.tests.helpers import make_http_server, make_temporary_cache
from unittest.mock import patch
from urllib.error import URLError


class TestDownloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start the HTTP server running.  Vend it out of our test data
        # directory, which will at least have a phablet.pubkey.asc file.
        pubkey_file = resource_filename('resolver.tests.data',
                                        'phablet.pubkey.asc')
        directory = os.path.dirname(pubkey_file)
        cls._stop = make_http_server(directory)

    @classmethod
    def tearDownClass(cls):
        # Stop the HTTP server.
        cls._stop()

    def setUp(self):
        self._cache = make_temporary_cache(self.addCleanup)

    def test_download_good_path(self):
        # Download a bunch of files that exist.  No callback.
        with patch('resolver.download.config', self._cache.config):
            get_files([
                ('channels_01.json', 'channels.json'),
                ('index_01.json', 'index.json'),
                ('phablet.pubkey.asc', 'pubkey.asc'),
                ])
        cache_listing = os.listdir(self._cache.config.cache.directory)
        self.assertEqual(sorted(cache_listing),
                         ['channels.json', 'index.json', 'pubkey.asc'])

    def test_download_with_callback(self):
        results = []
        def callback(*args):
            results.append(args)
        with patch('resolver.download.config', self._cache.config):
            get_files([
                ('channels_01.json', 'channels.json'),
                ('index_01.json', 'index.json'),
                ('phablet.pubkey.asc', 'pubkey.asc'),
                ], callback=callback)
        cache_listing = os.listdir(self._cache.config.cache.directory)
        self.assertEqual(sorted(cache_listing),
                         ['channels.json', 'index.json', 'pubkey.asc'])
        # Because we're doing async i/o, even though it's to localhost,
        # there's no guarantee about the order of things in the results list,
        # nor of their count.  It's *likely* that there's exactly one entry
        # with the full byte count for each file.  But just in case, we'll
        # tally up all the bytes for all the urls and verify they total what
        # we expect.
        byte_totals = defaultdict(int)
        for url, dst, size in results:
            byte_totals[url] += size
        self.assertEqual(byte_totals, {
            'http://localhost:8909/channels_01.json': 185,
            'http://localhost:8909/index_01.json': 99,
            'http://localhost:8909/phablet.pubkey.asc': 3149,
            })

    @patch('resolver.download.CHUNK_SIZE', 10)
    def test_download_chunks(self):
        # Similar to the above test, but makes sure that the chunking reads in
        # _get_one_file() work as expected.
        results = defaultdict(list)
        def callback(url, dst, size):
            results[url].append(size)
        with patch('resolver.download.config', self._cache.config):
            get_files([
                ('channels_01.json', 'channels.json'),
                ('index_01.json', 'index.json'),
                ('phablet.pubkey.asc', 'pubkey.asc'),
                ], callback=callback)
        channels = sorted(results['http://localhost:8909/channels_01.json'])
        self.assertEqual(channels, [i * 10 for i in range(1, 19)] + [185])
        index = sorted(results['http://localhost:8909/index_01.json'])
        self.assertEqual(index, [i * 10 for i in range(1, 10)] + [99])
        pubkey = sorted(results['http://localhost:8909/phablet.pubkey.asc'])
        self.assertEqual(pubkey, [i * 10 for i in range(1, 315)] + [3149])

    def test_download_404(self):
        # Try to download a file which doesn't exist.  Since it's all or
        # nothing, the cache will be empty.
        with patch('resolver.download.config', self._cache.config):
            self.assertRaises(URLError, get_files, [
                ('channels_01.json', 'channels.json'),
                ('index_01.json', 'index.json'),
                ('phablet.pubkey.asc', 'pubkey.asc'),
                ('missing.txt', 'missing.txt'),
                ])
            self.assertEqual(
                os.listdir(self._cache.config.cache.directory),
                [])
