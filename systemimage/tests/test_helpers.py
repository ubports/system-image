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

"""Test helpers."""


__all__ = [
    'TestBag',
    'TestConverters',
    ]


import logging
import unittest

from datetime import timedelta
from systemimage.helpers import Bag, as_loglevel, as_object, as_timedelta


class TestBag(unittest.TestCase):
    def test_hyphens(self):
        # Hyphens get converted to underscores.
        bag = Bag(**{'foo-bar': 'yes'})
        self.assertEqual(bag.foo_bar, 'yes')

    def test_keywords(self):
        # Python keywords get an underscore appended.
        bag = Bag(**{'global': 'yes'})
        self.assertEqual(bag.global_, 'yes')


class TestConverters(unittest.TestCase):
    def test_as_object_good_path(self):
        self.assertEqual(as_object('systemimage.helpers.Bag'), Bag)

    def test_as_object_no_dot(self):
        self.assertRaises(ValueError, as_object, 'foo')

    def test_as_object_import_error(self):
        self.assertRaises(ImportError, as_object,
                          'systemimage.doesnotexist.Foo')

    def test_as_object_attribute_error(self):
        self.assertRaises(AttributeError, as_object,
                          'systemimage.tests.test_helpers.NoSuchTest')

    def test_as_timedelta_seconds(self):
        self.assertEqual(as_timedelta('2s'), timedelta(seconds=2))

    def test_as_timedelta_unadorned(self):
        self.assertRaises(ValueError, as_timedelta, '5')

    def test_as_timedelta_minutes(self):
        self.assertEqual(as_timedelta('10m'), timedelta(seconds=600))

    def test_as_timedelta_unknown(self):
        self.assertRaises(ValueError, as_timedelta, '3x')

    def test_as_loglevel(self):
        self.assertEqual(as_loglevel('error'), logging.ERROR)

    def test_as_loglevel_uppercase(self):
        self.assertEqual(as_loglevel('ERROR'), logging.ERROR)

    def test_as_loglevel_unknown(self):
        self.assertRaises(ValueError, as_loglevel, 'BADNESS')
