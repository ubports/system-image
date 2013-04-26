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
import gpgme
import unittest

from pkg_resources import resource_filename
from resolver.gpg import Context, get_pubkey
from resolver.tests.helpers import make_http_server, make_temporary_cache


class TestSignature(unittest.TestCase):
    def setUp(self):
        self.pubkey_path = resource_filename(
            'resolver.tests.data', 'phablet.pubkey.asc')

    def test_import(self):
        with Context(self.pubkey_path) as ctx:
            results = ctx.import_result
        # Exactly one key was successfully imported.
        self.assertEqual(len(results.imports), 1)
        fingerprint, error, status = results.imports[0]
        self.assertEqual(fingerprint,
                         '9E28BB58D3EEAB91EB5B3C4011F731054CB57BF5')
        self.assertIsNone(error)
        self.assertEqual(status, gpgme.IMPORT_NEW)

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

    @classmethod
    def setUpClass(cls):
        # Start the HTTP server running.  Vend it out of our test data
        # directory, which will at least have a phablet.pubkey.asc file.
        pubkey_file = resource_filename('resolver.tests.data',
                                        'phablet.pubkey.asc')
        directory = os.path.dirname(pubkey_file)
        cls._stop = make_http_server(directory)

    @classmethod
    def tearDownClass(cls):
        # Stop the HTTP server.
        cls._stop()

    def setUp(self):
        self._cache = make_temporary_cache(self.addCleanup)

    def test_get_pubkey(self):
        # When the cache is empty, we'll download our pubkey.
        self.assertIsNone(self._cache.get_path('phablet.pubkey.asc'))
        pubkey = get_pubkey(self._cache)
        self.assertEqual(os.path.basename(pubkey), 'phablet.pubkey.asc')
        self.assertEqual(get_pubkey(self._cache), pubkey)
