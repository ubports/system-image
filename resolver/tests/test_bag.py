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

"""Test the Bag class."""

__all__ = [
    'TestBag',
    ]


import unittest

from operator import setitem
from resolver.bag import Bag


class TestBag(unittest.TestCase):
    def test_simple(self):
        bag = Bag(a=1, b=2, c=3)
        self.assertEqual(bag.a, 1)
        self.assertEqual(bag.b, 2)
        self.assertEqual(bag.c, 3)

    def test_dash_translation(self):
        bag = Bag(**{'a-b': 1, 'c-d': 2, 'e-f': 3})
        self.assertEqual(bag.a_b, 1)
        self.assertEqual(bag.c_d, 2)
        self.assertEqual(bag.e_f, 3)

    def test_keyword_translation(self):
        bag = Bag(**{'global': 1, 'with': 2, 'import': 3})
        self.assertEqual(bag.global_, 1)
        self.assertEqual(bag.with_, 2)
        self.assertEqual(bag.import_, 3)

    def test_repr(self):
        bag = Bag(**{'a-b': 1, 'global': 2, 'foo': 3})
        self.assertEqual(repr(bag), '<Bag: a_b, foo, global_>')

    def test_original(self):
        source = {'a-b': 1, 'global': 2, 'foo': 3}
        bag = Bag(**source)
        self.assertEqual(bag.__original__, source)

    def test_add_key(self):
        bag = Bag(a=1, b=2, c=3)
        bag['d'] = bag.b + bag.c
        self.assertEqual(bag.d, 5)

    def test_add_existing_key(self):
        bag = Bag(a=1, b=2, c=3)
        self.assertRaises(ValueError, setitem, bag, 'b', 5)
        self.assertEqual(bag.b, 2)
