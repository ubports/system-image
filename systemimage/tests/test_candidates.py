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

"""Test the candidate upgrade path algorithm."""

__all__ = [
    'TestCandidateDownloads',
    'TestCandidateFilters',
    'TestCandidates',
    'TestNewVersionRegime',
    ]


import unittest

from operator import attrgetter
from systemimage.candidates import (
    delta_filter, full_filter, get_candidates, iter_path)
from systemimage.scores import WeightedScorer
from systemimage.testing.helpers import (
    configuration, descriptions, get_index)


class TestCandidates(unittest.TestCase):
    def test_no_images(self):
        # If there are no images defined, there are no candidates.
        index = get_index('candidates.index_01.json')
        candidates = get_candidates(index, 1400)
        self.assertEqual(candidates, [])

    def test_only_higher_fulls(self):
        # All the full images have a minversion greater than our version, so
        # we cannot upgrade to any of them.
        index = get_index('candidates.index_02.json')
        candidates = get_candidates(index, 100)
        self.assertEqual(candidates, [])

    def test_one_higher_full(self):
        # Our device is between the minversions of the two available fulls, so
        # the older one can be upgraded too.
        index = get_index('candidates.index_02.json')
        candidates = get_candidates(index, 800)
        # There is exactly one upgrade path.
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        # The path has exactly one image.
        self.assertEqual(len(path), 1)
        image = path[0]
        self.assertEqual(list(image.descriptions.values()),
                         ['New full build 1'])

    def test_fulls_with_no_minversion(self):
        # Like the previous test, there are two full upgrades, but because
        # neither of them have minversions, both are candidates.
        index = get_index('candidates.index_03.json')
        candidates = get_candidates(index, 400)
        self.assertEqual(len(candidates), 2)
        # Both candidate paths have exactly one image in them.  We can't sort
        # these paths, so just test them both.
        path0, path1 = candidates
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # One path gets us to version 1300 and the other 1400.
        images = sorted([path0[0], path1[0]], key=attrgetter('version'))
        self.assertEqual(list(images[0].descriptions.values()),
                         ['New full build 1'])
        self.assertEqual(list(images[1].descriptions.values()),
                         ['New full build 2'])

    def test_no_deltas_based_on_us(self):
        # There are deltas in the test data, but no fulls.  None of the deltas
        # have a base equal to our build number.
        index = get_index('candidates.index_04.json')
        candidates = get_candidates(index, 100)
        self.assertEqual(candidates, [])

    def test_one_delta_based_on_us(self):
        # There is one delta in the test data that is based on us.
        index = get_index('candidates.index_04.json')
        candidates = get_candidates(index, 500)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        # The path has exactly one image.
        self.assertEqual(len(path), 1)
        image = path[0]
        self.assertEqual(list(image.descriptions.values()), ['Delta 2'])

    def test_two_deltas_based_on_us(self):
        # There are two deltas that are based on us, so both are candidates.
        # They get us to different final versions.
        index = get_index('candidates.index_05.json')
        candidates = get_candidates(index, 1100)
        self.assertEqual(len(candidates), 2)
        # Both candidate paths have exactly one image in them.  We can't sort
        # these paths, so just test them both.
        path0, path1 = candidates
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # One path gets us to version 1300 and the other 1400.
        images = sorted([path0[0], path1[0]], key=attrgetter('version'))
        self.assertEqual(descriptions(images), ['Delta 2', 'Delta 1'])

    def test_one_path_with_full_and_deltas(self):
        # There's one path to upgrade from our version to the final version.
        # This one starts at a full and includes several deltas.
        index = get_index('candidates.index_06.json')
        candidates = get_candidates(index, 1000)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        self.assertEqual(len(path), 3)
        self.assertEqual([image.version for image in path],
                         [1300, 1301, 1302])
        self.assertEqual(descriptions(path), ['Full 1', 'Delta 1', 'Delta 2'])

    def test_one_path_with_deltas(self):
        # Similar to above, except that because we're upgrading from the
        # version of the full, the path is only two images long, i.e. the
        # deltas.
        index = get_index('candidates.index_06.json')
        candidates = get_candidates(index, 1300)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        self.assertEqual(len(path), 2)
        self.assertEqual([image.version for image in path], [1301, 1302])
        self.assertEqual(descriptions(path), ['Delta 1', 'Delta 2'])

    def test_forked_paths(self):
        # We have a fork in the road.  There is a full update, but two deltas
        # with different versions point to the same base.  This will give us
        # two upgrade paths, both of which include the full.
        index = get_index('candidates.index_07.json')
        candidates = get_candidates(index, 1200)
        self.assertEqual(len(candidates), 2)
        # We can sort the paths by length.
        paths = sorted(candidates, key=len)
        # The shortest path gets us to 1302 in two steps.
        self.assertEqual(len(paths[0]), 2)
        self.assertEqual([image.version for image in paths[0]], [1300, 1302])
        descriptions = []
        for image in paths[0]:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full 1', 'Delta 2'])
        # The longer path gets us to 1302 in three steps.
        self.assertEqual(len(paths[1]), 3)
        self.assertEqual([image.version for image in paths[1]],
                         [1300, 1301, 1302])
        descriptions = []
        for image in paths[1]:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full 1', 'Delta 1', 'Delta 3'])


class TestCandidateDownloads(unittest.TestCase):
    maxDiff = None

    @configuration
    def test_get_downloads(self):
        # Path B will win; it has one full and two deltas, none of which have
        # a bootme flag.  Download all their files.
        index = get_index('candidates.index_08.json')
        candidates = get_candidates(index, 600)
        winner = WeightedScorer().choose(candidates, 'devel')
        descriptions = []
        for image in winner:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full B', 'Delta B.1', 'Delta B.2'])
        downloads = list(iter_path(winner))
        paths = set(filerec.path for (n, filerec) in downloads)
        self.assertEqual(paths, set([
            '/3/4/5.txt',
            '/4/5/6.txt',
            '/5/6/7.txt',
            '/6/7/8.txt',
            '/7/8/9.txt',
            '/8/9/a.txt',
            '/9/a/b.txt',
            '/e/d/c.txt',
            '/f/e/d.txt',
            ]))
        signatures = set(filerec.signature for (n, filerec) in downloads)
        self.assertEqual(signatures, set([
            '/3/4/5.txt.asc',
            '/4/5/6.txt.asc',
            '/5/6/7.txt.asc',
            '/6/7/8.txt.asc',
            '/7/8/9.txt.asc',
            '/8/9/a.txt.asc',
            '/9/a/b.txt.asc',
            '/e/d/c.txt.asc',
            '/f/e/d.txt.asc',
            ]))

    @configuration
    def test_get_downloads_with_bootme(self):
        # Path B will win; it has one full and two deltas.  The first delta
        # has a bootme flag so the second delta's files are not downloaded.
        index = get_index('candidates.index_09.json')
        candidates = get_candidates(index, 600)
        winner = WeightedScorer().choose(candidates, 'devel')
        descriptions = []
        for image in winner:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full B', 'Delta B.1', 'Delta B.2'])
        downloads = iter_path(winner)
        paths = set(filerec.path for (n, filerec) in downloads)
        self.assertEqual(paths, set([
            '/3/4/5.txt',
            '/4/5/6.txt',
            '/5/6/7.txt',
            '/6/7/8.txt',
            '/7/8/9.txt',
            '/8/9/a.txt',
            ]))


class TestCandidateFilters(unittest.TestCase):
    def test_filter_for_fulls(self):
        # Run a filter over the candidates, such that the only ones left are
        # those that contain only full upgrades.  This can truncate any paths
        # that start with some fulls and then contain some deltas.
        index = get_index('candidates.index_08.json')
        candidates = get_candidates(index, 600)
        filtered = full_filter(candidates)
        # Since all images start with a full update, we're still left with
        # three candidates.
        self.assertEqual(len(filtered), 3)
        self.assertEqual([image.type for image in filtered[0]], ['full'])
        self.assertEqual([image.type for image in filtered[1]], ['full'])
        self.assertEqual([image.type for image in filtered[2]], ['full'])
        self.assertEqual(descriptions(filtered[0]), ['Full A'])
        self.assertEqual(descriptions(filtered[1]), ['Full B'])
        self.assertEqual(descriptions(filtered[2]), ['Full C'])

    def test_filter_for_fulls_one_candidate(self):
        # Filter for full updates, where the only candidate has one full image.
        index = get_index('candidates.index_10.json')
        candidates = get_candidates(index, 600)
        filtered = full_filter(candidates)
        self.assertEqual(filtered, candidates)

    def test_filter_for_fulls_with_just_delta_candidates(self):
        # A candidate path that contains only deltas will have no filtered
        # paths if all the images are delta updates.
        index = get_index('candidates.index_11.json')
        candidates = get_candidates(index, 100)
        self.assertEqual(len(candidates), 1)
        filtered = full_filter(candidates)
        self.assertEqual(len(filtered), 0)

    def test_filter_for_deltas(self):
        # Filter the candidates, where the only available path is a delta path.
        index = get_index('candidates.index_11.json')
        candidates = get_candidates(index, 100)
        self.assertEqual(len(candidates), 1)
        filtered = delta_filter(candidates)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(candidates, filtered)

    def test_filter_for_deltas_none_available(self):
        # Run a filter over the candidates, such that the only ones left are
        # those that start with and contain only deltas.  Since none of the
        # paths do so, tere are no candidates left.
        index = get_index('candidates.index_08.json')
        candidates = get_candidates(index, 600)
        filtered = delta_filter(candidates)
        self.assertEqual(len(filtered), 0)

    def test_filter_for_deltas_one_candidate(self):
        # Filter for delta updates, but the only candidate is a full.
        index = get_index('candidates.index_10.json')
        candidates = get_candidates(index, 600)
        filtered = delta_filter(candidates)
        self.assertEqual(len(filtered), 0)

    def test_filter_for_multiple_deltas(self):
        # The candidate path has multiple deltas.  All are preserved.
        index = get_index('candidates.index_12.json')
        candidates = get_candidates(index, 100)
        filtered = delta_filter(candidates)
        self.assertEqual(len(filtered), 1)
        path = filtered[0]
        self.assertEqual(len(path), 3)
        self.assertEqual(descriptions(path),
                         ['Delta A', 'Delta B', 'Delta C'])


class TestNewVersionRegime(unittest.TestCase):
    """LP: #1218612"""

    def test_candidates(self):
        # Path B will win; it has one full and two deltas.
        index = get_index('candidates.index_13.json')
        candidates = get_candidates(index, 0)
        self.assertEqual(len(candidates), 3)
        path0 = candidates[0]
        self.assertEqual(descriptions(path0),
                         ['Full A', 'Delta A.1', 'Delta A.2'])
        path1 = candidates[1]
        self.assertEqual(descriptions(path1),
                         ['Full B', 'Delta B.1', 'Delta B.2'])
        path2 = candidates[2]
        self.assertEqual(descriptions(path2), ['Full C', 'Delta C.1'])
        # The version numbers use the new regime.
        self.assertEqual(path0[0].version, 300)
        self.assertEqual(path0[1].base, 300)
        self.assertEqual(path0[1].version, 301)
        self.assertEqual(path0[2].base, 301)
        self.assertEqual(path0[2].version, 304)
        winner = WeightedScorer().choose(candidates, 'devel')
        self.assertEqual(descriptions(winner),
                         ['Full B', 'Delta B.1', 'Delta B.2'])
        self.assertEqual(winner[0].version, 200)
        self.assertEqual(winner[1].base, 200)
        self.assertEqual(winner[1].version, 201)
        self.assertEqual(winner[2].base, 201)
        self.assertEqual(winner[2].version, 304)
