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
    'TestChannelSignature',
    'TestChannels',
    'TestLoadChannel',
    'TestLoadChannelOverHTTPS',
    ]


import os
import hashlib
import unittest

from contextlib import ExitStack
from resolver.config import config
from resolver.gpg import SignatureError
from resolver.helpers import temporary_directory
from resolver.state import State
from resolver.tests.helpers import (
    copy, get_channels, make_http_server, setup_keyrings,
    setup_remote_keyring, sign, testable_configuration)


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
        setup_remote_keyring(
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
        self._state = State()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            copy('channels_01.json', self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            # Get the blacklist.
            next(self._state)
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @testable_configuration
    def test_load_channel_over_https_port_with_http_fails(self):
        # We maliciously put an HTTP server on the HTTPS port.  This should
        # still fail.
        with make_http_server(self._serverdir, 8943):
            self.assertRaises(FileNotFoundError, next, self._state)


class TestChannelSignature(unittest.TestCase):
    """Test the signature and updating of the signing keys."""

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
    def test_first_signature_fails_get_new_image_signing_key(self):
        # The first time we check the channels.json file, the signature fails.
        # Everything works out in the end though because a new system image
        # signing key is downloaded.
        #
        # Start by signing the channels file with a blacklisted key.
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        setup_remote_keyring(
            'image-signing.gpg', 'image-master.gpg', dict(type='signing'),
            os.path.join(self._serverdir, 'gpg', 'signing.tar.xz'))
        # Run through the state machine twice so that we get the blacklist and
        # the channels.json file.  Since the channels.json file will not be
        # signed correctly, new state transitions will be added to re-aquire a
        # new image signing key.
        state = State()
        next(state)
        next(state)
        # Where we would expect a channels object, there is none.
        self.assertIsNone(state.channels)
        # Just to prove that the image signing key is going to change, let's
        # calculate the current one's checksum.
        with open(config.gpg.image_signing, 'rb') as fp:
            checksum = hashlib.md5(fp.read())
        next(state)
        # Now we have a new image signing key.
        with open(config.gpg.image_signing, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()))
        # Let's re-sign the channels.json file with the new image signing
        # key.  Then step the state machine once more and we should get a
        # valid channels object.
        sign(self._channels_path, 'image-signing.gpg')
        next(state)
        self.assertEqual(state.channels.stable.nexus7.index,
                         '/stable/nexus7/index.json')
