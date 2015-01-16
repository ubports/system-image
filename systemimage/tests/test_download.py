# Copyright (C) 2013-2015 Canonical Ltd.
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
    'TestCURL',
    'TestDownload',
    'TestDownloadBigFiles',
    'TestDownloadManagerFactory',
    'TestDuplicateDownloads',
    'TestGSMDownloads',
    'TestHTTPSDownloads',
    'TestHTTPSDownloadsExpired',
    'TestHTTPSDownloadsNasty',
    'TestHTTPSDownloadsNoSelfSigned',
    'TestRecord',
    ]


import os
import sys
import random
import pycurl
import unittest

from contextlib import ExitStack
from dbus.exceptions import DBusException
from hashlib import sha256
from systemimage.config import Configuration, config
from systemimage.curl import CurlDownloadManager
from systemimage.download import (
    Canceled, DuplicateDestinationError, Record, get_download_manager)
from systemimage.helpers import temporary_directory
from systemimage.settings import Settings
from systemimage.testing.controller import USING_PYCURL
from systemimage.testing.helpers import (
    configuration, data_path, make_http_server, reset_envar, write_bytes)
from systemimage.testing.nose import SystemImagePlugin
from systemimage.udm import DOWNLOADER_INTERFACE, UDMDownloadManager
from unittest.mock import patch
from urllib.parse import urljoin


def _http_pathify(downloads):
    return [
        (urljoin(config.http_base, url),
         os.path.join(config.tempdir, filename)
        ) for url, filename in downloads]


def _https_pathify(downloads):
    return [
        (urljoin(config.https_base, url),
         os.path.join(config.tempdir, filename)
        ) for url, filename in downloads]


class TestDownload(unittest.TestCase):
    """Base class for testing the PyCURL and udm downloaders."""

    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(data_path('__init__.py'))
            self._resources.push(make_http_server(directory, 8980))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    def _downloader(self, *args):
        return get_download_manager(*args)

    @configuration
    def test_good_path(self):
        # Download a bunch of files that exist.  No callback.
        self._downloader().get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json'),
            ('download.index_01.json', 'index.json'),
            ]))
        self.assertEqual(
            set(os.listdir(config.tempdir)),
            set(['channels.json', 'index.json']))

    @configuration
    def test_empty_download(self):
        # Empty download set completes successfully.  LP: #1245597.
        self._downloader().get_files([])
        # No TimeoutError is raised.

    @configuration
    def test_user_agent(self):
        # The User-Agent request header contains the build number.
        version = random.randint(0, 99)
        config.build_number = version
        # Download a magic path which the server will interpret to return us
        # the User-Agent header value.
        self._downloader().get_files(_http_pathify([
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
        downloader = self._downloader(callback)
        downloader.get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json'),
            ('download.index_01.json', 'index.json'),
            ]))
        self.assertEqual(
            set(os.listdir(config.tempdir)),
            set(['channels.json', 'index.json']))
        self.assertEqual(received_bytes, 669)
        self.assertEqual(total_bytes, 669)

    @configuration
    def test_download_with_broken_callback(self):
        # If the callback raises an exception, it is logged and ignored.
        def callback(receive, total):
            raise RuntimeError
        exception = None
        def capture(message):
            nonlocal exception
            exception = message
        downloader = self._downloader(callback)
        with patch('systemimage.download.log.exception', capture):
            downloader.get_files(_http_pathify([
                ('channel.channels_05.json', 'channels.json'),
                ]))
        # The exception got logged.
        self.assertEqual(exception, 'Exception in progress callback')
        # The file still got downloaded.
        self.assertEqual(os.listdir(config.tempdir), ['channels.json'])

    @configuration
    def test_no_dev_package(self):
        # system-image-dev contains the systemimage.testing subpackage, but
        # this is not normally installed on the device.  When it's missing,
        # the DownloadReactor's _print() debugging method should no-op.
        #
        # To test this, we patch systemimage.testing in sys.modules so that an
        # ImportError is raised when it tries to import it.
        with patch.dict(sys.modules, {'systemimage.testing.helpers': None}):
            self._downloader().get_files(_http_pathify([
                ('channel.channels_05.json', 'channels.json'),
                ]))
        self.assertEqual(os.listdir(config.tempdir), ['channels.json'])

    # This test helps bump the udm-based downloader test coverage to 100%.
    @unittest.skipIf(USING_PYCURL, 'Test is not relevant for PyCURL')
    @configuration
    def test_timeout(self):
        # If the reactor times out, we get an exception.  We fake the timeout
        # by setting the attribute on the reactor, even though it successfully
        # completes its download without timing out.
        def finish_with_timeout(self, *args, **kws):
            self.timed_out = True
            self.quit()
        with patch('systemimage.udm.DownloadReactor._do_finished',
                   finish_with_timeout):
            self.assertRaises(
                TimeoutError,
                self._downloader().get_files,
                _http_pathify([('channel.channels_05.json', 'channels.json')])
                )


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
            get_download_manager().get_files(_https_pathify([
                ('channel.channels_05.json', 'channels.json'),
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
                get_download_manager().get_files,
                _https_pathify([
                    ('channel.channels_05.json', 'channels.json'),
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
                get_download_manager().get_files,
                _https_pathify([
                    ('channel.channels_05.json', 'channels.json'),
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
                get_download_manager().get_files,
                _https_pathify([
                    ('channel.channels_05.json', 'channels.json'),
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
                get_download_manager().get_files,
                _https_pathify([
                    ('channel.channels_05.json', 'channels.json'),
                    ]))


# These tests don't strictly improve coverage for the udm-based downloader,
# but they are still useful to keep because they test a implicit code path.
# These can be removed once GSM-testing is pulled into s-i via LP: #1388886.
@unittest.skipIf(USING_PYCURL, 'Test is not relevant for PyCURL')
class TestGSMDownloads(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Patch this method so that we can verify both the value of the flag
        # that system-image sets and the value that u-d-m's group downloader
        # records and uses.  This is the only thing we can really
        # automatically test given that e.g. we won't have GSM in development.
        self._gsm_set_flag = None
        self._gsm_get_flag = None
        self._original = None
        def set_gsm(iface, *, allow_gsm):
            self._gsm_set_flag = allow_gsm
            self._original(iface, allow_gsm=allow_gsm)
            self._gsm_get_flag = iface.isGSMDownloadAllowed()
        self._resources = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(data_path('__init__.py'))
            self._resources.push(make_http_server(directory, 8980))
            # Patch the GSM setting method to capture what actually happens.
            self._original = getattr(UDMDownloadManager, '_set_gsm')
            self._resources.enter_context(patch(
                'systemimage.udm.UDMDownloadManager._set_gsm', set_gsm))
            self._resources.callback(setattr, self, '_original', None)
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    @configuration
    def test_manual_downloads_gsm_allowed(self, config_d):
        # When auto_download is 0, manual downloads are enabled so assuming
        # the user knows what they're doing, GSM downloads are allowed.
        config = Configuration(config_d)
        Settings(config).set('auto_download', '0')
        get_download_manager().get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json')
            ]))
        self.assertTrue(self._gsm_set_flag)
        self.assertTrue(self._gsm_get_flag)

    @configuration
    def test_wifi_downloads_gsm_disallowed(self, config_d):
        # Obviously GSM downloads are not allowed when downloading
        # automatically on wifi-only.
        config = Configuration(config_d)
        Settings(config).set('auto_download', '1')
        get_download_manager().get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json')
            ]))
        self.assertFalse(self._gsm_set_flag)
        self.assertFalse(self._gsm_get_flag)

    @configuration
    def test_always_downloads_gsm_allowed(self, config_d):
        # GSM downloads are allowed when always downloading.
        config = Configuration(config_d)
        Settings(config).set('auto_download', '2')
        get_download_manager().get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json')
            ]))
        self.assertTrue(self._gsm_set_flag)
        self.assertTrue(self._gsm_get_flag)


class TestDownloadBigFiles(unittest.TestCase):
    # This test helps bump the udm-based downloader test coverage to 100%.
    @unittest.skipIf(USING_PYCURL, 'Test is not relevant for PyCURL')
    @configuration
    def test_cancel(self):
        # Try to cancel the download of a big file.
        self.assertEqual(os.listdir(config.tempdir), [])
        with ExitStack() as stack:
            serverdir = stack.enter_context(temporary_directory())
            stack.push(make_http_server(serverdir, 8980))
            # Create a couple of big files to download.
            write_bytes(os.path.join(serverdir, 'bigfile_1.dat'), 10)
            write_bytes(os.path.join(serverdir, 'bigfile_2.dat'), 10)
            # The download service doesn't provide reliable cancel
            # granularity, so instead, we mock the 'started' signal to
            # immediately cancel the download.
            downloader = get_download_manager()
            def cancel_on_start(self, signal, path, started):
                if started:
                    downloader.cancel()
            stack.enter_context(patch(
                'systemimage.udm.DownloadReactor._do_started',
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
            write_bytes(os.path.join(serverdir, 'bigfile_1.dat'), 10)
            write_bytes(os.path.join(serverdir, 'bigfile_2.dat'), 10)
            write_bytes(os.path.join(serverdir, 'bigfile_3.dat'), 10)
            downloads = _http_pathify([
                ('bigfile_1.dat', 'bigfile_1.dat'),
                ('bigfile_2.dat', 'bigfile_2.dat'),
                ('bigfile_3.dat', 'bigfile_3.dat'),
                ('missing.txt', 'missing.txt'),
                ])
            self.assertRaises(FileNotFoundError,
                              get_download_manager().get_files,
                              downloads)
            # The temporary directory is empty.
            self.assertEqual(os.listdir(config.tempdir), [])


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


class TestDuplicateDownloads(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        try:
            self._serverdir = self._resources.enter_context(
                temporary_directory())
            self._resources.push(make_http_server(self._serverdir, 8980))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    @configuration
    def test_matched_duplicates(self):
        # A download that duplicates the destination location, but for which
        # the sources and checksums are the same is okay.
        content = b'x' * 100
        checksum = sha256(content).hexdigest()
        with open(os.path.join(self._serverdir, 'source.dat'), 'wb') as fp:
            fp.write(content)
        downloader = get_download_manager()
        downloads = []
        for url, dst in _http_pathify([('source.dat', 'local.dat'),
                                       ('source.dat', 'local.dat'),
                                       ]):
            downloads.append(Record(url, dst, checksum))
        downloader.get_files(downloads)
        self.assertEqual(os.listdir(config.tempdir), ['local.dat'])

    @configuration
    def test_mismatched_urls(self):
        # A download that duplicates the destination location, but for which
        # the source urls don't match, is not allowed.
        content = b'x' * 100
        checksum = sha256(content).hexdigest()
        with open(os.path.join(self._serverdir, 'source1.dat'), 'wb') as fp:
            fp.write(content)
        with open(os.path.join(self._serverdir, 'source2.dat'), 'wb') as fp:
            fp.write(content)
        downloader = get_download_manager()
        downloads = []
        for url, dst in _http_pathify([('source1.dat', 'local.dat'),
                                       ('source2.dat', 'local.dat'),
                                       ]):
            downloads.append(Record(url, dst, checksum))
        with self.assertRaises(DuplicateDestinationError) as cm:
            downloader.get_files(downloads)
        self.assertEqual(len(cm.exception.duplicates), 1)
        dst, dupes = cm.exception.duplicates[0]
        self.assertEqual(os.path.basename(dst), 'local.dat')
        self.assertEqual([r[0] for r in dupes],
                         ['http://localhost:8980/source1.dat',
                          'http://localhost:8980/source2.dat'])
        self.assertEqual(os.listdir(config.tempdir), [])

    @configuration
    def test_mismatched_checksums(self):
        # A download that duplicates the destination location, but for which
        # the checksums don't match, is not allowed.
        content = b'x' * 100
        checksum = sha256(content).hexdigest()
        with open(os.path.join(self._serverdir, 'source.dat'), 'wb') as fp:
            fp.write(content)
        downloader = get_download_manager()
        url = urljoin(config.http_base, 'source.dat')
        downloads = [
            Record(url, 'local.dat', checksum),
            # Mutate the checksum so they won't match.
            Record(url, 'local.dat', checksum[-1] + checksum[:-1]),
            ]
        with self.assertRaises(DuplicateDestinationError) as cm:
            downloader.get_files(downloads)
        self.assertEqual(len(cm.exception.duplicates), 1)
        dst, dupes = cm.exception.duplicates[0]
        self.assertEqual(os.path.basename(dst), 'local.dat')
        self.assertEqual([r[0] for r in dupes],
                         ['http://localhost:8980/source.dat',
                          'http://localhost:8980/source.dat'])
        # The records in the exception aren't sorted by checksum.
        self.assertEqual(
            sorted(r[2] for r in dupes),
            ['09ecb6ebc8bcefc733f6f2ec44f791abeed6a99edf0cc31519637898aebd52d8'
             ,
             '809ecb6ebc8bcefc733f6f2ec44f791abeed6a99edf0cc31519637898aebd52d'
             ])
        self.assertEqual(os.listdir(config.tempdir), [])

    @configuration
    def test_duplicate_error_message(self):
        # When a duplicate destination error occurs, an error message gets
        # logged.  Make sure the error message is helpful.
        content = b'x' * 100
        checksum = sha256(content).hexdigest()
        with open(os.path.join(self._serverdir, 'source.dat'), 'wb') as fp:
            fp.write(content)
        downloader = get_download_manager()
        url = urljoin(config.http_base, 'source.dat')
        downloads = [
            Record(url, 'local.dat', checksum),
            # Mutate the checksum so they won't match.
            Record(url, 'local.dat', checksum[-1] + checksum[:-1]),
            ]
        with self.assertRaises(DuplicateDestinationError) as cm:
            downloader.get_files(downloads)
        self.assertMultiLineEqual(str(cm.exception), """
[   (   'local.dat',
        [   (   'http://localhost:8980/source.dat',
                'local.dat',
                '09ecb6ebc8bcefc733f6f2ec44f791abeed6a99edf0cc31519637898aebd52d8'),
            (   'http://localhost:8980/source.dat',
                'local.dat',
                '809ecb6ebc8bcefc733f6f2ec44f791abeed6a99edf0cc31519637898aebd52d')])]""")


# This class only bumps coverage to 100% for the cURL-based downloader, so it
# can be skipped when the test suite runs under u-d-m.  Checking the
# environment variable wouldn't be enough for production (see download.py
# get_download_manager() for other cases where the downloader is chosen), but
# it's sufficient for the test suite.  See tox.ini.
@unittest.skipIf(USING_PYCURL, 'Test is not relevant for PyCURL')
class TestCURL(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        try:
            # Start the HTTP server running, vending files out of our test
            # data directory.
            directory = os.path.dirname(data_path('__init__.py'))
            self._resources.push(make_http_server(directory, 8980))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    @configuration
    def test_multi_perform(self):
        # PyCURL's multi.perform() can return the E_CALL_MULTI_PEFORM status
        # which tells us to just try again.  This doesn't happen in practice,
        # but the code path needs coverage.  However, .perform() itself can't
        # be mocked because pycurl.CurlMulti is a built-in.  Fun.
        class FakeMulti:
            def perform(self):
                return pycurl.E_CALL_MULTI_PERFORM, 2
        done_once = False
        class Testable(CurlDownloadManager):
            def _do_once(self, multi, handles):
                nonlocal done_once
                if done_once:
                    return super()._do_once(multi, handles)
                else:
                    done_once = True
                    return super()._do_once(FakeMulti(), handles)
        Testable().get_files(_http_pathify([
            ('channel.channels_05.json', 'channels.json'),
            ('download.index_01.json', 'index.json'),
            ]))
        self.assertTrue(done_once)
        # The files still get downloaded.
        self.assertEqual(
            set(os.listdir(config.tempdir)),
            set(['channels.json', 'index.json']))

    @configuration
    def test_multi_fail(self):
        # PyCURL's multi.perform() can return a failure code (i.e. not E_OK)
        # which triggers a FileNotFoundError.  It doesn't really matter which
        # failure code it returns.
        class FakeMulti:
            def perform(self):
                return pycurl.E_READ_ERROR, 2
        class Testable(CurlDownloadManager):
            def _do_once(self, multi, handles):
                return super()._do_once(FakeMulti(), handles)
        with self.assertRaises(FileNotFoundError) as cm:
            Testable().get_files(_http_pathify([
                ('channel.channels_05.json', 'channels.json'),
                ('download.index_01.json', 'index.json'),
                ]))
        # One of the two files will be contained in the error message, but
        # which one is undefined, although in practice it will be the first
        # one.
        self.assertRegex(
            cm.exception.args[0],
            'http://localhost:8980/(channel.channels_05|index_01).json')


class TestDownloadManagerFactory(unittest.TestCase):
    """We have a factory for creating the download manager to use."""

    def test_get_downloader_forced_curl(self):
        # Setting SYSTEMIMAGE_PYCURL envar to 1, yes, or true forces the
        # PyCURL downloader.
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = '1'
            self.assertIsInstance(get_download_manager(), CurlDownloadManager)
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = 'tRuE'
            self.assertIsInstance(get_download_manager(), CurlDownloadManager)
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = 'YES'
            self.assertIsInstance(get_download_manager(), CurlDownloadManager)

    def test_get_downloader_forced_udm(self):
        # Setting SYSTEMIMAGE_PYCURL envar to anything else forces the udm
        # downloader.
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = '0'
            self.assertIsInstance(get_download_manager(), UDMDownloadManager)
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = 'false'
            self.assertIsInstance(get_download_manager(), UDMDownloadManager)
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            os.environ['SYSTEMIMAGE_PYCURL'] = 'nope'
            self.assertIsInstance(get_download_manager(), UDMDownloadManager)

    def test_auto_detect_udm(self):
        # If the environment variable is not set, we do auto-detection.  For
        # backward compatibility, if udm is available on the system bus, we
        # use it.
        with reset_envar('SYSTEMIMAGE_PYCURL'):
            if 'SYSTEMIMAGE_PYCURL' in os.environ:
                del os.environ['SYSTEMIMAGE_PYCURL']
            with patch('dbus.SystemBus.get_object') as mock:
                self.assertIsInstance(
                    get_download_manager(), UDMDownloadManager)
            mock.assert_called_once_with(DOWNLOADER_INTERFACE, '/')

    def test_auto_detect_curl(self):
        # If the environment variable is not set, we do auto-detection.  If udm
        # is not available on the system bus, we use the cURL downloader.
        import systemimage.download
        with ExitStack() as resources:
            resources.enter_context(reset_envar('SYSTEMIMAGE_PYCURL'))
            if 'SYSTEMIMAGE_PYCURL' in os.environ:
                del os.environ['SYSTEMIMAGE_PYCURL']
            mock = resources.enter_context(
                patch('dbus.SystemBus.get_object', side_effect=DBusException))
            resources.enter_context(
                patch.object(systemimage.download, 'pycurl', object()))
            self.assertIsInstance(
                get_download_manager(), CurlDownloadManager)
            mock.assert_called_once_with(DOWNLOADER_INTERFACE, '/')

    def test_auto_detect_none_available(self):
        # Again, we're auto-detecting, but in this case, we have neither udm
        # nor pycurl available.
        import systemimage.download
        with ExitStack() as resources:
            resources.enter_context(reset_envar('SYSTEMIMAGE_PYCURL'))
            if 'SYSTEMIMAGE_PYCURL' in os.environ:
                del os.environ['SYSTEMIMAGE_PYCURL']
            mock = resources.enter_context(
                patch('dbus.SystemBus.get_object', side_effect=DBusException))
            resources.enter_context(
                patch.object(systemimage.download, 'pycurl', None))
            self.assertRaises(ImportError, get_download_manager)
            mock.assert_called_once_with(DOWNLOADER_INTERFACE, '/')
