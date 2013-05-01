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
from resolver.tests.helpers import get_index


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.index = get_index('sprint_nexus7_index_01.json')

    def test_index_global(self):
        self.assertEqual(
            self.index.global_.generated_at,
            datetime(2013, 4, 29, 18, 45, 27, tzinfo=timezone.utc))

    def test_index_image_count(self):
        self.assertEqual(len(self.index.images), 7)

    @unittest.skip('broken')
    def test_image_20130300_full(self):
        image = self.index.images[0]
        self.assertEqual(image.description, 'Some kind of daily build')
        self.assertEqual(image.type, 'full')
        self.assertEqual(image.version, '20130300')
        self.assertTrue(image.bootme)
        self.assertEqual(len(image.files), 3)
        # The first file is the device dependent image.  The second is the
        # device independent file, and the third is the version zip.
        dev, ind, ver = image.files
        self.assertEqual(dev.path, '/sprint/nexus7/nexus7-20130300.full.zip')
        self.assertEqual(dev.signature,
                         '/sprint/nexus7/nexus7-20130300.full.zip.asc')
        self.assertEqual(dev.checksum, 'abcdef0')
        self.assertEqual(dev.order, 0)
        self.assertEqual(dev.size, 0)
        # Let's not check the whole file, just a few useful bits.
        self.assertEqual(ind.checksum, 'abcdef1')
        self.assertEqual(ind.order, 0)
        self.assertEqual(ver.checksum, 'abcdef2')
        self.assertEqual(ver.order, 1)

    @unittest.skip('broken')
    def test_image_20130500_minversion(self):
        # Some full images have a minimum version older than which they refuse
        # to upgrade from.
        image = self.index.images[5]
        self.assertEqual(image.type, 'full')
        self.assertEqual(image.version, '20130500')
        self.assertTrue(image.bootme)
        self.assertEqual(image.minversion, '20130100')
