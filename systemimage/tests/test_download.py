# Copyright (C) 2013-2014 Canonical Ltd.
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
    'TestDownloadBigFiles',
    'TestDownloads',
    'TestHTTPSDownloads',
    'TestHTTPSDownloadsExpired',
    'TestHTTPSDownloadsNasty',
    'TestHTTPSDownloadsNoSelfSigned',
    'TestRecord',
    ]


import os
import random
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta
from gi.repository import GLib
from systemimage.config import config
from systemimage.download import (
    Canceled, DBusDownloadManager, DuplicateDestinationError, Record)
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import (
    configuration, data_path, make_http_server)
from systemimage.testing.nose import SystemImagePlugin
from unittest.mock import patch
from urllib.parse import urljoin

MiB = 1024 * 1024


def _http_pathify(downloads):
    return [
        (urljoin(config.service.http_base, url),
         os.path.join(config.tempdir, filename)
        ) for url, filename in downloads]


def _https_pathify(downloads):
    return [
        (urljoin(config.service.https_base, url),
         os.path.join(config.tempdir, filename)
        ) for url, filename in downloads]


class TestDownloads(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode()

    def setUp(self):
        self._stack = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(data_path('__init__.py'))
            self._stack.push(make_http_server(directory, 8980))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_good_path(self):
        # Download a bunch of files that exist.  No callback.
        DBusDownloadManager().get_files(_http_pathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ]))
        self.assertEqual(
            set(os.listdir(config.tempdir)),
            set(['channels.json', 'index.json']))

    @configuration
    def test_empty_download(self):
        # Empty download set completes successfully.  LP: #1245597.
        DBusDownloadManager().get_files([])
        # No TimeoutError is raised.

    @configuration
    def test_user_agent(self):
        # The User-Agent request header contains the build number.
        version = random.randint(0, 99)
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(version, file=fp)
        # Download a magic path which the server will interpret to return us
        # the User-Agent header value.
        DBusDownloadManager().get_files(_http_pathify([
            ('user-agent.txt', 'user-agent.txt'),
            ]))
        path = os.path.join(config.tempdir, 'user-agent.txt')
        with open(path, 'r', encoding='utf-8') as fp:
            user_agent = fp.read()
        self.assertEqual(
            user_agent,
            'Ubuntu System Image Upgrade Client; Build {}'.format(version))

    @configuration
    def test_download_with_callback(self):
        # Downloading calls the callback with some arguments.
        received_bytes = 0
        total_bytes = 0
        def callback(received, total):
            nonlocal received_bytes, total_bytes
            received_bytes = received
            total_bytes = total
        downloader = DBusDownloadManager(callback)
        downloader.get_files(_http_pathify([
            ('channels_01.json', 'channels.json'),
            ('index_01.json', 'index.json'),
            ]))
        self.assertEqual(
            set(os.listdir(config.tempdir)),
            set(['channels.json', 'index.json']))
        self.assertEqual(received_bytes, 669)
        self.assertEqual(total_bytes, 669)

    @configuration
    def test_duplicate_destinations(self):
        # A download that duplicates the destination location is not allowed.
        downloader = DBusDownloadManager()
        downloads = _http_pathify([
            ('channels_01.json', 'channels.json'),
            ('channels_02.json', 'channels.json'),
            ])
        with self.assertRaises(DuplicateDestinationError) as cm:
            downloader.get_files(downloads)
        self.assertEqual(len(cm.exception.duplicates), 1)
        dst, urls = cm.exception.duplicates[0]
        self.assertEqual(os.path.basename(dst), 'channels.json')
        self.assertEqual(urls, ['http://localhost:8980/channels_01.json',
                                'http://localhost:8980/channels_02.json'])


class TestHTTPSDownloads(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._directory = os.path.dirname(data_path('__init__.py'))

    @configuration
    def test_good_path(self):
        # The HTTPS server has a valid self-signed certificate, so downloading
        # over https succeeds.
        with ExitStack() as stack:
            stack.push(make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem'))
            DBusDownloadManager().get_files(_https_pathify([
                ('channels_01.json', 'channels.json'),
                ]))
            self.assertEqual(
                set(os.listdir(config.tempdir)),
                set(['channels.json']))


class TestHTTPSDownloadsNoSelfSigned(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode()

    def setUp(self):
        self._directory = os.path.dirname(data_path('__init__.py'))

    @configuration
    def test_https_cert_not_in_capath(self):
        # The self-signed certificate fails because it's not in the system's
        # CApath (no known-good CA).
        with make_http_server(self._directory, 8943, 'cert.pem', 'key.pem'):
            self.assertRaises(
                FileNotFoundError,
                DBusDownloadManager().get_files,
                _https_pathify([
                    ('channels_01.json', 'channels.json'),
                    ]))

    @configuration
    def test_http_masquerades_as_https(self):
        # There's an HTTP server pretending to be an HTTPS server.  This
        # should fail to download over https URLs.
        with ExitStack() as stack:
            # By not providing an SSL context wrapped socket, this isn't
            # really an https server.
            stack.push(make_http_server(self._directory, 8943))
            self.assertRaises(
                FileNotFoundError,
                DBusDownloadManager().get_files,
                _https_pathify([
                    ('channels_01.json', 'channels.json'),
                    ]))


class TestHTTPSDownloadsExpired(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='expired_cert.pem')

    def setUp(self):
        self._directory = os.path.dirname(data_path('__init__.py'))

    @configuration
    def test_expired(self):
        # The HTTPS server has an expired certificate (mocked so that its CA
        # is in the system's trusted path).
        with ExitStack() as stack:
            stack.push(make_http_server(
                self._directory, 8943, 'expired_cert.pem', 'expired_key.pem'))
            self.assertRaises(
                FileNotFoundError,
                DBusDownloadManager().get_files,
                _https_pathify([
                    ('channels_01.json', 'channels.json'),
                    ]))


class TestHTTPSDownloadsNasty(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='nasty_cert.pem')

    def setUp(self):
        self._directory = os.path.dirname(data_path('__init__.py'))

    @configuration
    def test_bad_host(self):
        # The HTTPS server has a certificate with a non-matching hostname
        # (mocked so that its CA is in the system's trusted path).
        with ExitStack() as stack:
            stack.push(make_http_server(
                self._directory, 8943, 'nasty_cert.pem', 'nasty_key.pem'))
            self.assertRaises(
                FileNotFoundError,
                DBusDownloadManager().get_files,
                _https_pathify([
                    ('channels_01.json', 'channels.json'),
                    ]))


class TestDownloadBigFiles(unittest.TestCase):
    @configuration
    def test_cancel(self):
        # Try to cancel the download of a big file.
        self.assertEqual(os.listdir(config.tempdir), [])
        with ExitStack() as stack:
            serverdir = stack.enter_context(temporary_directory())
            stack.push(make_http_server(serverdir, 8980))
            # Create a couple of big files to download.
            with open(os.path.join(serverdir, 'bigfile_1.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            with open(os.path.join(serverdir, 'bigfile_2.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            # The download service doesn't provide reliable cancel
            # granularity, so instead, we mock the 'started' signal to
            # immediately cancel the download.
            downloader = DBusDownloadManager()
            def cancel_on_start(self, signal, path, started):
                if started:
                    downloader.cancel()
            stack.enter_context(patch(
                'systemimage.download.DownloadReactor._do_started',
                cancel_on_start))
            self.assertRaises(
                Canceled, downloader.get_files, _http_pathify([
                    ('bigfile_1.dat', 'bigfile_1.dat'),
                    ('bigfile_2.dat', 'bigfile_2.dat'),
                    ]))
            self.assertEqual(os.listdir(config.tempdir), [])

    @configuration
    def test_download_404(self):
        # Start a group download of some big files.   One of the files won't
        # exist, so the entire group download should fail, and none of the
        # files should exist in the destination.
        self.assertEqual(os.listdir(config.tempdir), [])
        with ExitStack() as stack:
            serverdir = stack.enter_context(temporary_directory())
            stack.push(make_http_server(serverdir, 8980))
            # Create a couple of big files to download.
            with open(os.path.join(serverdir, 'bigfile_1.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            with open(os.path.join(serverdir, 'bigfile_2.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            with open(os.path.join(serverdir, 'bigfile_3.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            downloads = _http_pathify([
                ('bigfile_1.dat', 'bigfile_1.dat'),
                ('bigfile_2.dat', 'bigfile_2.dat'),
                ('bigfile_3.dat', 'bigfile_3.dat'),
                ('missing.txt', 'missing.txt'),
                ])
            self.assertRaises(FileNotFoundError,
                              DBusDownloadManager().get_files,
                              downloads)
            # The temporary directory is empty.
            self.assertEqual(os.listdir(config.tempdir), [])

    @configuration
    def test_download_pause_resume(self):
        with ExitStack() as stack:
            serverdir = stack.enter_context(temporary_directory())
            stack.push(make_http_server(serverdir, 8980))
            # Create a couple of big files to download.
            with open(os.path.join(serverdir, 'bigfile_1.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            with open(os.path.join(serverdir, 'bigfile_2.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            with open(os.path.join(serverdir, 'bigfile_3.dat'), 'wb') as fp:
                fp.write(b'x' * 10 * MiB)
            downloads = _http_pathify([
                ('bigfile_1.dat', 'bigfile_1.dat'),
                ('bigfile_2.dat', 'bigfile_2.dat'),
                ('bigfile_3.dat', 'bigfile_3.dat'),
                ])
            downloader = DBusDownloadManager()
            pauses = []
            def do_paused(self, signal, path, paused):
                if paused:
                    pauses.append(datetime.now())
            resumes = []
            def do_resumed(self, signal, path, resumed):
                if resumed:
                    resumes.append(datetime.now())
            def pause_on_start(self, signal, path, started):
                if started:
                    downloader.pause()
                    GLib.timeout_add_seconds(3, downloader.resume)
            stack.enter_context(
                patch('systemimage.download.DownloadReactor._do_paused',
                      do_paused))
            stack.enter_context(
                patch('systemimage.download.DownloadReactor._do_resumed',
                      do_resumed))
            stack.enter_context(
                patch('systemimage.download.DownloadReactor._do_started',
                      pause_on_start))
            downloader.get_files(downloads, pausable=True)
            self.assertEqual(len(pauses), 1)
            self.assertEqual(len(resumes), 1)
            self.assertGreaterEqual(resumes[0] - pauses[0],
                                    timedelta(seconds=2.5))


class TestRecord(unittest.TestCase):
    def test_record(self):
        # A record can provide three arguments, the url, destination, and
        # checksum.
        record = Record('src', 'dst', 'hash')
        self.assertEqual(record.url, 'src')
        self.assertEqual(record.destination, 'dst')
        self.assertEqual(record.checksum, 'hash')

    def test_record_default_checksum(self):
        # The checksum is optional, and defaults to the empty string.
        record = Record('src', 'dst')
        self.assertEqual(record.url, 'src')
        self.assertEqual(record.destination, 'dst')
        self.assertEqual(record.checksum, '')

    def test_too_few_arguments(self):
        # At least two arguments must be given.
        self.assertRaises(TypeError, Record, 'src')

    def test_too_many_arguments(self):
        # No more than three arguments may be given.
        self.assertRaises(TypeError, Record, 'src', 'dst', 'hash', 'foo')
