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
from functools import partial
from resolver.candidates import get_candidates, get_downloads
from resolver.config import config
from resolver.download import get_files
from resolver.helpers import temporary_directory
from resolver.index import load_current_index
from resolver.scores import WeightedScorer
from resolver.tests.helpers import (
    copy as copyfile, get_index, make_http_server, makedirs, sign,
    test_data_path, testable_configuration)


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
            cls._serverdir = cls._stack.enter_context(temporary_directory())
            keyring_dir = os.path.dirname(test_data_path('__init__.py'))
            copy = partial(copyfile, todir=cls._serverdir)
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
