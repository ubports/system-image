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
    'TestSignature',
    ]


import gpgme
import unittest

from pkg_resources import resource_filename
from resolver.gpg import Context


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
        with Context(self.pubkey_path) as ctx, \
             open(signature_path, 'rb') as sig_fp, \
             open(data_path, 'rb') as data_fp:
            results = ctx.import_result
            signatures = ctx.verify(sig_fp, data_fp, None)
        self.assertEqual(len(signatures), 1)
        signed_by = set(sig.fpr for sig in signatures)
        expected = set(imported[0] for imported in results.imports)
        self.assertEqual(expected, signed_by)
