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
    'TestHTTPSDownloads',
    'TestWinnerDownloads',
    ]


import os
import ssl
import json
import shutil
import tempfile
import unittest

from collections import defaultdict
from contextlib import ExitStack
from functools import partial
from resolver.candidates import get_candidates, get_downloads
from resolver.config import config
from resolver.download import Downloader, get_files
from resolver.index import load_current_index
from resolver.scores import WeightedScorer
from resolver.tests.helpers import (
    copy as copyfile, get_index, make_http_server, makedirs, sign,
    test_data_path, testable_configuration)
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urljoin


class TestDownloads(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(test_data_path('__init__.py'))
            cls._stack.push(make_http_server(directory, 8980))
        except:
            cls._stack.close()

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def _abspathify(self, downloads):
        return [
            (urljoin(config.service.http_base, url),
             os.path.join(config.system.tempdir, filename)
            ) for url, filename in downloads]

    @testable_configuration
    def test_download_good_path(self):
        # Download a bunch of files that exist.  No callback.
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ]))
        self.assertEqual(
            set(os.listdir(config.system.tempdir)),
            set(['channels.json', 'index.json']))

    @testable_configuration
    def test_download_with_callback(self):
        results = []
        def callback(*args):
            results.append(args)
        get_files(self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ]), callback=callback)
        self.assertEqual(
            set(os.listdir(config.system.tempdir)),
            set(['channels.json', 'index.json']))
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
            urljoin(config.service.http_base, 'channels_01.json'): 334,
            urljoin(config.service.http_base, 'index_01.json'): 99,
            })

    @testable_configuration
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
            ]), callback=callback)
        channels = sorted(
            results[urljoin(config.service.http_base, 'channels_01.json')])
        self.assertEqual(channels, [i * 10 for i in range(1, 34)] + [334])
        index = sorted(
            results[urljoin(config.service.http_base, 'index_01.json')])
        self.assertEqual(index, [i * 10 for i in range(1, 10)] + [99])

    @testable_configuration
    def test_download_404(self):
        # Try to download a file which doesn't exist.  Since it's all or
        # nothing, the temp directory will be empty.
        self.assertRaises(FileNotFoundError, get_files, self._abspathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ('missing.txt', 'missing.txt'),
            ]))
        self.assertEqual(os.listdir(config.system.tempdir), [])


class TestWinnerDownloads(unittest.TestCase):
    """Test full end-to-end downloads through index.json."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        # Start both an HTTP and an HTTPS server running.  The former is for
        # the zip files and the latter is for everything else.  Vend them out
        # of a temporary directory which we load up with the right files.
        cls._stack = ExitStack()
        try:
            cls._serverdir = tempfile.mkdtemp()
            cls._stack.callback(shutil.rmtree, cls._serverdir)
            keyring_dir = os.path.dirname(test_data_path('__init__.py'))
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
            cls._stack.push(
                make_http_server(cls._serverdir, 8943, 'cert.pem', 'key.pem',
                    # The following isn't strictly necessary, since its
                    # the default.
                    selfsign=True))
            cls._stack.push(make_http_server(cls._serverdir, 8980))
        except:
            cls._stack.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    @testable_configuration
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

    @testable_configuration
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

    @testable_configuration
    def test_no_download_winners_with_bad_signature(self):
        # If one of the download files has a bad a signature, none of the
        # files get downloaded and get_files() fails.
        target = os.path.join(self._serverdir, '6/7/8.txt')
        os.remove(target + '.asc')
        # Sign the file with the attacker's key.
        sign(os.path.dirname(test_data_path('__init__.py')),
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
            ]))


class TestHTTPSDownloads(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._directory = os.path.dirname(test_data_path('__init__.py'))

    def test_https_good_path(self):
        # The HTTPS server has a valid certificate (mocked so that its CA is
        # in the system's trusted path), so downloading over https succeeds
        # (i.e. the good path).
        with ExitStack() as stack:
            stack.push(make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True))
            response = stack.enter_context(Downloader(
                'https://localhost:8943/channels_01.json'))
            data = json.loads(response.read().decode('utf-8'))
            self.assertIn('daily', data)
            self.assertIn('stable', data)

    def test_get_files_https_good_path(self):
        # The HTTPS server has a valid certificate (mocked so that its CA is
        # in the system's trusted path), so downloading over https succeeds
        # (i.e. the good path).
        with ExitStack() as stack:
            tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, tempdir)
            stack.push(make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True))
            channels_path = os.path.join(tempdir, 'channels.json')
            get_files([('https://localhost:8943/channels_01.json',
                        channels_path)])
            with open(channels_path, encoding='utf-8') as fp:
                data = json.loads(fp.read())
            self.assertIn('daily', data)
            self.assertIn('stable', data)

    def test_https_cert_not_in_capath(self):
        # The self-signed certificate fails because it's not in the system's
        # CApath (no known-good CA).
        with make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem',
                selfsign=False):
            dl = Downloader('https://localhost:8943/channels_01.json')
            self.assertRaises(URLError, dl.__enter__)

    def test_get_files_https_cert_not_in_capath(self):
        # The self-signed certificate fails because it's not in the system's
        # CApath (no known-good CA).
        with ExitStack() as stack:
            tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, tempdir)
            stack.push(make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem',
                selfsign=False))
            self.assertRaises(
                FileNotFoundError,
                get_files, [('https://localhost:8943/channels_01.json',
                             os.path.join(tempdir, 'channels.json'))])

    def test_http_masquerades_as_https(self):
        # There's an HTTP server pretending to be an HTTPS server.  This
        # should fail to download over https URLs.
        with make_http_server(self._directory, 8943):
            # By not providing an SSL context wrapped socket, this isn't
            # really an https server.
            dl = Downloader('https://localhost:8943/channels_01.json')
            self.assertRaises(URLError, dl.__enter__)

    def test_get_files_http_masquerades_as_https(self):
        # There's an HTTP server pretending to be an HTTPS server.  This
        # should fail to download over https URLs.
        with ExitStack() as stack:
            tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, tempdir)
            # By not providing an SSL context wrapped socket, this isn't
            # really an https server.
            stack.push(make_http_server(self._directory, 8943))
            self.assertRaises(
                FileNotFoundError,
                get_files, [('https://localhost:8943/channels_01.json',
                            os.path.join(tempdir, 'channels.json'))])

    def test_expired(self):
        # The HTTPS server has an expired certificate (mocked so that its CA
        # is in the system's trusted path).
        with make_http_server(
                self._directory, 8943, 'expired_cert.pem', 'expired_key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True):
            dl = Downloader('https://localhost:8943/channels_01.json')
            self.assertRaises(URLError, dl.__enter__)

    def test_get_files_expired(self):
        # The HTTPS server has an expired certificate (mocked so that its CA
        # is in the system's trusted path).
        with ExitStack() as stack:
            tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, tempdir)
            stack.push(make_http_server(
                self._directory, 8943, 'expired_cert.pem', 'expired_key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True))
            self.assertRaises(
                FileNotFoundError,
                get_files, [('https://localhost:8943/channels_01.json',
                             os.path.join(tempdir, 'channels.json'))])

    def test_bad_host(self):
        # The HTTPS server has a certificate with a non-matching hostname
        # (mocked so that its CA is in the system's trusted path).
        with make_http_server(
                self._directory, 8943, 'nasty_cert.pem', 'nasty_key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True):
            dl = Downloader('https://localhost:8943/channels_01.json')
            self.assertRaises(ssl.CertificateError, dl.__enter__)

    def test_get_files_bad_host(self):
        # The HTTPS server has a certificate with a non-matching hostname
        # (mocked so that its CA is in the system's trusted path).
        with ExitStack() as stack:
            tempdir = tempfile.mkdtemp()
            stack.callback(shutil.rmtree, tempdir)
            stack.push(make_http_server(
                self._directory, 8943, 'nasty_cert.pem', 'nasty_key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True))
            self.assertRaises(
                FileNotFoundError,
                get_files, [('https://localhost:8943/channels_01.json',
                             os.path.join(tempdir, 'channels.json'))])
