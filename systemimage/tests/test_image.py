# Copyright (C) 2013-2015 Canonical Ltd.
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
    'TestNewVersionRegime',
    ]


import unittest

from systemimage.image import Image


class TestImage(unittest.TestCase):
    def test_full_hash(self):
        image = Image(type='full', version=400)
        self.assertEqual(hash(image), 0b1100100000000000000000000)

    def test_full_hash_ignores_base(self):
        image = Image(type='full', version=400, base=300)
        self.assertEqual(hash(image), 0b1100100000000000000000000)

    def test_delta_includes_base(self):
        image = Image(type='delta', version=400, base=300)
        self.assertEqual(hash(image), 0b1100100000000000100101100)

    def test_delta_with_more_info(self):
        image = Image(type='delta', version=299, base=1212)
        self.assertEqual(hash(image), 0b1001010110000010010111100)

    def test_full_equal(self):
        image_1 = Image(type='full', version=400)
        image_2 = Image(type='full', version=400)
        self.assertEqual(image_1, image_2)

    def test_full_inequal(self):
        image_1 = Image(type='full', version=400)
        image_2 = Image(type='full', version=401)
        self.assertNotEqual(image_1, image_2)

    def test_full_equal_ignores_base(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='full', version=400, base=299)
        self.assertEqual(image_1, image_2)

    def test_full_equal_ignores_missing_base(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='full', version=400)
        self.assertEqual(image_1, image_2)

    def test_full_delta_with_base_inequal(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='delta', version=400, base=300)
        self.assertNotEqual(image_1, image_2)

    def test_default_phased_percentage(self):
        image = Image(type='full', version=10)
        self.assertEqual(image.phased_percentage, 100)

    def test_explicit_phased_percentage(self):
        kws = dict(type='full', version=10)
        kws['phased-percentage'] = '39'
        image = Image(**kws)
        self.assertEqual(image.phased_percentage, 39)


class TestNewVersionRegime(unittest.TestCase):
    """LP: #1218612"""

    def test_full_hash(self):
        image = Image(type='full', version=3)
        self.assertEqual(hash(image), 0b00000000000000110000000000000000)

    def test_full_hash_ignores_base(self):
        image = Image(type='full', version=3, base=2)
        self.assertEqual(hash(image), 0b00000000000000110000000000000000)

    def test_delta_includes_base(self):
        image = Image(type='delta', version=3, base=2)
        self.assertEqual(hash(image), 0b00000000000000110000000000000010)

    def test_delta_with_more_info(self):
        image = Image(type='delta', version=99, base=83)
        self.assertEqual(hash(image), 0b00000000011000110000000001010011)

    def test_full_equal(self):
        image_1 = Image(type='full', version=17)
        image_2 = Image(type='full', version=17)
        self.assertEqual(image_1, image_2)

    def test_full_inequal(self):
        image_1 = Image(type='full', version=17)
        image_2 = Image(type='full', version=18)
        self.assertNotEqual(image_1, image_2)

    def test_full_equal_ignores_base(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='full', version=400, base=299)
        self.assertEqual(image_1, image_2)

    def test_full_equal_ignores_missing_base(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='full', version=400)
        self.assertEqual(image_1, image_2)

    def test_full_delta_with_base_inequal(self):
        image_1 = Image(type='full', version=400, base=300)
        image_2 = Image(type='delta', version=400, base=300)
        self.assertNotEqual(image_1, image_2)

    def test_signed_version_rejects(self):
        self.assertRaises(AssertionError, hash,
                          Image(type='full', version=-1))

    def test_17bit_version_rejects(self):
        self.assertRaises(AssertionError, hash,
                          Image(type='full', version=1 << 16))

    def test_mixed_regime_rejects(self):
        self.assertRaises(AssertionError, hash,
                          Image(type='delta', version=3, base=20130899))

    def test_mixed_regime_full_okay(self):
        self.assertEqual(hash(Image(type='full', version=3, base=20130899)),
                         0b00000000000000110000000000000000)

    def test_mixed_regime_reversed_rejects(self):
        self.assertRaises(AssertionError, hash,
                          Image(type='delta', version=20130899, base=3))
