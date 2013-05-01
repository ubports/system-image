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

"""Test Image objects."""

__all__ = [
    'TestImage',
    ]


import unittest

from resolver.image import Image


class TestImage(unittest.TestCase):
    def test_full_hash(self):
        image = Image(type='full', version=20130400)
        # hex(20130400) == 0x1332a60
        self.assertEqual(hash(image), 0x1332a6000000000)

    def test_full_hash_ignores_base(self):
        image = Image(type='full', version=20130400, base=20130300)
        self.assertEqual(hash(image), 0x1332a6000000000)

    def test_delta_includes_base(self):
        image = Image(type='delta', version=20130400, base=20130300)
        # hex(20130300) == 0x13329fc
        self.assertEqual(hash(image), 0x1332a60013329fc)

    def test_full_equal(self):
        image_1 = Image(type='full', version=20130400)
        image_2 = Image(type='full', version=20130400)
        self.assertEqual(image_1, image_2)

    def test_full_inequal(self):
        image_1 = Image(type='full', version=20130400)
        image_2 = Image(type='full', version=20130401)
        self.assertNotEqual(image_1, image_2)

    def test_full_equal_ignores_base(self):
        image_1 = Image(type='full', version=20130400, base=20130300)
        image_2 = Image(type='full', version=20130400, base=20130299)
        self.assertEqual(image_1, image_2)

    def test_full_equal_ignores_missing_base(self):
        image_1 = Image(type='full', version=20130400, base=20130300)
        image_2 = Image(type='full', version=20130400)
        self.assertEqual(image_1, image_2)

    def test_full_delta_with_base_inequal(self):
        image_1 = Image(type='full', version=20130400, base=20130300)
        image_2 = Image(type='delta', version=20130400, base=20130300)
        self.assertNotEqual(image_1, image_2)
