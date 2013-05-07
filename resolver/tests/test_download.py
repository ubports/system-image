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
    'TestWinnerDownloads',
    ]


import os
import shutil
import tempfile
import unittest

from collections import defaultdict
from pkg_resources import resource_filename
from resolver.candidates import get_candidates, get_downloads
from resolver.download import get_files
from resolver.index import Index, load_current_index
from resolver.scores import WeightedScorer
from resolver.tests.helpers import make_http_server, make_temporary_cache, sign
from subprocess import check_call, PIPE
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urljoin


def safe_makedirs(path):
    try:
        os.makedirs(os.path.dirname(path))
    except FileExistsError:
        pass


class TestDownloads(unittest.TestCase):
    maxDiff = None

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

    def _abspathify(self, downloads):
        return [
            (urljoin(self._cache.config.service.base, url),
             os.path.join(self._cache.config.cache.directory, filename)
            ) for url, filename in downloads]

    def test_download_good_path(self):
        # Download a bunch of files that exist.  No callback.
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ]))
        cache_listing = os.listdir(self._cache.config.cache.directory)
        self.assertEqual(sorted(cache_listing),
                         ['channels.json', 'index.json', 'pubkey.asc'])

    def test_download_with_callback(self):
        results = []
        def callback(*args):
            results.append(args)
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ]), callback=callback)
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
            'http://localhost:8909/channels_01.json': 334,
            'http://localhost:8909/index_01.json': 99,
            'http://localhost:8909/phablet.pubkey.asc': 1679,
            })

    @patch('resolver.download.CHUNK_SIZE', 10)
    def test_download_chunks(self):
        # Similar to the above test, but makes sure that the chunking reads in
        # _get_one_file() work as expected.
        results = defaultdict(list)
        def callback(url, dst, size):
            results[url].append(size)
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ]), callback=callback)
        channels = sorted(results['http://localhost:8909/channels_01.json'])
        self.assertEqual(channels, [i * 10 for i in range(1, 34)] + [334])
        index = sorted(results['http://localhost:8909/index_01.json'])
        self.assertEqual(index, [i * 10 for i in range(1, 10)] + [99])
        pubkey = sorted(results['http://localhost:8909/phablet.pubkey.asc'])
        self.assertEqual(pubkey, [i * 10 for i in range(1, 168)] + [1679])

    def test_download_404(self):
        # Try to download a file which doesn't exist.  Since it's all or
        # nothing, the cache will be empty.
        self.assertRaises(URLError, get_files, self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ('missing.txt', 'missing.txt'),
            ]))
        self.assertEqual(
            os.listdir(self._cache.config.cache.directory),
            [])


class TestWinnerDownloads(unittest.TestCase):
    """Test full end-to-end downloads through index.json."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        # Start the HTTP server running.  Vend it out of a temporary directory
        # which we load up with the right files.
        cls._cleaners = []
        def append(*args):
            cls._cleaners.append(args)
        cls._serverdir = tempfile.mkdtemp()
        cls._cleaners.append((shutil.rmtree, cls._serverdir))
        def copy(filename, dst=None, sign=False):
            src = resource_filename('resolver.tests.data', filename)
            dst = os.path.join(cls._serverdir,
                               (filename if dst is None else dst))
            safe_makedirs(dst)
            shutil.copy(src, dst)
        # BAW 2013-05-03: Use pygpgme instead of shelling out for signing.
        keyring_dir = os.path.dirname(os.path.abspath(resource_filename(
            'resolver.tests.data', 'pubring_01.gpg')))
        copy('phablet.pubkey.asc')
        copy('channels_02.json', 'channels.json')
        copy('channels_02.json.asc', 'channels.json.asc')
        # index_10.json path B will win, with no bootme flags.
        copy('index_10.json', 'stable/nexus7/index.json')
        # Create every file in path B.  The contents of the files will be the
        # checksum value.  We need to create the signatures on the fly too.
        path = resource_filename('resolver.tests.data', 'index_10.json')
        with open(path, encoding='utf-8') as fp:
            index = Index.from_json(fp.read())
        for image in index.images:
            if 'B' not in image.description:
                continue
            for filerec in image.files:
                path = (filerec.path[1:]
                        if filerec.path.startswith('/')
                        else filrecpath)
                dst = os.path.join(cls._serverdir, path)
                safe_makedirs(dst)
                with open(dst, 'w', encoding='utf-8') as fp:
                    fp.write(filerec.checksum)
                sign(keyring_dir, dst)
                # BAW 2013-05-03: Sign the download files.
        cls._stop = make_http_server(cls._serverdir)
        cls._cleaners.insert(0, (cls._stop,))

    @classmethod
    def tearDownClass(cls):
        # Run all the cleanups.
        for func, *args in cls._cleaners:
            try:
                func(*args)
            except:
                # Boo hiss.
                pass

    def setUp(self):
        self._cache = make_temporary_cache(self.addCleanup)

    def test_download_winners(self):
        # This is essentially an integration test making sure that the
        # procedure in main() leaves you with the expected files.  In this
        # case all the B path files will have been downloaded.
        index = load_current_index(self._cache, force=True)
        candidates = get_candidates(index, 20130100)
        winner = WeightedScorer().choose(candidates)
        downloads = get_downloads(winner, self._cache)
        get_files(downloads)
        # The B path files contain their checksums.
        cache_dir = self._cache.config.cache.directory
        # Full B files.
        with open(os.path.join(cache_dir, '5.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '345')
        with open(os.path.join(cache_dir, '6.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '456')
        with open(os.path.join(cache_dir, '7.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '567')
        # Delta B.1 files.
        with open(os.path.join(cache_dir, '8.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '678')
        with open(os.path.join(cache_dir, '9.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '789')
        with open(os.path.join(cache_dir, 'a.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '89a')
        # Delta B.2 files.
        with open(os.path.join(cache_dir, 'b.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), '9ab')
        with open(os.path.join(cache_dir, 'd.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), 'fed')
        with open(os.path.join(cache_dir, 'c.txt'), encoding='utf-8') as fp:
            self.assertEqual(fp.read(), 'edc')
        # There should be no other files.
        self.assertEqual(set(os.listdir(cache_dir)), set([
            'timestamps.json', 'index.json',
            'channels.json', 'channels.json.asc',
            'phablet.pubkey.asc',
            '5.txt', '6.txt', '7.txt',
            '8.txt', '9.txt', 'a.txt',
            'b.txt', 'd.txt', 'c.txt',
            '5.txt.asc', '6.txt.asc', '7.txt.asc',
            '8.txt.asc', '9.txt.asc', 'a.txt.asc',
            'b.txt.asc', 'd.txt.asc', 'c.txt.asc',
            ]))
