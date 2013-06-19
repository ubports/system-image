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

"""Test channel/device index parsing."""

__all__ = [
    'TestIndex',
    'TestDownloadIndex',
    ]


import os
import unittest

from contextlib import ExitStack
from datetime import datetime, timezone
from resolver.gpg import SignatureError
from resolver.helpers import temporary_directory
from resolver.state import State
from resolver.tests.helpers import (
    copy, get_index, make_http_server, makedirs, setup_keyrings,
    setup_remote_keyring, sign, testable_configuration)


class TestIndex(unittest.TestCase):
    maxDiff = None

    def test_index_global(self):
        index = get_index('index_01.json')
        self.assertEqual(
            index.global_.generated_at,
            datetime(2013, 4, 29, 18, 45, 27, tzinfo=timezone.utc))

    def test_index_image_count(self):
        index = get_index('index_01.json')
        self.assertEqual(len(index.images), 0)
        index = get_index('index_02.json')
        self.assertEqual(len(index.images), 2)

    def test_image_20130300_full(self):
        index = get_index('sprint_nexus7_index_01.json')
        image = index.images[0]
        self.assertEqual(image.description, 'Some kind of daily build')
        self.assertEqual(image.type, 'full')
        self.assertEqual(image.version, 20130300)
        self.assertTrue(image.bootme)
        self.assertEqual(len(image.files), 3)
        # The first file is the device dependent image.  The second is the
        # device independent file, and the third is the version zip.
        dev, ind, ver = image.files
        self.assertEqual(dev.path, '/sprint/nexus7/nexus7-20130300.full.zip')
        self.assertEqual(dev.signature,
                         '/sprint/nexus7/nexus7-20130300.full.zip.asc')
        self.assertEqual(dev.checksum, 'abcdef0')
        self.assertEqual(dev.order, 0)
        self.assertEqual(dev.size, 0)
        # Let's not check the whole file, just a few useful bits.
        self.assertEqual(ind.checksum, 'abcdef1')
        self.assertEqual(ind.order, 0)
        self.assertEqual(ver.checksum, 'abcdef2')
        self.assertEqual(ver.order, 1)

    def test_image_20130500_minversion(self):
        # Some full images have a minimum version older than which they refuse
        # to upgrade from.
        index = get_index('sprint_nexus7_index_01.json')
        image = index.images[5]
        self.assertEqual(image.type, 'full')
        self.assertEqual(image.version, 20130500)
        self.assertTrue(image.bootme)
        self.assertEqual(image.minversion, 20130100)


class TestDownloadIndex(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        # Start the HTTPS server running.  Vend it out of a temporary
        # directory which we load up with the right files.
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    def _copysign(self, src, dst, keyring):
        server_dst = os.path.join(self._serverdir, dst)
        makedirs(os.path.dirname(server_dst))
        copy(src, self._serverdir, dst)
        sign(server_dst, keyring)

    @testable_configuration
    def test_load_index_good_path(self):
        # Load the index.json pointed to by the channels.json.  All signatures
        # validate correctly and there is no device keyring or blacklist.
        self._copysign(
            'channels_02.json', 'channels.json', 'image-signing.gpg')
        # index_10.json path B will win, with no bootme flags.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'image-signing.gpg')
        setup_keyrings()
        # Since there is no device keyring, we know that three state changes
        # will get us an index (blacklist -> channels -> index).
        state = State()
        for i in range(3):
            next(state)
        self.assertEqual(
            state.index.global_.generated_at,
            datetime(2013, 4, 29, 18, 45, 27, tzinfo=timezone.utc))
        self.assertEqual(
            state.index.images[0].files[1].checksum, 'bcd')

    @testable_configuration
    def test_load_index_with_device_keyring(self):
        # Here, the index.json file is signed with a device keyring.
        self._copysign(
            'channels_03.json', 'channels.json', 'image-signing.gpg')
        # index_10.json path B will win, with no bootme flags.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'device-signing.gpg')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-signing.gpg', dict(type='device'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        # Since there is a device keyring, four state changes are necessary to
        # get us an index (blacklist -> channels -> index).
        state = State()
        for i in range(4):
            next(state)
        self.assertEqual(
            state.index.global_.generated_at,
            datetime(2013, 4, 29, 18, 45, 27, tzinfo=timezone.utc))
        self.assertEqual(
            state.index.images[0].files[1].checksum, 'bcd')

    @testable_configuration
    def test_load_index_with_device_keyring_and_signing_key(self):
        # Here, the index.json file is signed with the image signing keyring,
        # even though there is a device key.  That's fine.
        self._copysign(
            'channels_03.json', 'channels.json', 'image-signing.gpg')
        # index_10.json path B will win, with no bootme flags.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'image-signing.gpg')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-signing.gpg', dict(type='device'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        # Since there is a device keyring, four state changes are necessary to
        # get us an index (blacklist -> channels -> index).
        state = State()
        for i in range(4):
            next(state)
        self.assertEqual(
            state.index.global_.generated_at,
            datetime(2013, 4, 29, 18, 45, 27, tzinfo=timezone.utc))
        self.assertEqual(
            state.index.images[0].files[1].checksum, 'bcd')

    @testable_configuration
    def test_load_index_with_bad_keyring(self):
        # Here, the index.json file is signed with a defective device keyring.
        self._copysign(
            'channels_03.json', 'channels.json', 'image-signing.gpg')
        # This will be signed by a keyring that is not the device keyring.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'spare.gpg')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-signing.gpg', dict(type='device'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        # Since there is a device keyring, four state changes are necessary to
        # get us an index (blacklist -> channels -> index).
        state = State()
        for i in range(3):
            next(state)
        self.assertRaises(SignatureError, next, state)

    @testable_configuration
    def test_load_index_with_blacklist(self):
        # Here, we've blacklisted the device key.
        self._copysign(
            'channels_03.json', 'channels.json', 'image-signing.gpg')
        # This will be signed by a keyring that is not the device keyring.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'device-signing.gpg')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-signing.gpg', dict(type='device'),
            os.path.join(self._serverdir, 'stable', 'nexus7', 'device.tar.xz'))
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        # Since there is a device keyring, four state changes are necessary to
        # get us an index (blacklist -> channels -> index).
        state = State()
        for i in range(3):
            next(state)
        self.assertRaises(SignatureError, next, state)

    @testable_configuration
    def test_missing_channel(self):
        # The system's channel does not exist.
        self._copysign(
            'channels_04.json', 'channels.json', 'image-signing.gpg')
        # index_10.json path B will win, with no bootme flags.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'image-signing.gpg')
        setup_keyrings()
        # Our channel (stable) isn't in the channels.json file, so there's
        # nothing to do.  Running the state machine to its conclusion leaves
        # us with no index file.
        state = State()
        list(state)
        # There really is nothing left to do.
        self.assertIsNone(state.index)

    @testable_configuration
    def test_missing_device(self):
        # The system's device does not exist.
        self._copysign(
            'channels_05.json', 'channels.json', 'image-signing.gpg')
        # index_10.json path B will win, with no bootme flags.
        self._copysign(
            'index_10.json', 'stable/nexus7/index.json', 'image-signing.gpg')
        setup_keyrings()
        # Our device (nexus7) isn't in the channels.json file, so there's
        # nothing to do.  Running the state machine to its conclusion leaves
        # us with no index file.
        state = State()
        list(state)
        # There really is nothing left to do.
        self.assertIsNone(state.index)
