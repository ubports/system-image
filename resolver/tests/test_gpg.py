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


    'TestGetPubkey',
    'TestSignature',
    ]


import os
import unittest

from pkg_resources import resource_filename
from resolver.config import config
from resolver.gpg import Context, get_pubkey
from resolver.tests.helpers import (
    copy, make_http_server, testable_configuration)


class TestKeyrings(unittest.TestCase):
    """Test various attributes of the 5 defined keyrings."""

    @testable_configuration
    def test_archive_master(self):
        # The archive master keyring contains the master key.  This a
        # persistent, mandatory, shipped, non-expiring key.
        copy('archive-master.gpg', config.system.tempdir)
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

    @testable_configuration
    def test_archive_and_image_masters(self):
        # There is also a system image master key which is also persistent,
        # mandatory, shipped, and non-expiring.  It should never need
        # changing, but it is possible to do so if it gets compromised.
        copy('archive-master.gpg', config.system.tempdir)
        copy('image-master.gpg', config.system.tempdir)
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

    @testable_configuration
    def test_archive_image_masters_image_signing(self):
        # In addition to the above, there is also a image signing key which is
        # generally what downloaded files are signed with.  This key is also
        # persistent, mandatory, and shipped.  It is updated regularly and
        # expires every two years.
        copy('archive-master.gpg', config.system.tempdir)
        copy('image-master.gpg', config.system.tempdir)
        copy('image-signing.gpg', config.system.tempdir)
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

    @testable_configuration
    def test_archive_image_masters_image_device_signing(self):
        # In addition to the above, there is also a device/vendor signing key
        # which downloaded files can also be signed with.  This key is also
        # persistent, mandatory, and shipped.  It is optional, so doesn't need
        # to exist, but it is also updated regularly and expires after one
        # month.
        copy('archive-master.gpg', config.system.tempdir)
        copy('image-master.gpg', config.system.tempdir)
        copy('image-signing.gpg', config.system.tempdir)
        copy('vendor-signing.gpg', config.system.tempdir)
        keyrings = [
            config.gpg.archive_master,
            config.gpg.image_master,
            config.gpg.image_signing,
            config.gpg.vendor_signing,
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
