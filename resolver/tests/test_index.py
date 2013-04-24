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
    ]


import unittest

from datetime import datetime, timezone
from operator import attrgetter
from resolver.tests.helpers import get_index


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.index = get_index('stable_nexus7_index_01.json')

    def test_index_bundles(self):
        self.assertEqual(len(self.index.bundles), 1)
        bundle = self.index.bundles[0]
        self.assertEqual(bundle.images.android, '20130301')
        self.assertEqual(bundle.images.ubuntu_rootfs, '20130301')
        self.assertEqual(bundle.version, '20130304')

    def test_index_global(self):
        self.assertEqual(self.index.global_.generated_at,
                         datetime(2013, 4, 11, 15, 1, 46, tzinfo=timezone.utc))

    def test_index_images(self):
        self.assertEqual(len(self.index.images), 4)
        # Sort the images by lexical order on the checksum string.
        images = sorted(self.index.images, key=attrgetter('checksum'))
        # The first image starts with 5a...
        self.assertEqual(images[0].checksum,
                         '5a37ba30664cde4ab245e337c12d16f8ad892278')
        self.assertEqual(images[0].content, 'ubuntu-rootfs')
        self.assertEqual(images[0].path,
                         '/stable/ubuntu/ubuntu-20130301.full.zip')
        self.assertEqual(images[0].size, 425039674)
        self.assertEqual(images[0].type, 'full')
        self.assertEqual(images[0].version, '20130301')
        self.assertRaises(AttributeError, getattr, images[0], 'base')
        # The second image starts with c5...
        self.assertEqual(images[1].checksum,
                         'c513dc5e4ed887d8c56e138386f68c8e33f93002')
        self.assertEqual(images[1].content, 'ubuntu-rootfs')
        self.assertEqual(images[1].path,
                         '/stable/ubuntu/ubuntu-20130300.full.zip')
        self.assertEqual(images[1].size, 423779219)
        self.assertEqual(images[1].type, 'full')
        self.assertEqual(images[1].version, '20130300')
        self.assertRaises(AttributeError, getattr, images[0], 'base')
        # The third image starts with ca...
        self.assertEqual(images[2].checksum,
                         'ca124997894fa5be76f42a9404f6375d3aca1664')
        self.assertEqual(images[2].base, '20130300')
        self.assertEqual(images[2].content, 'ubuntu-rootfs')
        self.assertEqual(images[2].path,
                         '/stable/ubuntu/ubuntu-20130301.delta-20130300.zip')
        self.assertEqual(images[2].size, 24320692)
        self.assertEqual(images[2].type, 'delta')
        self.assertEqual(images[2].version, '20130301')
        # The fourth image starts with da...
        self.assertEqual(images[3].checksum,
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(images[3].base, '20130300')
        self.assertEqual(images[3].content, 'android')
        self.assertEqual(images[3].path,
                         '/stable/nexus7/android-20130301.delta-20130300.zip')
        self.assertEqual(images[3].size, 0)
        self.assertEqual(images[3].type, 'delta')
        self.assertEqual(images[3].version, '20130301')
