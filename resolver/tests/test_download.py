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
    ]


import os
import ssl
import json
import unittest

from collections import defaultdict
from contextlib import ExitStack
from resolver.config import config
from resolver.download import Downloader, get_files
from resolver.helpers import temporary_directory
from resolver.tests.helpers import (
    make_http_server, test_data_path, testable_configuration)
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urljoin


class TestDownloads(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._stack = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(test_data_path('__init__.py'))
            self._stack.push(make_http_server(directory, 8980))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

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
            urljoin(config.service.http_base, 'channels_01.json'): 456,
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
        self.assertEqual(channels, [i * 10 for i in range(1, 46)] + [456])
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
            tempdir = stack.enter_context(temporary_directory())
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
            tempdir = stack.enter_context(temporary_directory())
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
            tempdir = stack.enter_context(temporary_directory())
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
            tempdir = stack.enter_context(temporary_directory())
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
            tempdir = stack.enter_context(temporary_directory())
            stack.push(make_http_server(
                self._directory, 8943, 'nasty_cert.pem', 'nasty_key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True))
            self.assertRaises(
                FileNotFoundError,
                get_files, [('https://localhost:8943/channels_01.json',
                             os.path.join(tempdir, 'channels.json'))])
