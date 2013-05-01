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

from operator import attrgetter
from resolver.candidates import get_candidates
from resolver.tests.helpers import get_index


class TestCandidates(unittest.TestCase):
    def test_no_images(self):
        # If there are no images defined, there are no candidates.
        index = get_index('index_01.json')
        candidates = get_candidates(index, 20130400)
        self.assertEqual(candidates, [])

    def test_only_higher_fulls(self):
        # All the full images have a minversion greater than our version, so
        # we cannot upgrade to any of them.
        index = get_index('index_02.json')
        candidates = get_candidates(index, 20120100)
        self.assertEqual(candidates, [])

    def test_one_higher_full(self):
        # Our device is between the minversions of the two available fulls, so
        # the older one can be upgraded too.
        index = get_index('index_02.json')
        candidates = get_candidates(index, 20120800)
        # There is exactly one upgrade path.
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        # The path has exactly one image.
        self.assertEqual(len(path), 1)
        image = path[0]
        self.assertEqual(image.description, 'New full build 1')

    def test_fulls_with_no_minversion(self):
        # Like the previous test, there are two full upgrades, but because
        # neither of them have minversions, both are candidates.
        index = get_index('index_05.json')
        candidates = get_candidates(index, 20120400)
        self.assertEqual(len(candidates), 2)
        # Both candidate paths have exactly one image in them.  We can't sort
        # these paths, so just test them both.
        path0, path1 = candidates
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # One path gets us to version 20130300 and the other 20130400.
        images = sorted([path0[0], path1[0]], key=attrgetter('version'))
        self.assertEqual(images[0].description, 'New full build 1')
        self.assertEqual(images[1].description, 'New full build 2')

    def test_no_deltas_based_on_us(self):
        # There are deltas in the test data, but no fulls.  None of the deltas
        # have a base equal to our build number.
        index = get_index('index_03.json')
        candidates = get_candidates(index, 20120100)
        self.assertEqual(candidates, [])

    def test_one_delta_based_on_us(self):
        # There is one delta in the test data that is based on us.
        index = get_index('index_03.json')
        candidates = get_candidates(index, 20120500)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        # The path has exactly one image.
        self.assertEqual(len(path), 1)
        image = path[0]
        self.assertEqual(image.description, 'Delta 2')

    def test_two_deltas_based_on_us(self):
        # There are two deltas that are based on us, so both are candidates.
        # They get us to different final versions.
        index = get_index('index_04.json')
        candidates = get_candidates(index, 20130100)
        self.assertEqual(len(candidates), 2)
        # Both candidate paths have exactly one image in them.  We can't sort
        # these paths, so just test them both.
        path0, path1 = candidates
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # One path gets us to version 20130300 and the other 20130400.
        images = sorted([path0[0], path1[0]], key=attrgetter('version'))
        self.assertEqual(images[0].description, 'Delta 2')
        self.assertEqual(images[1].description, 'Delta 1')
