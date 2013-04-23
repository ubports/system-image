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
    ]


import unittest

from resolver.helpers import Bag


class TestBag(unittest.TestCase):
    def test_hyphens(self):
        # Hyphens get converted to underscores.
        bag = Bag(**{'foo-bar': 'yes'})
        self.assertEqual(bag.foo_bar, 'yes')

    def test_keywords(self):
        # Python keywords get an underscore appended.
        bag = Bag(**{'global': 'yes'})
        self.assertEqual(bag.global_, 'yes')
