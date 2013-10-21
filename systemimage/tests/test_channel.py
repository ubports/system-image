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
    'TestLoadChannel',
    'TestLoadChannelOverHTTPS',
    'TestChannelsNewFormat',
    ]


import os
import unittest

from contextlib import ExitStack
from operator import getitem
from systemimage.gpg import SignatureError
from systemimage.helpers import temporary_directory
from systemimage.state import State
from systemimage.testing.helpers import (
    configuration, copy, get_channels, make_http_server, setup_keyring_txz,
    setup_keyrings, sign)
from systemimage.testing.nose import SystemImagePlugin


class TestChannels(unittest.TestCase):
    def test_channels(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channels.  The Nexus 7 daily images have a device
        # specific keyring.
        channels = get_channels('channels_01.json')
        self.assertEqual(channels.daily.devices.nexus7.index,
                         '/daily/nexus7/index.json')
        self.assertEqual(channels.daily.devices.nexus7.keyring.path,
                         '/daily/nexus7/device-keyring.tar.xz')
        self.assertEqual(channels.daily.devices.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')
        self.assertEqual(channels.daily.devices.nexus4.index,
                         '/daily/nexus4/index.json')
        self.assertIsNone(
            getattr(channels.daily.devices.nexus4, 'keyring', None))
        self.assertEqual(channels.stable.devices.nexus7.index,
                         '/stable/nexus7/index.json')

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        channels = get_channels('channels_01.json')
        self.assertRaises(AttributeError, getattr, channels, 'bleeding')
        self.assertRaises(AttributeError, getattr, channels.stable, 'nexus3')

    def test_daily_proposed(self):
        # The channel name has a dash in it.
        channels = get_channels('channels_07.json')
        self.assertEqual(channels['daily-proposed'].devices.grouper.index,
                         '/daily-proposed/grouper/index.json')

    def test_bad_getitem(self):
        # Trying to get a channel via getitem which doesn't exist.
        channels = get_channels('channels_07.json')
        self.assertRaises(KeyError, getitem, channels, 'daily-testing')

    def test_channel_version(self):
        # The channel name has a dot in it.
        channels = get_channels('channels_08.json')
        self.assertEqual(channels['13.10'].devices.grouper.index,
                         '/13.10/grouper/index.json')

    def test_channel_version_proposed(self):
        # The channel name has both a dot and a dash in it.
        channels = get_channels('channels_08.json')
        self.assertEqual(channels['14.04-proposed'].devices.grouper.index,
                         '/14.04-proposed/grouper/index.json')


class TestLoadChannel(unittest.TestCase):
    """Test downloading and caching the channels.json file."""

    @classmethod
    def setUpClass(cls):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._stack = ExitStack()
        self._state = State()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
            copy('channels_01.json', self._serverdir, 'channels.json')
            self._channels_path = os.path.join(
                self._serverdir, 'channels.json')
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_load_channel_good_path(self):
        # A channels.json file signed by the image signing key, no blacklist.
        sign(self._channels_path, 'image-signing.gpg')
        setup_keyrings()
        self._state.run_thru('get_channel')
        channels = self._state.channels
        self.assertEqual(channels.daily.devices.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')

    @configuration
    def test_load_channel_bad_signature(self):
        # We get an error if the signature on the channels.json file is bad.
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        self._state.run_thru('get_channel')
        self.assertRaises(SignatureError, next, self._state)

    @configuration
    def test_load_channel_blacklisted_signature(self):
        # We get an error if the signature on the channels.json file is good
        # but the key is blacklisted.
        sign(self._channels_path, 'image-signing.gpg')
        setup_keyrings()
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        self._state.run_thru('get_channel')
        self.assertRaises(SignatureError, next, self._state)

    @configuration
    def test_load_channel_bad_signature_gets_fixed(self):
        # The first load gets a bad signature, but the second one fixes the
        # signature and everything is fine.
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        self._state.run_thru('get_channel')
        self.assertRaises(SignatureError, next, self._state)
        sign(self._channels_path, 'image-signing.gpg')
        state = State()
        state.run_thru('get_channel')
        channels = state.channels
        self.assertEqual(channels.daily.devices.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')


class TestLoadChannelOverHTTPS(unittest.TestCase):
    """channels.json MUST be downloaded over HTTPS.

    Start an HTTP server, no HTTPS server to show the download fails.
    """
    @classmethod
    def setUpClass(cls):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            copy('channels_01.json', self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_load_channel_over_https_port_with_http_fails(self):
        # We maliciously put an HTTP server on the HTTPS port.
        setup_keyrings()
        state = State()
        # Try to get the blacklist.  This will fail silently since it's okay
        # not to find a blacklist.
        state.run_thru('get_blacklist_1')
        # This will fail to get the channels.json file.
        with make_http_server(self._serverdir, 8943):
            self.assertRaises(FileNotFoundError, next, state)


class TestChannelsNewFormat(unittest.TestCase):
    """LP: #1221841 introduces a new format to channels.json."""
    def test_channels(self):
        # We can parse new-style channels.json files.
        channels = get_channels('channels_09.json')
        self.assertEqual(channels.daily.alias, 'saucy')
        self.assertEqual(channels.daily.devices.grouper.index,
                         '/daily/grouper/index.json')
        self.assertEqual(channels.daily.devices.mako.index,
                         '/daily/mako/index.json')
        # 'saucy' channel has no alias.
        self.assertRaises(AttributeError, getattr, channels.saucy, 'alias')
        self.assertEqual(channels.saucy.devices.mako.index,
                         '/saucy/mako/index.json')
        # 'saucy-proposed' has a hidden field.
        self.assertTrue(channels.saucy_proposed.hidden)
        self.assertEqual(channels.saucy_proposed.devices.maguro.index,
                         '/saucy-proposed/maguro/index.json')
        # Device specific keyrings are still supported.
        self.assertEqual(channels.saucy.devices.manta.keyring.path,
                         '/saucy/manta/device-signing.tar.xz')

    def test_hidden_defaults_to_false(self):
        # If a channel does not have a hidden field, it defaults to false.
        channels = get_channels('channels_09.json')
        self.assertFalse(channels.daily.hidden)

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        channels = get_channels('channels_09.json')
        self.assertRaises(AttributeError, getattr, channels, 'bleeding')
        self.assertRaises(
            AttributeError, getattr, channels.daily.devices, 'nexus3')

    def test_daily_proposed(self):
        # The channel name has a dash in it.
        channels = get_channels('channels_09.json')
        self.assertEqual(channels['saucy-proposed'].devices.grouper.index,
                         '/saucy-proposed/grouper/index.json')

    def test_bad_getitem(self):
        # Trying to get a channel via getitem which doesn't exist.
        channels = get_channels('channels_09.json')
        self.assertRaises(KeyError, getitem, channels, 'daily-testing')
