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

"""Test the node classes."""

__all__ = [
    'TestChannels',
    'TestLoadChannels',
    ]


import os
import shutil
import tempfile
import unittest

from resolver.channel import load_channel
from resolver.tests.helpers import (
    get_channels, make_http_server, make_temporary_cache)
from pkg_resources import resource_filename


class TestChannels(unittest.TestCase):
    def setUp(self):
        self.channels = get_channels('channels_01.json')

    def test_channels(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channels.
        self.assertEqual(
            self.channels.daily.nexus7, '/daily/nexus7/index.json')
        self.assertEqual(
            self.channels.daily.nexus4, '/daily/nexus4/index.json')
        self.assertEqual(
            self.channels.stable.nexus7, '/stable/nexus7/index.json')

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        self.assertRaises(AttributeError, getattr, self.channels, 'bleeding')
        self.assertRaises(AttributeError,
                          getattr, self.channels.stable, 'nexus3')


class TestLoadChannels(unittest.TestCase):
    """Test downloading and caching the channels.json file."""

    @classmethod
    def setUpClass(cls):
        # Start the HTTP server running.  Vend it out of a temporary directory
        # we conspire to contain the appropriate files.
        cls._tempdir = tempfile.mkdtemp()
        try:
            # If an exception occurs in any of the following, we must make
            # sure to remove our temporary directory explicitly, since
            # tearDownClass() won't get called.
            pubkey_src = resource_filename('resolver.tests.data',
                                           'phablet.pubkey.asc')
            pubkey_dst = os.path.join(cls._tempdir, 'phablet.pubkey.asc')
            shutil.copyfile(pubkey_src, pubkey_dst)
            channels_src = resource_filename('resolver.tests.data',
                                             'channels_01.json')
            channels_dst = os.path.join(cls._tempdir, 'channels.json')
            shutil.copyfile(channels_src, channels_dst)
            asc_src = resource_filename('resolver.tests.data',
                                        'channels_01.json.asc')
            asc_dst = os.path.join(cls._tempdir, 'channels.json.asc')
            shutil.copyfile(asc_src, asc_dst)
        except:
            shutil.rmtree(cls._tempdir)
            raise
        cls._stop = make_http_server(cls._tempdir)

    @classmethod
    def tearDownClass(cls):
        # Stop the HTTP server.
        try:
            shutil.rmtree(cls._tempdir)
        finally:
            cls._stop()

    def setUp(self):
        self._cache = make_temporary_cache(self.addCleanup)

    def test_load_channel(self):
        # With an empty cache, the channel.json and channels.json.asc files
        # are downloaded, and the signature matches.
        self.assertIsNone(self._cache.get_path('channels.json'))
        channels = load_channel(self._cache)
        self.assertIsNotNone(self._cache.get_path('channels.json'))
        self.assertEqual(channels.daily.nexus7, '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.nexus4, '/daily/nexus4/index.json')
        self.assertEqual(channels.stable.nexus7, '/stable/nexus7/index.json')

    def test_load_channel_bad_signature(self):
        # If the signature on the channels.json file is bad, then we get a
        # FileNotFoundError and the cache is not filled.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.bad.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        self.assertRaises(FileNotFoundError, load_channel, self._cache)
        self.assertIsNone(self._cache.get_path('channels.json'))
        self.assertIsNone(self._cache.get_path('channels.json.asc'))

    def test_load_channel_from_cache(self):
        # The first time downloads from the web service.  The second one loads
        # it from the cache.
        self.assertIsNone(self._cache.get_path('channels.json'))
        load_channel(self._cache)
        self.assertIsNotNone(self._cache.get_path('channels.json'))
        channels = load_channel(self._cache)
        self.assertEqual(channels.daily.nexus7, '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.nexus4, '/daily/nexus4/index.json')
        self.assertEqual(channels.stable.nexus7, '/stable/nexus7/index.json')

    def test_load_channel_bad_signature_gets_fixed(self):
        # The first load gets a bad signature, but the second one fixes the
        # signature and everything is fine.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.bad.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        self.assertRaises(FileNotFoundError, load_channel, self._cache)
        self.assertIsNone(self._cache.get_path('channels.json'))
        self.assertIsNone(self._cache.get_path('channels.json.asc'))
        # Fix the signature file on the server.  Because the cache wasn't
        # filled, it will be downloaded again.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        channels = load_channel(self._cache)
        self.assertIsNotNone(self._cache.get_path('channels.json'))
        self.assertEqual(channels.daily.nexus7, '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.nexus4, '/daily/nexus4/index.json')
        self.assertEqual(channels.stable.nexus7, '/stable/nexus7/index.json')
