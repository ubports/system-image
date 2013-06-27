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
    ]


import os
import unittest

from contextlib import ExitStack
from systemimage.gpg import SignatureError
from systemimage.helpers import temporary_directory
from systemimage.logging import initialize
from systemimage.state import State
from systemimage.tests.helpers import (
    copy, get_channels, make_http_server, setup_keyring_txz, setup_keyrings,
    sign, testable_configuration)


def setUpModule():
    # BAW 2013-06-17: For correctness, this really should be put in all
    # test_*.py modules, or in a global test runner.  As it is, this only
    # quiets the logging output for tests in this module and later.
    initialize(verbosity=3)


class TestChannels(unittest.TestCase):
    def setUp(self):
        self.channels = get_channels('channels_01.json')

    def test_channels(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channels.  The Nexus 7 daily images have a device
        # specific keyring.
        self.assertEqual(self.channels.daily.nexus7.index,
                         '/daily/nexus7/index.json')
        self.assertEqual(self.channels.daily.nexus7.keyring.path,
                         '/daily/nexus7/device-keyring.tar.xz')
        self.assertEqual(self.channels.daily.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')
        self.assertEqual(self.channels.daily.nexus4.index,
                         '/daily/nexus4/index.json')
        self.assertIsNone(getattr(self.channels.daily.nexus4, 'keyring', None))
        self.assertEqual(self.channels.stable.nexus7.index,
                         '/stable/nexus7/index.json')

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        self.assertRaises(AttributeError, getattr, self.channels, 'bleeding')
        self.assertRaises(AttributeError,
                          getattr, self.channels.stable, 'nexus3')


class TestLoadChannel(unittest.TestCase):
    """Test downloading and caching the channels.json file."""

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

    @testable_configuration
    def test_load_channel_good_path(self):
        # A channels.json file signed by the image signing key, no blacklist.
        # (blacklist -> channels)
        sign(self._channels_path, 'image-signing.gpg')
        setup_keyrings()
        next(self._state)
        next(self._state)
        channels = self._state.channels
        self.assertEqual(channels.daily.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')

    @testable_configuration
    def test_load_channel_bad_signature(self):
        # We get an error if the signature on the channels.json file is bad.
        # The state machine needs three transitions:
        # (blacklist -> channels -> signing_key)
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        next(self._state)
        next(self._state)
        self.assertRaises(SignatureError, next, self._state)

    @testable_configuration
    def test_load_channel_blacklisted_signature(self):
        # We get an error if the signature on the channels.json file is good
        # but the key is blacklisted.
        # (blacklist -> channels -> signing_key)
        sign(self._channels_path, 'image-signing.gpg')
        setup_keyrings()
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        next(self._state)
        next(self._state)
        self.assertRaises(SignatureError, next, self._state)

    @testable_configuration
    def test_load_channel_bad_signature_gets_fixed(self):
        # The first load gets a bad signature, but the second one fixes the
        # signature and everything is fine.
        # (blacklist -> channels -> signing_key: FAIL)
        # ...then, re-sign and...
        # (blacklist -> channels)
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        next(self._state)
        next(self._state)
        self.assertRaises(SignatureError, next, self._state)
        sign(self._channels_path, 'image-signing.gpg')
        # Two state transitions are necessary (blacklist -> channels).
        state = State()
        next(state)
        next(state)
        channels = state.channels
        self.assertEqual(channels.daily.nexus7.keyring.signature,
                         '/daily/nexus7/device-keyring.tar.xz.asc')


class TestLoadChannelOverHTTPS(unittest.TestCase):
    """channels.json MUST be downloaded over HTTPS.

    Start an HTTP server, no HTTPS server to show the download fails.
    """
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

    @testable_configuration
    def test_load_channel_over_https_port_with_http_fails(self):
        # We maliciously put an HTTP server on the HTTPS port.
        setup_keyrings()
        state = State()
        # Try to get the blacklist.  This will fail silently since it's okay
        # not to find a blacklist.
        next(state)
        # This will fail to get the channels.json file.
        with make_http_server(self._serverdir, 8943):
            self.assertRaises(FileNotFoundError, next, state)
