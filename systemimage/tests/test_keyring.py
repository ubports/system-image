# Copyright (C) 2013-2016 Canonical Ltd.
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

"""Test downloading and unpacking a keyring."""


__all__ = [
    'TestKeyring',
    ]


import os
import hashlib
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from systemimage.config import config
from systemimage.gpg import Context, SignatureError
from systemimage.helpers import temporary_directory
from systemimage.keyring import KeyringError, get_keyring
from systemimage.testing.helpers import (
    configuration, make_http_server, setup_keyring_txz, setup_keyrings)
from systemimage.testing.nose import SystemImagePlugin


class TestKeyring(unittest.TestCase):
    """Test downloading and unpacking a keyring."""

    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._stack = ExitStack()
        try:
            self._serverdir = self._stack.enter_context(
                temporary_directory())
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_good_path(self):
        # Everything checks out, with the simplest possible keyring.json.
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg', dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        get_keyring('image-master', 'gpg/image-master.tar.xz',
                    'archive-master')
        with Context(config.gpg.archive_master) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))

    @configuration
    def test_good_path_full_json(self):
        # Everything checks out, with a fully loaded keyring.json file.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg',
            dict(type='image-master',
                 expiry=next_year.timestamp(), model='nexus7'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        get_keyring('image-master', 'gpg/image-master.tar.xz',
                    'archive-master')
        with Context(config.gpg.archive_master) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))

    @configuration
    def test_good_path_model(self):
        # Everything checks out with the model specified.
        setup_keyrings()
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg',
            dict(type='image-master', model='nexus7'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        get_keyring('image-master', 'gpg/image-master.tar.xz',
                    'archive-master')
        with Context(config.gpg.archive_master) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))

    @configuration
    def test_good_path_expiry(self):
        # Everything checks out, with the expiration date specified.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg',
            dict(type='image-master', expiry=next_year.timestamp()),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        get_keyring('image-master', 'gpg/image-master.tar.xz',
                    'archive-master')
        with Context(config.gpg.archive_master) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['289518ED3A0C4CFE975A0B32E0979A7EADE8E880']))

    @configuration
    def test_path_device_signing_keyring(self):
        # Get the device signing keyring.
        setup_keyrings('archive-master', 'image-master', 'image-signing')
        setup_keyring_txz(
            'spare.gpg', 'image-signing.gpg', dict(type='device-signing'),
            os.path.join(self._serverdir, 'gpg',
                         'stable', 'nexus7', 'device-signing.tar.xz'))
        url = 'gpg/{}/{}/device-signing.tar.xz'.format(
            config.channel, config.device)
        get_keyring('device-signing', url, 'image-signing')
        with Context(config.gpg.device_signing) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['94BE2CECF8A5AF9F3A10E2A6526B7016C3D2FB44']))

    @configuration
    def test_path_blacklist(self):
        # Get the blacklist keyring.
        setup_keyrings('archive-master', 'image-master')
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg/blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'.format(config.channel, config.device)
        get_keyring('blacklist', url, 'image-master')
        blacklist_path = os.path.join(config.tempdir, 'blacklist.tar.xz')
        with Context(blacklist_path) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['94BE2CECF8A5AF9F3A10E2A6526B7016C3D2FB44']))

    @configuration
    def test_tar_xz_file_missing(self):
        # If the tar.xz file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz')
        setup_keyrings()
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg', dict(type='blacklist'),
            tarxz_path)
        os.remove(tarxz_path)
        self.assertRaises(FileNotFoundError, get_keyring,
                          'blacklist', 'gpg/blacklist.tar.xz', 'image-master')

    @configuration
    def test_asc_file_missing(self):
        # If the tar.xz.asc file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz')
        setup_keyrings()
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg', dict(type='blacklist'),
            tarxz_path)
        os.remove(tarxz_path + '.asc')
        self.assertRaises(FileNotFoundError, get_keyring,
                          'blacklist', 'gpg/blacklist.tar.xz', 'image-master')

    @configuration
    def test_bad_signature(self):
        # Both files are downloaded, but the signature does not match the
        # image-master key.
        setup_keyrings()
        # Use the spare key as the blacklist, signed by itself.  Since this
        # won't match the image-signing key, the check will fail.
        server_path = os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz')
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='blacklist'), server_path)
        with self.assertRaises(SignatureError) as cm:
            get_keyring('blacklist', 'gpg/blacklist.tar.xz', 'image-master')
        error = cm.exception
        # The local file name will be keyring.tar.xz in the cache directory.
        basename = os.path.basename
        self.assertEqual(basename(error.data_path), 'keyring.tar.xz')
        self.assertEqual(basename(error.signature_path), 'keyring.tar.xz.asc')
        # The crafted blacklist.tar.xz file will have an unpredictable
        # checksum due to tarfile variablility.
        with open(server_path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).hexdigest()
        self.assertEqual(error.data_checksum, checksum)
        # The signature file's checksum is also unpredictable.
        with open(server_path + '.asc', 'rb') as fp:
            checksum = hashlib.md5(fp.read()).hexdigest()
        self.assertEqual(error.signature_checksum, checksum)

    @configuration
    def test_blacklisted_signature(self):
        # Normally, the signature would be good, except that the fingerprint
        # of the device signing key is blacklisted.
        setup_keyrings('archive-master', 'image-master')
        blacklist = os.path.join(config.tempdir, 'gpg', 'blacklist.tar.xz')
        # Blacklist the image-master keyring.
        setup_keyring_txz(
            'image-master.gpg', 'image-master.gpg', dict(type='blacklist'),
            blacklist)
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        # Now put an image-signing key on the server and attempt to download
        # it.  Because the image-master is blacklisted, this will fail.
        self.assertRaises(SignatureError, get_keyring,
                          'image-signing', 'gpg/image-signing.tar.xz',
                          'image-master', blacklist)

    @configuration
    def test_bad_json_type(self):
        # This type, while the signatures match, the keyring type in the
        # keyring.json file does not match.
        setup_keyrings()
        setup_keyring_txz(
            'device-signing.gpg', 'image-master.gpg', dict(type='master'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', 'gpg/blacklist.tar.xz', 'image-master')
        self.assertEqual(
            cm.exception.message,
            'keyring type mismatch; wanted: blacklist, got: master')

    @configuration
    def test_bad_json_model(self):
        # Similar to above, but with a non-matching model name.
        setup_keyrings()
        setup_keyring_txz(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus0'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', 'gpg/blacklist.tar.xz', 'image-master')
        self.assertEqual(
            cm.exception.message,
            'keyring model mismatch; wanted: nexus7, got: nexus0')

    @configuration
    def test_expired(self):
        # Similar to above, but the expiry key in the json names a utc
        # timestamp that has already elapsed.
        last_year = datetime.now(tz=timezone.utc) + timedelta(days=-365)
        setup_keyrings()
        setup_keyring_txz(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus7',
                 expiry=last_year.timestamp()),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', 'gpg/blacklist.tar.xz', 'image-master')
        self.assertEqual(
            cm.exception.message, 'expired keyring timestamp')

    @configuration
    def test_destination_image_master(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files.
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        asc_path = config.gpg.image_master + '.asc'
        self.assertFalse(os.path.exists(config.gpg.image_master))
        self.assertFalse(os.path.exists(asc_path))
        get_keyring(
            'image-master', 'gpg/image-master.tar.xz', 'archive-master')
        self.assertTrue(os.path.exists(config.gpg.image_master))
        self.assertTrue(os.path.exists(asc_path))
        with Context(config.gpg.archive_master) as ctx:
            self.assertTrue(ctx.verify(asc_path, config.gpg.image_master))

    @configuration
    def test_destination_image_signing(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files.
        setup_keyrings('archive-master', 'image-master')
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        asc_path = config.gpg.image_signing + '.asc'
        self.assertFalse(os.path.exists(config.gpg.image_signing))
        self.assertFalse(os.path.exists(asc_path))
        get_keyring(
            'image-signing', 'gpg/image-signing.tar.xz', 'image-master')
        self.assertTrue(os.path.exists(config.gpg.image_signing))
        self.assertTrue(os.path.exists(asc_path))
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(asc_path, config.gpg.image_signing))

    @configuration
    def test_destination_device_signing(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files.
        setup_keyrings('archive-master', 'image-master', 'image-signing')
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7',
                         'device-signing.tar.xz'))
        asc_path = config.gpg.device_signing + '.asc'
        self.assertFalse(os.path.exists(config.gpg.device_signing))
        self.assertFalse(os.path.exists(asc_path))
        get_keyring('device-signing',
                    'stable/nexus7/device-signing.tar.xz',
                    'image-signing')
        self.assertTrue(os.path.exists(config.gpg.device_signing))
        self.assertTrue(os.path.exists(asc_path))
        with Context(config.gpg.image_signing) as ctx:
            self.assertTrue(ctx.verify(asc_path, config.gpg.device_signing))

    @configuration
    def test_destination_blacklist(self):
        # Like above, but the blacklist files end up in the temporary
        # directory, since it's never persistent.
        setup_keyrings('archive-master', 'image-master')
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg',
            dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        txz_path = os.path.join(
            config.updater.data_partition, 'blacklist.tar.xz')
        asc_path = txz_path + '.asc'
        self.assertFalse(os.path.exists(txz_path))
        self.assertFalse(os.path.exists(asc_path))
        get_keyring('blacklist', 'gpg/blacklist.tar.xz', 'image-master')
        self.assertTrue(os.path.exists(txz_path))
        self.assertTrue(os.path.exists(asc_path))
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(asc_path, txz_path))
