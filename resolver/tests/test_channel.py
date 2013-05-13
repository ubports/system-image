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

from contextlib import ExitStack
from functools import partial
from pkg_resources import resource_filename
from resolver.channel import load_channel
from resolver.tests.helpers import (
    copy as copyfile, get_channels, make_http_server, test_configuration)


class TestChannels(unittest.TestCase):
    def setUp(self):
        self.channels = get_channels('channels_01.json')

    def test_channels(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channels.  The Nexus 7 daily images have a device
        # specific keyring.
        self.assertEqual(
            self.channels.daily.nexus7.index, '/daily/nexus7/index.json')
        self.assertEqual(
            self.channels.daily.nexus7.keyring, '/daily/nexus7/keyring.gpg')
        self.assertEqual(
            self.channels.daily.nexus4.index, '/daily/nexus4/index.json')
        self.assertEqual(
            self.channels.stable.nexus7.index, '/stable/nexus7/index.json')

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        self.assertRaises(AttributeError, getattr, self.channels, 'bleeding')
        self.assertRaises(AttributeError,
                          getattr, self.channels.stable, 'nexus3')


class TestLoadChannels(unittest.TestCase):
    """Test downloading and caching the channels.json file."""

    @classmethod
    def setUpClass(cls):
        cls._cleaners = ExitStack()
        # Start the HTTP server running.  Vend it out of a temporary directory
        # we conspire to contain the appropriate files.
        try:
            cls._tempdir = tempfile.mkdtemp()
            copy = partial(copyfile, todir=cls._tempdir)
            cls._cleaners.callback(shutil.rmtree, cls._tempdir)
            copy('phablet.pubkey.asc')
            copy('channels_01.json', dst='channels.json')
            copy('channels_01.json.asc', dst='channels.json.asc')
            cls._stop = make_http_server(cls._tempdir, 8980)
            cls._cleaners.callback(cls._stop)
        except:
            cls._cleaners.pop_all().close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._cleaners.close()

    @test_configuration
    def test_load_channel(self):
        # The channel.json and channels.json.asc files are downloaded, and the
        # signature matches.
        channels = load_channel()
        self.assertEqual(channels.daily.nexus7.index,
                         '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.nexus7.keyring,
                         '/daily/nexus7/keyring.gpg')
        self.assertEqual(channels.daily.nexus4.index,
                         '/daily/nexus4/index.json')
        self.assertIsNone(getattr(channels.daily.nexus4, 'keyring', None))
        self.assertEqual(channels.stable.nexus7.index,
                         '/stable/nexus7/index.json')
        self.assertIsNone(getattr(channels.stable.nexus7, 'keyring', None))

    @test_configuration
    def test_load_channel_bad_signature(self):
        # If the signature on the channels.json file is bad, then we get a
        # FileNotFoundError.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.bad.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        self.assertRaises(FileNotFoundError, load_channel)

    @test_configuration
    def test_load_channel_bad_signature_gets_fixed(self):
        # The first load gets a bad signature, but the second one fixes the
        # signature and everything is fine.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.bad.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        self.assertRaises(FileNotFoundError, load_channel)
        # Fix the signature file on the server.
        asc_src = resource_filename('resolver.tests.data',
                                    'channels_01.json.asc')
        asc_dst = os.path.join(self._tempdir, 'channels.json.asc')
        shutil.copyfile(asc_src, asc_dst)
        channels = load_channel()
        self.assertEqual(channels.daily.nexus7.index,
                         '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.nexus7.keyring,
                         '/daily/nexus7/keyring.gpg')
        self.assertEqual(channels.daily.nexus4.index,
                         '/daily/nexus4/index.json')
        self.assertEqual(channels.stable.nexus7.index,
                         '/stable/nexus7/index.json')
