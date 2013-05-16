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
    'TestGetPubkey',
    'TestSignature',
    ]


import os
import unittest

from pkg_resources import resource_filename
from resolver.config import config
from resolver.gpg import Context, get_pubkey
from resolver.tests.helpers import make_http_server, testable_configuration


class TestSignature(unittest.TestCase):
    def setUp(self):
        self.pubkey_path = resource_filename(
            'resolver.tests.data', 'phablet.pubkey.asc')

    def test_import(self):
        with Context(self.pubkey_path) as ctx:
            results = ctx.import_result
        # Exactly one key was successfully imported.
        self.assertEqual(results.count, 1)
        self.assertEqual(len(results.fingerprints), 1)
        self.assertEqual(results.fingerprints[0],
                         '253E67218CF5327B4F965F3260D858F208B776C3')
        # One new key was imported.
        self.assertEqual(results.imported, 1)

    def test_channel_signature(self):
        signature_path = resource_filename(
            'resolver.tests.data', 'channels_01.json.asc')
        data_path = resource_filename(
            'resolver.tests.data', 'channels_01.json')
        with Context(self.pubkey_path) as ctx:
            self.assertTrue(ctx.verify(signature_path, data_path))

    def test_channel_bad_signature(self):
        # The fingerprints in the signature do not match.
        signature_path = resource_filename(
            'resolver.tests.data', 'channels_01.json.bad.asc')
        data_path = resource_filename(
            'resolver.tests.data', 'channels_01.json')
        with Context(self.pubkey_path) as ctx:
            self.assertFalse(ctx.verify(signature_path, data_path))

    def test_channel_no_signature(self):
        # The signature file isn't even a signature file.
        signature_path = resource_filename(
            'resolver.tests.data', 'config_01.ini')
        data_path = resource_filename(
            'resolver.tests.data', 'channels_01.json')
        with Context(self.pubkey_path) as ctx:
            self.assertFalse(ctx.verify(signature_path, data_path))


class TestGetPubkey(unittest.TestCase):
    """Test downloading and caching the public key."""

    def setUp(self):
        self._directory = os.path.dirname(resource_filename(
            'resolver.tests.data', 'phablet.pubkey.asc'))

    @testable_configuration
    def test_get_pubkey(self):
        with make_http_server(
                self._directory, 8943, 'cert.pem', 'key.pem',
                # The following isn't strictly necessary, since its default.
                selfsign=True):
            self.assertEqual(
                get_pubkey(),
                os.path.join(config.system.tempdir, 'phablet.pubkey.asc'))
