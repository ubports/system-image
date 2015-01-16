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

"""Test downloading the candidate winner files."""

__all__ = [
    'TestWinnerDownloads',
    ]


import os
import unittest

from contextlib import ExitStack
from systemimage.candidates import get_candidates
from systemimage.config import config
from systemimage.gpg import SignatureError
from systemimage.helpers import temporary_directory
from systemimage.state import State
from systemimage.testing.helpers import (
    configuration, copy, make_http_server, setup_index, setup_keyring_txz,
    setup_keyrings, sign, touch_build)
from systemimage.testing.nose import SystemImagePlugin


class TestWinnerDownloads(unittest.TestCase):
    """Test full end-to-end downloads through index.json."""

    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        # Start both an HTTP and an HTTPS server running.  The former is for
        # the zip files and the latter is for everything else.  Vend them out
        # of a temporary directory which we load up with the right files.
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            copy('winner.channels_01.json', self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            # Path B will win, with no bootme flags.
            self._indexpath = os.path.join('stable', 'nexus7', 'index.json')
            copy('winner.index_02.json', self._serverdir, self._indexpath)
            sign(os.path.join(self._serverdir, self._indexpath),
                 'image-signing.gpg')
            # Create every file in path B.  The file contents will be the
            # checksum value.  We need to create the signatures on the fly.
            setup_index('winner.index_02.json', self._serverdir,
                        'image-signing.gpg')
            self._stack.push(
                make_http_server(self._serverdir, 8943, 'cert.pem', 'key.pem'))
            self._stack.push(make_http_server(self._serverdir, 8980))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_calculate_candidates(self):
        # Calculate the candidate paths.
        setup_keyrings()
        state = State()
        # Run the state machine until we get an index file.
        state.run_until('calculate_winner')
        candidates = get_candidates(state.index, 100)
        # There are three candidate upgrade paths.
        self.assertEqual(len(candidates), 3)
        descriptions = []
        for image in candidates[0]:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full A', 'Delta A.1', 'Delta A.2'])
        descriptions = []
        for image in candidates[1]:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full B', 'Delta B.1', 'Delta B.2'])
        descriptions = []
        for image in candidates[2]:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full C', 'Delta C.1'])

    @configuration
    def test_calculate_winner(self):
        # Calculate the winning upgrade path.
        setup_keyrings()
        state = State()
        touch_build(100)
        # Run the state machine long enough to get the candidates and winner.
        state.run_thru('calculate_winner')
        # There are three candidate upgrade paths.
        descriptions = []
        for image in state.winner:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full B', 'Delta B.1', 'Delta B.2'])

    @configuration
    def test_download_winners(self):
        # Check that all the winning path's files are downloaded.
        setup_keyrings()
        state = State()
        touch_build(100)
        # Run the state machine until we download the files.
        state.run_thru('download_files')
        # The B path files contain their checksums.
        def assert_file_contains(filename, contents):
            path = os.path.join(config.updater.cache_partition, filename)
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

    @configuration
    def test_download_winners_overwrite(self):
        # Check that all the winning path's files are downloaded, even if
        # those files already exist in their destination paths.
        setup_keyrings()
        state = State()
        touch_build(100)
        # Run the state machine until we download the files.
        for basename in '56789abcd':
            base = os.path.join(config.updater.cache_partition, basename)
            path = base + '.txt'
            with open(path, 'w', encoding='utf-8') as fp:
                print('stale', file=fp)
        state.run_thru('download_files')
        # The B path files contain their checksums.
        def assert_file_contains(filename, contents):
            path = os.path.join(config.updater.cache_partition, filename)
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

    @configuration
    def test_download_winners_signed_by_device_key(self):
        # Check that all the winning path's files are downloaded, even when
        # they are signed by the device key instead of the image signing
        # master.
        setup_keyrings()
        # To set up the device signing key, we need to load channels_03.json
        # and copy the device keyring to the server.
        copy('winner.channels_02.json', self._serverdir, 'channels.json')
        sign(os.path.join(self._serverdir, 'channels.json'),
             'image-signing.gpg')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        # The index.json file and all the downloadable files must now be
        # signed with the device key.
        sign(os.path.join(self._serverdir, self._indexpath),
             'device-signing.gpg')
        setup_index('winner.index_02.json', self._serverdir,
                    'device-signing.gpg')
        touch_build(100)
        # Run the state machine until we download the files.
        state = State()
        state.run_thru('download_files')
        # The B path files contain their checksums.
        def assert_file_contains(filename, contents):
            path = os.path.join(config.updater.cache_partition, filename)
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

    @configuration
    def test_download_winners_signed_by_signing_key_with_device_key(self):
        # Check that all the winning path's files are downloaded, even when
        # they are signed by the device key instead of the image signing
        # master.
        setup_keyrings()
        # To set up the device signing key, we need to load this channels.json
        # file and copy the device keyring to the server.
        copy('winner.channels_02.json', self._serverdir, 'channels.json')
        sign(os.path.join(self._serverdir, 'channels.json'),
             'image-signing.gpg')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        sign(os.path.join(self._serverdir, self._indexpath),
             'device-signing.gpg')
        # All the downloadable files are now signed with the image signing key.
        setup_index('winner.index_02.json', self._serverdir,
                    'image-signing.gpg')
        touch_build(100)
        # Run the state machine until we download the files.
        state = State()
        state.run_thru('download_files')
        # The B path files contain their checksums.
        def assert_file_contains(filename, contents):
            path = os.path.join(config.updater.cache_partition, filename)
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

    @configuration
    def test_download_winners_bad_checksums(self):
        # Similar to the various good paths, except because the checksums are
        # wrong in this index.json file, we'll get a error when downloading.
        copy('winner.index_01.json', self._serverdir, self._indexpath)
        sign(os.path.join(self._serverdir, self._indexpath),
             'image-signing.gpg')
        setup_index('winner.index_01.json', self._serverdir,
                    'image-signing.gpg')
        setup_keyrings()
        state = State()
        touch_build(100)
        # Run the state machine until we're prepped to download
        state.run_until('download_files')
        # Now try to download the files and get the error.
        with self.assertRaises(FileNotFoundError) as cm:
            next(state)
        self.assertIn('HASH ERROR', str(cm.exception))

    @configuration
    def test_download_winners_signed_by_wrong_key(self):
        # There is a device key, but the image files are signed by the image
        # signing key, which according to the spec means the files are not
        # signed correctly.
        setup_keyrings()
        # To set up the device signing key, we need to load this channels.json
        # file and copy the device keyring to the server.
        copy('winner.channels_02.json', self._serverdir, 'channels.json')
        sign(os.path.join(self._serverdir, 'channels.json'),
             'image-signing.gpg')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        sign(os.path.join(self._serverdir, self._indexpath),
             'device-signing.gpg')
        # All the downloadable files are now signed with a bogus key.
        setup_index('winner.index_02.json', self._serverdir, 'spare.gpg')
        touch_build(100)
        # Run the state machine until just before we download the files.
        state = State()
        state.run_until('download_files')
        # The next state transition will fail because of the missing signature.
        self.assertRaises(SignatureError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0)

    @configuration
    def test_no_download_winners_with_missing_signature(self):
        # If one of the download files is missing a signature, none of the
        # files get downloaded and get_files() fails.
        setup_keyrings()
        state = State()
        touch_build(100)
        # Remove a signature.
        os.remove(os.path.join(self._serverdir, '6/7/8.txt.asc'))
        # Run the state machine to calculate the winning path.
        state.run_until('download_files')
        # The next state transition will fail because of the missing signature.
        self.assertRaises(FileNotFoundError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0, txtfiles)

    @configuration
    def test_no_download_winners_with_bad_signature(self):
        # If one of the download files has a bad a signature, none of the
        # downloaded files are available.
        setup_keyrings()
        state = State()
        touch_build(100)
        # Break a signature
        sign(os.path.join(self._serverdir, '6', '7', '8.txt'), 'spare.gpg')
        # Run the state machine to calculate the winning path.
        state.run_until('download_files')
        # The next state transition will fail because of the missing signature.
        self.assertRaises(SignatureError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0)
