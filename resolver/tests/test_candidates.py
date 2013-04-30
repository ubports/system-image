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

"""Test the candidate upgrade path algorithm."""

__all__ = [
    'TestCandidates',
    ]


import unittest

from resolver.candidates import get_candidates
from resolver.tests.helpers import get_index


class TestCandidates(unittest.TestCase):
    def test_no_images(self):
        # If there are no images defined, there are no candidates.
        index = get_index('index_01.json')
        candidates = get_candidates(index, 20130400)
        self.assertEqual(candidates, set([]))

    def test_only_higher_fulls(self):
        # All the full images have a minversion greater than our version, so
        # we cannot upgrade to any of them.
        pass
