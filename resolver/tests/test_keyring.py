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
import json
import shutil
import tarfile
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from resolver.config import config
from resolver.gpg import Context
from resolver.helpers import temporary_directory
from resolver.keyring import KeyringError, get_keyring
from resolver.tests.helpers import (
    copy, make_http_server, setup_keyrings, sign, testable_configuration)


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
    def test_tar_xz_file_missing(self):
        # If the tar.xz file cannot be downloaded, an error is raised.
        self.assertRaises(FileNotFoundError, get_keyring, 'blacklist')

    @testable_configuration
    def test_asc_file_missing(self):
        # If the tar.xz.asc file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(config.system.tempdir, 'blacklist.tar.xz')
        with open(tarxz_path, 'wb'):
            pass
        self.assertRaises(FileNotFoundError, get_keyring, 'blacklist')

    def _setup_server(self, keyring_src, signing_keyring, json_data, dst):
        with temporary_directory() as tmpdir:
            copy(keyring_src, tmpdir, 'keyring.gpg')
            json_path = os.path.join(tmpdir, 'keyring.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(json_data, fp)
            # Tar up the .gpg and .json files into a .tar.xz file.
            tarxz_path = os.path.join(tmpdir, 'keyring.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'keyring.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            sign(tarxz_path, signing_keyring)
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            server_path = os.path.join(self._serverdir, 'gpg', dst + '.tar.xz')
            os.makedirs(os.path.dirname(server_path))
            shutil.copy(tarxz_path, server_path)
            shutil.copy(tarxz_path + '.asc', server_path + '.asc')

    @testable_configuration
    def test_keyring_bad_signature(self):
        # Both files are downloaded, but the signature does not match the
        # system image master key.
        #
        # We'll use the vendor signing keyring as the blacklist, but we'll
        # sign this with the archive master key so it won't match the expected
        # signature.
        self._setup_server('vendor-signing.gpg', 'archive-master.gpg',
                           dict(type='blacklist'), 'blacklist')
        setup_keyrings()
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist')
        self.assertEqual(cm.exception.message, 'bad signature')

    @testable_configuration
    def test_keyring_blacklisted_signature(self):
        # Normally, the signature would be good, except that the fingerprint
        # of the signing key is blacklisted.
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist'),
                           'blacklist')
        setup_keyrings()
        copy('image-master.gpg',
             os.path.dirname(config.gpg.blacklist),
             os.path.basename(config.gpg.blacklist))
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist')
        self.assertEqual(cm.exception.message, 'bad signature')

    @testable_configuration
    def test_keyring_bad_json_type(self):
        # Similar to above, but while the signature matches, the keyring type
        # in the json file is not 'blacklist'.
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='master'), 'blacklist')
        setup_keyrings()
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist')
        self.assertEqual(
            cm.exception.message,
            'keyring type mismatch; wanted: blacklist, got: master')

    @testable_configuration
    def test_keyring_bad_json_model(self):
        # Similar to above, but with a non-matching model name.
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist', model='nexus0'),
                           'blacklist')
        setup_keyrings()
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist')
        self.assertEqual(
            cm.exception.message,
            'keyring model mismatch; wanted: nexus7, got: nexus0')

    @testable_configuration
    def test_keyring_expired(self):
        # Similar to above, but the expiry key in the json names a utc
        # timestamp that has already elapsed.
        last_year = datetime.now(tz=timezone.utc) + timedelta(days=-365)
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist', model='nexus7',
                                expiry=last_year.timestamp()),
                           'blacklist')
        setup_keyrings()
        with self.assertRaises(KeyringError) as cm:
            get_keyring('blacklist')
        self.assertEqual(
            cm.exception.message, 'expired keyring timestamp')

    @testable_configuration
    def test_keyring_good_path(self):
        # Everything checks out.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist', model='nexus7',
                                expiry=next_year.timestamp()),
                           'blacklist')
        setup_keyrings()
        get_keyring('blacklist')
        with Context(config.gpg.blacklist) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_expiration_good_path(self):
        # Everything checks out.
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist', model='nexus7'),
                           'blacklist')
        setup_keyrings()
        get_keyring('blacklist')
        with Context(config.gpg.blacklist) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_model_good_path(self):
        # Everything checks out.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist',
                                expiry=next_year.timestamp()),
                           'blacklist')
        setup_keyrings()
        get_keyring('blacklist')
        with Context(config.gpg.blacklist) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_keyring_no_model_or_expiration_good_path(self):
        # Everything checks out.
        self._setup_server('vendor-signing.gpg', 'image-master.gpg',
                           dict(type='blacklist'),
                           'blacklist')
        setup_keyrings()
        get_keyring('blacklist')
        with Context(config.gpg.blacklist) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))

    @testable_configuration
    def test_good_path_vendor_keyring(self):
        # Make sure there are no hardcoded references to the blacklist keyring.
        self._setup_server('spare.gpg', 'image-signing.gpg',
                           dict(type='device'),
                           'stable/nexus7/device')
        setup_keyrings()
        get_keyring('device')
        with Context(config.gpg.vendor_signing) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['94BE2CECF8A5AF9F3A10E2A6526B7016C3D2FB44']))
