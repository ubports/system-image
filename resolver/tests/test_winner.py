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

"""Test downloading the candidate winner files."""

__all__ = [
    'TestWinnerDownloads',
    ]


import os
import unittest

from contextlib import ExitStack
from resolver.candidates import get_candidates, get_downloads
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import SignatureError
from resolver.helpers import temporary_directory
from resolver.logging import initialize
from resolver.scores import WeightedScorer
from resolver.state import ChecksumError, State
from resolver.tests.helpers import (
    copy, get_index, make_http_server, makedirs, setup_keyring_txz,
    setup_keyrings, sign, test_data_path, testable_configuration)


EMPTYSTRING = ''


def setUpModule():
    # BAW 2013-06-17: For correctness, this really should be put in all
    # test_*.py modules, or in a global test runner.  As it is, this only
    # quiets the logging output for tests in this module and later.
    initialize(verbosity=3)


class TestWinnerDownloads(unittest.TestCase):
    """Test full end-to-end downloads through index.json."""

    maxDiff = None

    def setUp(self):
        # Start both an HTTP and an HTTPS server running.  The former is for
        # the zip files and the latter is for everything else.  Vend them out
        # of a temporary directory which we load up with the right files.
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            copy('channels_02.json', self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            # index_10.json path B will win, with no bootme flags.
            self._indexpath = os.path.join('stable', 'nexus7', 'index.json')
            copy('index_12.json', self._serverdir, self._indexpath)
            sign(os.path.join(self._serverdir, self._indexpath),
                 'image-signing.gpg')
            # Create every file in path B.  The file contents will be the
            # checksum value.  We need to create the signatures on the fly.
            self._signfiles('image-signing.gpg')
            self._stack.push(
                make_http_server(self._serverdir, 8943, 'cert.pem', 'key.pem'))
            self._stack.push(make_http_server(self._serverdir, 8980))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    def _signfiles(self, keyring):
        for image in get_index('index_12.json').images:
            if 'B' not in image.description:
                continue
            for filerec in image.files:
                path = (filerec.path[1:]
                        if filerec.path.startswith('/')
                        else filerec.path)
                dst = os.path.join(self._serverdir, path)
                makedirs(os.path.dirname(dst))
                contents = EMPTYSTRING.join(
                    os.path.splitext(filerec.path)[0].split('/'))
                with open(dst, 'w', encoding='utf-8') as fp:
                    fp.write(contents)
                # Sign with the imaging signing key.  Some tests will
                # re-sign all these files with the device key.
                sign(dst, keyring)

    @testable_configuration
    def test_calculate_candidates(self):
        # Calculate the candidate paths.
        setup_keyrings()
        state = State()
        # Run the state machine 4 times to get the candidates and winner.
        # (blacklist -> channel -> index -> calculate)
        for i in range(4):
            next(state)
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # There are three candidate upgrade paths.
        self.assertEqual(len(state.candidates), 3)
        self.assertEqual([c.description for c in state.candidates[0]],
                         ['Full A', 'Delta A.1', 'Delta A.2'])
        self.assertEqual([c.description for c in state.candidates[1]],
                         ['Full B', 'Delta B.1', 'Delta B.2'])
        self.assertEqual([c.description for c in state.candidates[2]],
                         ['Full C', 'Delta C.1'])

    @testable_configuration
    def test_calculate_winner(self):
        # Calculate the winning upgrade path.
        setup_keyrings()
        state = State()
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Run the state machine 4 times to get the candidates and winner.
        # (blacklist -> channel -> index -> calculate)
        for i in range(4):
            next(state)
        # There are three candidate upgrade paths.
        self.assertEqual([w.description for w in state.winner],
                         ['Full B', 'Delta B.1', 'Delta B.2'])

    @testable_configuration
    def test_download_winners(self):
        # Check that all the winning path's files are downloaded.
        setup_keyrings()
        state = State()
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Run the state machine 5 times to get the files.
        # (blacklist -> channel -> index -> calculate -> download)
        for i in range(5):
            next(state)
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

    @testable_configuration
    def test_download_winners_signed_by_device_key(self):
        # Check that all the winning path's files are downloaded, even when
        # they are signed by the device key instead of the image signing
        # master.
        setup_keyrings()
        # To set up the device signing key, we need to load channels_03.json
        # and copy the device keyring to the server.
        copy('channels_03.json', self._serverdir, 'channels.json')
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
        self._signfiles('device-signing.gpg')
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Because there's a device key, run the state machine 6 times to get
        # the files.
        # (blacklist -> channel -> index -> devicekey -> calculate -> download)
        state = State()
        for i in range(6):
            next(state)
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

    @testable_configuration
    def test_download_winners_signed_by_signing_key_with_device_key(self):
        # Check that all the winning path's files are downloaded, even when
        # they are signed by the device key instead of the image signing
        # master.
        setup_keyrings()
        # To set up the device signing key, we need to load channels_03.json
        # and copy the device keyring to the server.
        copy('channels_03.json', self._serverdir, 'channels.json')
        sign(os.path.join(self._serverdir, 'channels.json'),
             'image-signing.gpg')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        sign(os.path.join(self._serverdir, self._indexpath),
             'device-signing.gpg')
        # All the downloadable files are now signed with the image signing key.
        self._signfiles('image-signing.gpg')
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Because there's a device key, run the state machine 6 times to get
        # the files.
        # (blacklist -> channel -> index -> devicekey -> calculate -> download)
        state = State()
        for i in range(6):
            next(state)
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

    @testable_configuration
    def test_download_winners_bad_checksums(self):
        # Similar to the various good paths, except because the checksums are
        # wrong in index_10.json, we'll get a error when downloading.
        copy('index_10.json', self._serverdir, self._indexpath)
        sign(os.path.join(self._serverdir, self._indexpath),
             'image-signing.gpg')
        self._index = get_index('index_10.json')
        self._signfiles('image-signing.gpg')
        setup_keyrings()
        state = State()
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Run the state machine 4 times to get prepped.
        # (blacklist -> channel -> index -> calculate)
        # Now try to download the files and get the error.
        for i in range(4):
            next(state)
        self.assertRaises(ChecksumError, next, state)

    @testable_configuration
    def test_download_winners_signed_by_wrong_key(self):
        # There is a device key, but the image files are signed by the image
        # signing key, which according to the spec means the files are not
        # signed correctly.
        setup_keyrings()
        # To set up the device signing key, we need to load channels_03.json
        # and copy the device keyring to the server.
        copy('channels_03.json', self._serverdir, 'channels.json')
        sign(os.path.join(self._serverdir, 'channels.json'),
             'image-signing.gpg')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        sign(os.path.join(self._serverdir, self._indexpath),
             'device-signing.gpg')
        # All the downloadable files are now signed with a bogus key.
        self._signfiles('spare.gpg')
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Because there's a device key, run the state machine 6 times to get
        # the files.  However, since we want to catch the exception on step 6,
        # run it just 5 times now.
        #
        # (blacklist -> channel -> index -> devicekey -> calculate -> download)
        state = State()
        for i in range(5):
            next(state)
        # The next state transition will fail because of the missing signature.
        self.assertRaises(SignatureError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.system.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0)

    @testable_configuration
    def test_no_download_winners_with_missing_signature(self):
        # If one of the download files is missing a signature, none of the
        # files get downloaded and get_files() fails.
        setup_keyrings()
        state = State()
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Remove a signature.
        os.remove(os.path.join(self._serverdir, '6/7/8.txt.asc'))
        # Run the state machine 4 times to calculate the winning path.
        # (blacklist -> channel -> index -> calculate [-> download])
        for i in range(4):
            next(state)
        # The next state transition will fail because of the missing signature.
        self.assertRaises(FileNotFoundError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.system.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0)

    @testable_configuration
    def test_no_download_winners_with_bad_signature(self):
        # If one of the download files has a bad a signature, none of the
        # files get downloaded and get_files() fails.
        setup_keyrings()
        state = State()
        # Set the build number.
        with open(config.system.build_file, 'wt', encoding='utf-8') as fp:
            print(20120100, file=fp)
        # Break a signature
        sign(os.path.join(self._serverdir, '6', '7', '8.txt'), 'spare.gpg')
        # Run the state machine 4 times to calculate the winning path.
        # (blacklist -> channel -> index -> calculate [-> download])
        for i in range(4):
            next(state)
        # The next state transition will fail because of the missing signature.
        self.assertRaises(SignatureError, next, state)
        # There are no downloaded files.
        txtfiles = set(filename
                       for filename in os.listdir(config.system.tempdir)
                       if os.path.splitext(filename)[1] == '.txt')
        self.assertEqual(len(txtfiles), 0)
