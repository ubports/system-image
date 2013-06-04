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

"""Test downloading and unpacking the blacklist keyring."""


__all__ = [
    'TestBlacklist',
    ]


import os
import json
import shutil
import tarfile
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from resolver.blacklist import get_blacklist
from resolver.config import config
from resolver.gpg import Context
from resolver.helpers import temporary_directory
from resolver.tests.helpers import (
    copy, make_http_server, sign, testable_configuration)


class TestBlacklist(unittest.TestCase):
    """Test downloading and unpacking the blacklist keyring."""

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
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_asc_file_missing(self):
        # If the tar.xz.asc file cannot be downloaded, an error is raised.
        tarxz_path = os.path.join(config.system.tempdir, 'blacklist.tar.xz')
        with open(tarxz_path, 'wb'):
            pass
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_blacklist_bad_signature(self):
        # Both files are downloaded, but the signature does not match the
        # system image master key.
        #
        # We'll use the vendor signing keyring as the blacklist, but we'll
        # sign this with the archive master key so it won't match the expected
        # signature.  Start by copying the vendor signing key to a temporary
        # directory, then craft a json file for the keyring.  Tar those two
        # files up and sign them.
        with temporary_directory() as tmpdir:
            copy('vendor-signing.gpg', tmpdir, 'blacklist.gpg')
            json_path = os.path.join(tmpdir, 'blacklist.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(type='blacklist'), fp)
            tarxz_path = os.path.join(tmpdir, 'blacklist.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'blacklist.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            # Sign the file with the wrong key.
            sign(tarxz_path, 'archive-master.gpg')
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            gpg_path = os.path.join(self._serverdir, 'gpg')
            os.makedirs(gpg_path)
            shutil.copy(tarxz_path, gpg_path)
            shutil.copy(tarxz_path + '.asc', gpg_path)
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_blacklist_bad_json_type(self):
        # Similar to above, but while the signature matches, the keyring type
        # in the json file is not 'blacklist'.
        with temporary_directory() as tmpdir:
            copy('vendor-signing.gpg', tmpdir, 'blacklist.gpg')
            json_path = os.path.join(tmpdir, 'blacklist.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(type='master'), fp)
            tarxz_path = os.path.join(tmpdir, 'blacklist.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'blacklist.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            # Sign the file with the right key.
            sign(tarxz_path, 'image-master.gpg')
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            gpg_path = os.path.join(self._serverdir, 'gpg')
            os.makedirs(gpg_path)
            shutil.copy(tarxz_path, gpg_path)
            shutil.copy(tarxz_path + '.asc', gpg_path)
        copy('image-master.gpg', os.path.dirname(config.gpg.image_master))
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_blacklist_bad_json_model(self):
        # Similar to above, but with a non-matching model name.
        with temporary_directory() as tmpdir:
            copy('vendor-signing.gpg', tmpdir, 'blacklist.gpg')
            json_path = os.path.join(tmpdir, 'blacklist.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(type='blacklist',
                               model=config.system.device + '-foo'), fp)
            tarxz_path = os.path.join(tmpdir, 'blacklist.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'blacklist.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            # Sign the file with the right key.
            sign(tarxz_path, 'image-master.gpg')
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            gpg_path = os.path.join(self._serverdir, 'gpg')
            os.makedirs(gpg_path)
            shutil.copy(tarxz_path, gpg_path)
            shutil.copy(tarxz_path + '.asc', gpg_path)
        copy('image-master.gpg', os.path.dirname(config.gpg.image_master))
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_blacklist_expired(self):
        # Similar to above, but the expiry key in the json names a utc
        # timestamp that has already elapsed.
        last_year = datetime.now(tz=timezone.utc) + timedelta(days=-365)
        with temporary_directory() as tmpdir:
            copy('vendor-signing.gpg', tmpdir, 'blacklist.gpg')
            json_path = os.path.join(tmpdir, 'blacklist.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(type='blacklist',
                               model=config.system.device,
                               expiry=last_year.timestamp()), fp)
            tarxz_path = os.path.join(tmpdir, 'blacklist.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'blacklist.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            # Sign the file with the right key.
            sign(tarxz_path, 'image-master.gpg')
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            gpg_path = os.path.join(self._serverdir, 'gpg')
            os.makedirs(gpg_path)
            shutil.copy(tarxz_path, gpg_path)
            shutil.copy(tarxz_path + '.asc', gpg_path)
        copy('image-master.gpg', os.path.dirname(config.gpg.image_master))
        self.assertRaises(FileNotFoundError, get_blacklist)

    @testable_configuration
    def test_blacklist_good_path(self):
        # Everything checks out.
        next_year = datetime.now(tz=timezone.utc) + timedelta(days=365)
        with temporary_directory() as tmpdir:
            copy('vendor-signing.gpg', tmpdir, 'blacklist.gpg')
            json_path = os.path.join(tmpdir, 'blacklist.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(type='blacklist',
                               model=config.system.device,
                               expiry=next_year.timestamp()), fp)
            tarxz_path = os.path.join(tmpdir, 'blacklist.tar.xz')
            with tarfile.open(tarxz_path, 'w:xz') as tf:
                tf.add(os.path.join(tmpdir, 'blacklist.gpg'), 'keyring.gpg')
                tf.add(json_path, 'keyring.json')
            # Sign the file with the right key.
            sign(tarxz_path, 'image-master.gpg')
            # Copy the .tar.xz and .asc files to the proper directory under
            # the path the https server is vending them from.
            gpg_path = os.path.join(self._serverdir, 'gpg')
            os.makedirs(gpg_path)
            shutil.copy(tarxz_path, gpg_path)
            shutil.copy(tarxz_path + '.asc', gpg_path)
        copy('image-master.gpg', os.path.dirname(config.gpg.image_master))
        get_blacklist()
        with Context(config.gpg.blacklist) as ctx:
            self.assertEqual(ctx.fingerprints,
                             set(['C43D6575FDD935D2F9BC2A4669BC664FCB86D917']))
