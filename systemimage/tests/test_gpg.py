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

"""Test that we can verify GPG signatures."""

__all__ = [
    'TestKeyrings',
    'TestSignature',
    ]


import os
import unittest

from contextlib import ExitStack
from systemimage.config import config
from systemimage.gpg import Context
from systemimage.helpers import temporary_directory
from systemimage.testing.helpers import (
    configuration, copy, setup_keyring_txz, setup_keyrings, sign)


class TestKeyrings(unittest.TestCase):
    """Test various attributes of the 5 defined keyrings."""

    @configuration
    def test_archive_master(self):
        # The archive master keyring contains the master key.  This a
        # persistent, mandatory, shipped, non-expiring key.
        setup_keyrings()
        with Context(config.gpg.archive_master) as ctx:
            # There is only one key in the master keyring.
            self.assertEqual(
                ctx.fingerprints,
                set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))
            self.assertEqual(
                ctx.key_ids,
                set(['E0979A7EADE8E880']))
            # Here is some useful information about the master key.
            self.assertEqual(len(ctx.keys), 1)
            master = ctx.keys[0]
            self.assertEqual(
                master['uids'],
                ['Ubuntu Archive Master Signing Key (TEST) '
                 '<ftpmaster@ubuntu.example.com>'])

    @configuration
    def test_archive_master_cached(self):
        # Unpacking the .tar.xz caches the .gpg file contained within, so it
        # only needs to be unpacked once.  Test that the cached .gpg file is
        # used by not actually having a .tar.xz file.
        copy('archive-master.gpg', config.tempdir)
        self.assertFalse(os.path.exists(config.gpg.archive_master))
        with Context(config.gpg.archive_master) as ctx:
            self.assertEqual(
                ctx.fingerprints,
                set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))

    @configuration
    def test_archive_and_image_masters(self):
        # There is also a system image master key which is also persistent,
        # mandatory, shipped, and non-expiring.  It should never need
        # changing, but it is possible to do so if it gets compromised.
        setup_keyrings()
        keyrings = [
            config.gpg.archive_master,
            config.gpg.image_master,
            ]
        with Context(*keyrings) as ctx:
            # The context now knows about two keys.
            self.assertEqual(
                ctx.fingerprints,
                set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880',
                     '47691DEF271FB2B1FD3364513BC6AF1818E7F5FB']))
            self.assertEqual(
                ctx.key_ids,
                set(['E0979A7EADE8E880', '3BC6AF1818E7F5FB']))
            # Here are all the available uids.
            uids = []
            for key in ctx.keys:
                uids.extend(key['uids'])
            self.assertEqual(uids, [
                'Ubuntu Archive Master Signing Key (TEST) '
                    '<ftpmaster@ubuntu.example.com>',
                'Ubuntu System Image Master Signing Key (TEST) '
                    '<system-image@ubuntu.example.com>'
                ])

    @configuration
    def test_archive_image_masters_image_signing(self):
        # In addition to the above, there is also a image signing key which is
        # generally what downloaded files are signed with.  This key is also
        # persistent, mandatory, and shipped.  It is updated regularly and
        # expires every two years.
        setup_keyrings()
        keyrings = [
            config.gpg.archive_master,
            config.gpg.image_master,
            config.gpg.image_signing,
            ]
        with Context(*keyrings) as ctx:
            # The context now knows about two keys.
            self.assertEqual(
                ctx.fingerprints,
                set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880',
                     '47691DEF271FB2B1FD3364513BC6AF1818E7F5FB',
                     'C5E39F07D159687BA3E82BD15A0DE8A4F1F1846F']))
            self.assertEqual(
                ctx.key_ids,
                set(['E0979A7EADE8E880',
                     '3BC6AF1818E7F5FB',
                     '5A0DE8A4F1F1846F']))
            # Here are all the available uids.
            uids = []
            for key in ctx.keys:
                uids.extend(key['uids'])
            self.assertEqual(uids, [
                'Ubuntu Archive Master Signing Key (TEST) '
                    '<ftpmaster@ubuntu.example.com>',
                'Ubuntu System Image Master Signing Key (TEST) '
                    '<system-image@ubuntu.example.com>',
                'Ubuntu System Image Signing Key (TEST) '
                    '<system-image@ubuntu.example.com>',
                ])

    @configuration
    def test_archive_image_masters_image_device_signing(self):
        # In addition to the above, there is also a device signing key which
        # downloaded files can also be signed with.  This key is also
        # persistent, mandatory, and shipped.  It is optional, so doesn't need
        # to exist, but it is also updated regularly and expires after one
        # month.
        setup_keyrings()
        keyrings = [
            config.gpg.archive_master,
            config.gpg.image_master,
            config.gpg.image_signing,
            config.gpg.device_signing,
            ]
        with Context(*keyrings) as ctx:
            # The context now knows about two keys.
            self.assertEqual(
                ctx.fingerprints,
                set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880',
                     '47691DEF271FB2B1FD3364513BC6AF1818E7F5FB',
                     'C5E39F07D159687BA3E82BD15A0DE8A4F1F1846F',
                     'C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))
            self.assertEqual(
                ctx.key_ids,
                set(['E0979A7EADE8E880',
                     '3BC6AF1818E7F5FB',
                     '5A0DE8A4F1F1846F',
                     '69BC664FCB86D917']))
            # Here are all the available uids.
            uids = []
            for key in ctx.keys:
                uids.extend(key['uids'])
            self.assertEqual(uids, [
                'Ubuntu Archive Master Signing Key (TEST) '
                    '<ftpmaster@ubuntu.example.com>',
                'Ubuntu System Image Master Signing Key (TEST) '
                    '<system-image@ubuntu.example.com>',
                'Ubuntu System Image Signing Key (TEST) '
                    '<system-image@ubuntu.example.com>',
                'Acme Phones, LLC Image Signing Key (TEST) '
                    '<system-image@acme-phones.example.com>',
                ])

    @configuration
    def test_missing_keyring(self):
        # The keyring file does not exist.
        self.assertRaises(
            FileNotFoundError, Context,
            os.path.join(config.tempdir, 'does-not-exist.tar.xz'))

    @configuration
    def test_missing_blacklist(self):
        # The blacklist file does not exist.
        blacklist = os.path.join(config.tempdir, 'no-blacklist.tar.xz')
        self.assertRaises(
            FileNotFoundError, Context, blacklist=blacklist)


class TestSignature(unittest.TestCase):
    def setUp(self):
        self._stack = ExitStack()
        self._tmpdir = self._stack.enter_context(temporary_directory())

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_good_signature(self):
        # We have a channels.json file signed with the imaging signing key, as
        # would be the case in production.  The signature will match a context
        # loaded with the public key.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        sign(channels_json, 'image-signing.gpg')
        with temporary_directory() as tmpdir:
            keyring = os.path.join(tmpdir, 'image-signing.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), keyring)
            with Context(keyring) as ctx:
                self.assertTrue(
                    ctx.verify(channels_json + '.asc', channels_json))

    @configuration
    def test_bad_signature(self):
        # In this case, the file is signed with the device key, so it will not
        # verify against the image signing key.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        sign(channels_json, 'device-signing.gpg')
        # Verify the signature with the pubkey.
        with temporary_directory() as tmpdir:
            dst = os.path.join(tmpdir, 'image-signing.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), dst)
            with Context(dst) as ctx:
                self.assertFalse(
                    ctx.verify(channels_json + '.asc', channels_json))

    @configuration
    def test_good_signature_with_multiple_keyrings(self):
        # Like above, the file is signed with the device key, but this time we
        # include both the image signing and device signing pubkeys.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        sign(channels_json, 'device-signing.gpg')
        with temporary_directory() as tmpdir:
            keyring_1 = os.path.join(tmpdir, 'image-signing.tar.xz')
            keyring_2 = os.path.join(tmpdir, 'device-signing.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), keyring_1)
            setup_keyring_txz('device-signing.gpg', 'image-signing.gpg',
                              dict(type='device-signing'), keyring_2)
            with Context(keyring_1, keyring_2) as ctx:
                self.assertTrue(
                    ctx.verify(channels_json + '.asc', channels_json))

    @configuration
    def test_bad_signature_with_multiple_keyrings(self):
        # The file is signed with the image master key, but it won't verify
        # against the image signing and device signing pubkeys.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        sign(channels_json, 'image-master.gpg')
        # Verify the signature with the pubkey.
        with temporary_directory() as tmpdir:
            keyring_1 = os.path.join(tmpdir, 'image-signing.tar.xz')
            keyring_2 = os.path.join(tmpdir, 'device-signing.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), keyring_1)
            setup_keyring_txz('device-signing.gpg', 'image-signing.gpg',
                              dict(type='device-signing'), keyring_2)
            with Context(keyring_1, keyring_2) as ctx:
                self.assertFalse(
                    ctx.verify(channels_json + '.asc', channels_json))

    @configuration
    def test_bad_not_even_a_signature(self):
        # The signature file isn't even a signature file.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        copy('channels_01.json', self._tmpdir, dst=channels_json + '.asc')
        with temporary_directory() as tmpdir:
            dst = os.path.join(tmpdir, 'device-signing.tar.xz')
            setup_keyring_txz('device-signing.gpg', 'image-signing.gpg',
                              dict(type='device-signing'),
                              dst)
            with Context(dst) as ctx:
                self.assertFalse(ctx.verify(
                    channels_json + '.asc', channels_json))

    @configuration
    def test_good_signature_not_in_blacklist(self):
        # We sign the file with the device signing key, and verify it against
        # the imaging signing and device signing keyrings.  In this case
        # though, we also have a blacklist keyring, but none of the keyids in
        # the blacklist match the keyid that the file was signed with.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst='channels.json')
        sign(channels_json, 'device-signing.gpg')
        # Verify the signature with the pubkey.
        with temporary_directory() as tmpdir:
            keyring_1 = os.path.join(tmpdir, 'image-signing.tar.xz')
            keyring_2 = os.path.join(tmpdir, 'device-signing.tar.xz')
            blacklist = os.path.join(tmpdir, 'blacklist.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), keyring_1)
            setup_keyring_txz('device-signing.gpg', 'image-signing.gpg',
                              dict(type='device-signing'), keyring_2)
            setup_keyring_txz('spare.gpg', 'image-master.gpg',
                              dict(type='blacklist'), blacklist)
            with Context(keyring_1, keyring_2, blacklist=blacklist) as ctx:
                self.assertTrue(
                    ctx.verify(channels_json + '.asc', channels_json))

    @configuration
    def test_bad_signature_in_blacklist(self):
        # Like above, but we put the device signing key id in the blacklist.
        channels_json = os.path.join(self._tmpdir, 'channels.json')
        copy('channels_01.json', self._tmpdir, dst=channels_json)
        sign(channels_json, 'device-signing.gpg')
        # Verify the signature with the pubkey.
        with temporary_directory() as tmpdir:
            keyring_1 = os.path.join(tmpdir, 'image-signing.tar.xz')
            keyring_2 = os.path.join(tmpdir, 'device-signing.tar.xz')
            blacklist = os.path.join(tmpdir, 'blacklist.tar.xz')
            setup_keyring_txz('image-signing.gpg', 'image-master.gpg',
                              dict(type='image-signing'), keyring_1)
            setup_keyring_txz('device-signing.gpg', 'image-signing.gpg',
                              dict(type='device-signing'), keyring_2)
            # We're letting the device signing pubkey stand in for a blacklist.
            setup_keyring_txz('device-signing.gpg', 'image-master.gpg',
                              dict(type='blacklist'), blacklist)
            with Context(keyring_1, keyring_2, blacklist=blacklist) as ctx:
                self.assertFalse(
                    ctx.verify(channels_json + '.asc', channels_json))
