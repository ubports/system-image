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
from contextlib import ExitStack
from functools import partial
from pkg_resources import resource_filename
from resolver.candidates import get_candidates, get_downloads
from resolver.config import config
from resolver.download import get_files
from resolver.index import load_current_index
from resolver.scores import WeightedScorer
from resolver.tests.helpers import (
    copy as copyfile, get_index, make_http_server, makedirs, sign,
    test_configuration)
from unittest.mock import patch
from urllib.parse import urljoin


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

    def _abspathify(self, downloads):
        return [
            (urljoin(config.service.base, url),
             os.path.join(config.system.tempdir, filename)
            ) for url, filename in downloads]

    @test_configuration
    def test_download_good_path(self):
        # Download a bunch of files that exist.  No callback.
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ]))
        self.assertEqual(
            set(os.listdir(config.system.tempdir)),
            set(['channels.json', 'index.json', 'pubkey.asc',
                 'phablet.pubkey.asc']))

    @test_configuration
    def test_download_with_callback(self):
        results = []
        def callback(*args):
            results.append(args)
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ]), callback=callback)
        self.assertEqual(
            set(os.listdir(config.system.tempdir)),
            set(['channels.json', 'index.json', 'pubkey.asc',
                 'phablet.pubkey.asc']))
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
            urljoin(config.service.base, 'channels_01.json'): 334,
            urljoin(config.service.base, 'index_01.json'): 99,
            urljoin(config.service.base, 'phablet.pubkey.asc'): 1679,
            })

    @test_configuration
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
        channels = sorted(
            results[urljoin(config.service.base, 'channels_01.json')])
        self.assertEqual(channels, [i * 10 for i in range(1, 34)] + [334])
        index = sorted(results[urljoin(config.service.base, 'index_01.json')])
        self.assertEqual(index, [i * 10 for i in range(1, 10)] + [99])
        pubkey = sorted(
            results[urljoin(config.service.base, 'phablet.pubkey.asc')])
        self.assertEqual(pubkey, [i * 10 for i in range(1, 168)] + [1679])

    @test_configuration
    def test_download_404(self):
        # Try to download a file which doesn't exist.  Since it's all or
        # nothing, the temp directory will be empty.
        self.assertRaises(FileNotFoundError, get_files, self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('phablet.pubkey.asc', 'pubkey.asc'),
            ('missing.txt', 'missing.txt'),
            ]))
        self.assertEqual(os.listdir(config.system.tempdir), [])


class TestWinnerDownloads(unittest.TestCase):
    """Test full end-to-end downloads through index.json."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        # Start the HTTP server running.  Vend it out of a temporary directory
        # which we load up with the right files.
        cls._cleaners = ExitStack()
        try:
            cls._serverdir = tempfile.mkdtemp()
            cls._cleaners.callback(shutil.rmtree, cls._serverdir)
            keyring_dir = os.path.dirname(os.path.abspath(resource_filename(
                'resolver.tests.data', 'pubring_01.gpg')))
            copy = partial(copyfile, todir=cls._serverdir)
            copy('phablet.pubkey.asc')
            copy('channels_02.json', dst='channels.json')
            copy('channels_02.json.asc', dst='channels.json.asc')
            # index_10.json path B will win, with no bootme flags.
            copy('index_10.json', dst='stable/nexus7/index.json')
            # Create every file in path B.  The file contents will be the
            # checksum value.  We need to create the signatures on the fly.
            index = get_index('index_10.json')
            for image in index.images:
                if 'B' not in image.description:
                    continue
                for filerec in image.files:
                    path = (filerec.path[1:]
                            if filerec.path.startswith('/')
                            else filerec.path)
                    dst = os.path.join(cls._serverdir, path)
                    makedirs(os.path.dirname(dst))
                    with open(dst, 'w', encoding='utf-8') as fp:
                        fp.write(filerec.checksum)
                    sign(keyring_dir, dst)
            cls._stop = make_http_server(cls._serverdir)
            cls._cleaners.callback(cls._stop)
        except:
            cls._cleaners.pop_all().close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._cleaners.close()

    @test_configuration
    def test_download_winners(self):
        # This is essentially an integration test making sure that the
        # procedure in main() leaves you with the expected files.  In this
        # case all the B path files will have been downloaded.
        index = load_current_index()
        candidates = get_candidates(index, 20130100)
        winner = WeightedScorer().choose(candidates)
        downloads = get_downloads(winner)
        get_files(downloads)
        # The B path files contain their checksums.
        def assert_file_contains(filename, contents):
            path = os.path.join(config.system.tempdir, filename)
            with open(path, encoding='utf-8') as fp:
                self.assertEqual(fp.read(), contents)
        assert_file_contains('5.txt', '345')
        assert_file_contains('6.txt', '456')
        assert_file_contains('7.txt', '567')
        # Delta B.1 files.
        assert_file_contains('8.txt', '678')
        assert_file_contains('9.txt', '789')
        assert_file_contains('a.txt', '89a')
        # Delta B.2 files.
        assert_file_contains('b.txt', '9ab')
        assert_file_contains('d.txt', 'fed')
        assert_file_contains('c.txt', 'edc')
        # There should be no other files.
        self.assertEqual(set(os.listdir(config.system.tempdir)), set([
            'index.json',
            'channels.json', 'channels.json.asc',
            'phablet.pubkey.asc',
            '5.txt', '6.txt', '7.txt',
            '8.txt', '9.txt', 'a.txt',
            'b.txt', 'd.txt', 'c.txt',
            '5.txt.asc', '6.txt.asc', '7.txt.asc',
            '8.txt.asc', '9.txt.asc', 'a.txt.asc',
            'b.txt.asc', 'd.txt.asc', 'c.txt.asc',
            ]))

    @test_configuration
    def test_no_download_winners_with_missing_signature(self):
        # If one of the download files is missing a signature, none of the
        # files get downloaded and get_files() fails.
        os.remove(os.path.join(self._serverdir, '6/7/8.txt.asc'))
        index = load_current_index()
        candidates = get_candidates(index, 20130100)
        winner = WeightedScorer().choose(candidates)
        downloads = get_downloads(winner)
        self.assertRaises(FileNotFoundError, get_files, downloads)
        self.assertEqual(set(os.listdir(config.system.tempdir)), set([
            'channels.json',
            'index.json',
            'channels.json.asc',
            'phablet.pubkey.asc',
            ]))

    @test_configuration
    def test_no_download_winners_with_bad_signature(self):
        # If one of the download files has a bad a signature, none of the
        # files get downloaded and get_files() fails.
        target = os.path.join(self._serverdir, '6/7/8.txt')
        os.remove(target + '.asc')
        # Sign the file with the attacker's key.
        sign(os.path.dirname(os.path.abspath(resource_filename(
            'resolver.tests.data', 'pubring_02.gpg'))),
             target,
             ('pubring_02.gpg', 'secring_02.gpg'))
        index = load_current_index()
        candidates = get_candidates(index, 20130100)
        winner = WeightedScorer().choose(candidates)
        downloads = get_downloads(winner)
        self.assertRaises(FileNotFoundError, get_files, downloads)
        self.assertEqual(set(os.listdir(config.system.tempdir)), set([
            'channels.json',
            'index.json',
            'channels.json.asc',
            'phablet.pubkey.asc',
            ]))
