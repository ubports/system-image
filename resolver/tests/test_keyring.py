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

"""Test downloading and unpacking a keyring."""


__all__ = [
    'TestKeyring',
    ]


import os
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from resolver.config import config
from resolver.gpg import Context, SignatureError
from resolver.helpers import temporary_directory
from resolver.keyring import KeyringError, get_keyring
from resolver.tests.helpers import (
    make_http_server, setup_keyrings, setup_remote_keyring, test_data_path,
    testable_configuration)


class TestKeyring(unittest.TestCase):
    """Test downloading and unpacking a keyring."""

    maxDiff = None

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

    @testable_configuration
    def test_keyring_good_path(self):
        # Everything checks out.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus7',
                 expiry=next_year.timestamp()),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        with Context(dst) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_expiration_good_path(self):
        # Everything checks out.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus7'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        with Context(dst) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_model_good_path(self):
        # Everything checks out.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', expiry=next_year.timestamp()),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        with Context(dst) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_model_or_expiration_good_path(self):
        # Everything checks out.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        with Context(dst) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_good_path_device_keyring(self):
        # Make sure there are no hardcoded references to the blacklist keyring.
        setup_keyrings()
        setup_remote_keyring(
            'spare.gpg', 'image-signing.gpg', dict(type='device-signing'),
            os.path.join(
                self._serverdir, 'gpg', 'stable', 'nexus7', 'device.tar.xz'))
        url = 'gpg/{}/{}/device.tar.xz'.format(
            config.system.channel, config.system.device)
        dst = get_keyring('device-signing', url, url + '.asc', 'image_signing')
        with Context(dst) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['94BE2CECF8A5AF9F3A10E2A6526B7016C3D2FB44']))

    @testable_configuration
    def test_tar_xz_file_missing(self):
        # If the tar.xz file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'archive-master.gpg', dict(type='blacklist'),
            tarxz_path)
        os.remove(tarxz_path)
        url = 'gpg/blacklist.tar.xz'
        self.assertRaises(FileNotFoundError, get_keyring,
                          'blacklist', url, url + '.asc', 'image_master')

    @testable_configuration
    def test_asc_file_missing(self):
        # If the tar.xz.asc file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz')
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'archive-master.gpg', dict(type='blacklist'),
            tarxz_path)
        os.remove(tarxz_path + '.asc')
        url = 'gpg/blacklist.tar.xz'
        self.assertRaises(FileNotFoundError, get_keyring,
                          'blacklist', url, url + '.asc', 'image_master')

    @testable_configuration
    def test_keyring_bad_signature(self):
        # Both files are downloaded, but the signature does not match the
        # system image master key.
        #
        # We'll use the device signing keyring as the blacklist, but we'll
        # sign this with the archive master key so it won't match the expected
        # signature.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'archive-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        self.assertRaises(SignatureError, get_keyring,
                          'blacklist', url, url + '.asc', 'image_master')

    @testable_configuration
    def test_keyring_blacklisted_signature(self):
        # Normally, the signature would be good, except that the fingerprint
        # of the signing key is blacklisted.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        self.assertRaises(SignatureError, get_keyring,
                          'blacklist', url, url + '.asc', 'image_master',
                          test_data_path('image-master.gpg'))

    @testable_configuration
    def test_keyring_bad_json_type(self):
        # Similar to above, but while the signature matches, the keyring type
        # in the json file is not 'blacklist'.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg', dict(type='master'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', url, url + '.asc', 'image_master')
        self.assertEqual(
            cm.exception.message,
            'keyring type mismatch; wanted: blacklist, got: master')

    @testable_configuration
    def test_keyring_bad_json_model(self):
        # Similar to above, but with a non-matching model name.
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus0'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', url, url + '.asc', 'image_master')
        self.assertEqual(
            cm.exception.message,
            'keyring model mismatch; wanted: nexus7, got: nexus0')

    @testable_configuration
    def test_keyring_expired(self):
        # Similar to above, but the expiry key in the json names a utc
        # timestamp that has already elapsed.
        last_year = datetime.now(tz=timezone.utc) + timedelta(days=-365)
        setup_keyrings()
        setup_remote_keyring(
            'device-signing.gpg', 'image-master.gpg',
            dict(type='blacklist', model='nexus7',
                 expiry=last_year.timestamp()),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        url = 'gpg/blacklist.tar.xz'
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist', url, url + '.asc', 'image_master')
        self.assertEqual(
            cm.exception.message, 'expired keyring timestamp')

    @testable_configuration
    def test_keyring_destination_image_master(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files for access by the updater.
        setup_keyrings('archive_master')
        setup_remote_keyring(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        get_keyring('image-master',
                    'gpg/image-master.tar.xz', 'gpg/image-master.tar.xz.asc',
                    'archive_master')
        tarxz_path = os.path.join(
            config.updater.cache_partition, 'image-master.tar.xz')
        ascxz_path = os.path.join(
            config.updater.cache_partition, 'image-master.tar.xz.asc')
        self.assertTrue(os.path.exists(tarxz_path))
        self.assertTrue(os.path.exists(ascxz_path))
        with Context(config.gpg.archive_master) as ctx:
            self.assertTrue(ctx.verify(ascxz_path, tarxz_path))

    @testable_configuration
    def test_keyring_destination_image_signing(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files for access by the updater.
        setup_keyrings('archive_master', 'image_master')
        setup_remote_keyring(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        get_keyring('image-signing',
                    'gpg/image-signing.tar.xz', 'gpg/image-signing.tar.xz.asc',
                    'image_master')
        tarxz_path = os.path.join(
            config.updater.cache_partition, 'image-signing.tar.xz')
        ascxz_path = os.path.join(
            config.updater.cache_partition, 'image-signing.tar.xz.asc')
        self.assertTrue(os.path.exists(tarxz_path))
        self.assertTrue(os.path.exists(ascxz_path))
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(ascxz_path, tarxz_path))

    @testable_configuration
    def test_keyring_destination_device_signing(self):
        # When a keyring is downloaded, we preserve its .tar.xz and
        # .tar.xz.asc files for access by the updater.
        setup_keyrings('archive_master', 'image_master', 'image_signing')
        setup_remote_keyring(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, 'stable', 'nexus7',
                         'device-signing.tar.xz'))
        get_keyring('device-signing',
                    'stable/nexus7/device-signing.tar.xz',
                    'stable//nexus7/device-signing.tar.xz.asc',
                    'image_signing')
        tarxz_path = os.path.join(
            config.updater.cache_partition, 'device-signing.tar.xz')
        ascxz_path = os.path.join(
            config.updater.cache_partition, 'device-signing.tar.xz.asc')
        self.assertTrue(os.path.exists(tarxz_path))
        self.assertTrue(os.path.exists(ascxz_path))
        with Context(config.gpg.image_signing) as ctx:
            self.assertTrue(ctx.verify(ascxz_path, tarxz_path))

    @testable_configuration
    def test_keyring_destination_blacklist(self):
        # Like above, but the blacklist files end up in the data partition
        # instead of the cache partition.
        setup_keyrings('archive_master', 'image_master')
        setup_remote_keyring(
            'spare.gpg', 'image-master.gpg',
            dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        get_keyring('blacklist',
                    'gpg/blacklist.tar.xz', 'gpg/blacklist.tar.xz.asc',
                    'image_master')
        tarxz_path = os.path.join(
            config.updater.data_partition, 'blacklist.tar.xz')
        ascxz_path = os.path.join(
            config.updater.data_partition, 'blacklist.tar.xz.asc')
        self.assertTrue(os.path.exists(tarxz_path))
        self.assertTrue(os.path.exists(ascxz_path))
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(ascxz_path, tarxz_path))
