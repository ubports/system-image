# Copyright (C) 2013-2014 Canonical Ltd.
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


import pickle
import unittest

from operator import setitem
from systemimage.bag import Bag


class TestBag(unittest.TestCase):
    def test_simple(self):
        # Initialize a bag; its attributes are the keywords of the ctor.
        bag = Bag(a=1, b=2, c=3)
        self.assertEqual(bag.a, 1)
        self.assertEqual(bag.b, 2)
        self.assertEqual(bag.c, 3)

    def test_dash_translation(self):
        # Dashes in keys get turned into underscore in attributes.
        bag = Bag(**{'a-b': 1, 'c-d': 2, 'e-f': 3})
        self.assertEqual(bag.a_b, 1)
        self.assertEqual(bag.c_d, 2)
        self.assertEqual(bag.e_f, 3)

    def test_dash_literal_access(self):
        # For keys with dashes, the original name is preserved in getitem.
        bag = Bag(**{'a-b': 1, 'c-d': 2, 'e-f': 3})
        self.assertEqual(bag['a-b'], 1)
        self.assertEqual(bag['c-d'], 2)
        self.assertEqual(bag['e-f'], 3)

    def test_keyword_translation(self):
        # Python keywords get a trailing underscore.
        bag = Bag(**{'global': 1, 'with': 2, 'import': 3})
        self.assertEqual(bag.global_, 1)
        self.assertEqual(bag.with_, 2)
        self.assertEqual(bag.import_, 3)

    def test_repr(self):
        # The repr of a bag includes its translated keys.
        bag = Bag(**{'a-b': 1, 'global': 2, 'foo': 3})
        self.assertEqual(repr(bag), '<Bag: a_b, foo, global_>')

    def test_original(self):
        # There's a magical attribute containing the original ctor arguments.
        source = {'a-b': 1, 'global': 2, 'foo': 3}
        bag = Bag(**source)
        self.assertEqual(bag.__original__, source)

    def test_add_key(self):
        # We can add new keys/attributes via setitem.
        bag = Bag(a=1, b=2, c=3)
        bag['d'] = bag.b + bag.c
        self.assertEqual(bag.d, 5)

    def test_add_existing_key(self):
        # A key set in the original ctor cannot be changed.
        bag = Bag(a=1, b=2, c=3)
        self.assertRaises(ValueError, setitem, bag, 'b', 5)
        self.assertEqual(bag.b, 2)

    def test_add_new_key(self):
        # A key added by setitem can be changed.
        bag = Bag(a=1, b=2, c=3)
        bag['d'] = 4
        bag['d'] = 5
        self.assertEqual(bag.d, 5)

    def test_pickle(self):
        # Bags can be pickled and unpickled.
        bag = Bag(a=1, b=2, c=3)
        pck = pickle.dumps(bag)
        new_bag = pickle.loads(pck)
        self.assertEqual(new_bag.a, 1)
        self.assertEqual(new_bag.b, 2)
        self.assertEqual(new_bag.c, 3)

    def test_update(self):
        # Bags can be updated, similar to dicts.
        bag = Bag(a=1, b=2, c=3)
        bag.update(b=7, d=9)
        self.assertEqual(bag.a, 1)
        self.assertEqual(bag.b, 7)
        self.assertEqual(bag.c, 3)
        self.assertEqual(bag.d, 9)

    def test_converters(self):
        # The Bag ctor accepts a mapping of type converter functions.
        bag = Bag(converters=dict(a=int, b=int),
                  a='1', b='2', c='3')
        self.assertEqual(bag.a, 1)
        self.assertEqual(bag.b, 2)
        self.assertEqual(bag.c, '3')

    def test_converters_error(self):
        # Type converter function errors get propagated.
        converters = dict(a=int, b=int)
        keywords = dict(a='1', b='foo', c=3)
        self.assertRaises(ValueError, Bag, converters=converters, **keywords)

    def test_update_converters(self):
        # The update method also accepts converters.
        bag = Bag(a=1, b=2, c=3)
        bag.update(converters=dict(d=int),
                   d='4', e='5')
        self.assertEqual(bag.d, 4)
        self.assertEqual(bag.e, '5')

    def test_update_converter_overrides(self):
        # Converters in the update method permanently override ctor converters.
        converters = dict(a=int, b=int)
        bag = Bag(converters=converters, a='1', b='2')
        self.assertEqual(bag.a, 1)
        self.assertEqual(bag.b, 2)
        new_converters = dict(a=str)
        bag.update(converters=new_converters, a='3', b='4')
        self.assertEqual(bag.a, '3')
        self.assertEqual(bag.b, 4)
        bag.update(a='5', b='6')
        self.assertEqual(bag.a, '5')
        self.assertEqual(bag.b, 6)
