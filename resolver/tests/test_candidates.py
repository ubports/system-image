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
    'TestCandidateDownloads',
    ]


import os
import unittest

from operator import attrgetter
from resolver.candidates import get_candidates, get_downloads
from resolver.scores import WeightedScorer
from resolver.tests.helpers import get_index, make_temporary_cache


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
        self.assertEqual([image.description for image in images],
                         ['Delta 2', 'Delta 1'])

    def test_one_path_with_full_and_deltas(self):
        # There's one path to upgrade from our version to the final version.
        # This one starts at a full and includes several deltas.
        index = get_index('index_06.json')
        candidates = get_candidates(index, 20120000)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        self.assertEqual(len(path), 3)
        self.assertEqual([image.version for image in path],
                         [20130300, 20130301, 20130302])
        self.assertEqual([image.description for image in path],
                         ['Full 1', 'Delta 1', 'Delta 2'])

    def test_one_path_with_deltas(self):
        # Similar to above, except that because we're upgrading from the
        # version of the full, the path is only two images long, i.e. the
        # deltas.
        index = get_index('index_06.json')
        candidates = get_candidates(index, 20130300)
        self.assertEqual(len(candidates), 1)
        path = candidates[0]
        self.assertEqual(len(path), 2)
        self.assertEqual([image.version for image in path],
                         [20130301, 20130302])
        self.assertEqual([image.description for image in path],
                         ['Delta 1', 'Delta 2'])

    def test_forked_paths(self):
        # We have a fork in the road.  There is a full update, but two deltas
        # with different versions point to the same base.  This will give us
        # two upgrade paths, both of which include the full.
        index = get_index('index_07.json')
        candidates = get_candidates(index, 20130200)
        self.assertEqual(len(candidates), 2)
        # We can sort the paths by length.
        paths = sorted(candidates, key=len)
        # The shortest path gets us to 20130302 in two steps.
        self.assertEqual(len(paths[0]), 2)
        self.assertEqual([image.version for image in paths[0]],
                         [20130300, 20130302])
        self.assertEqual([image.description for image in paths[0]],
                         ['Full 1', 'Delta 2'])
        # The longer path gets us to 20130302 in three steps.
        self.assertEqual(len(paths[1]), 3)
        self.assertEqual([image.version for image in paths[1]],
                         [20130300, 20130301, 20130302])
        self.assertEqual([image.description for image in paths[1]],
                         ['Full 1', 'Delta 1', 'Delta 3'])


class TestCandidateDownloads(unittest.TestCase):
    def setUp(self):
        self._cache = make_temporary_cache(self.addCleanup)

    def test_get_downloads(self):
        # Path B will win; it has one full and two deltas, none of which have
        # a bootme flag.  Download all their files.
        index = get_index('index_10.json')
        candidates = get_candidates(index, 20120600)
        winner = WeightedScorer().choose(candidates)
        self.assertEqual([image.description for image in winner],
                         ['Full B', 'Delta B.1', 'Delta B.2'])
        downloads = get_downloads(winner, self._cache)
        urls = set(url for url, path in downloads)
        paths = set(path for url, path in downloads)
        self.maxDiff = None
        self.assertEqual(urls, set([
            'http://localhost:8909/3/4/5.txt',
            'http://localhost:8909/3/4/5.txt.asc',
            'http://localhost:8909/4/5/6.txt',
            'http://localhost:8909/4/5/6.txt.asc',
            'http://localhost:8909/5/6/7.txt',
            'http://localhost:8909/5/6/7.txt.asc',
            'http://localhost:8909/6/7/8.txt',
            'http://localhost:8909/6/7/8.txt.asc',
            'http://localhost:8909/7/8/9.txt',
            'http://localhost:8909/7/8/9.txt.asc',
            'http://localhost:8909/8/9/a.txt',
            'http://localhost:8909/8/9/a.txt.asc',
            'http://localhost:8909/9/a/b.txt',
            'http://localhost:8909/9/a/b.txt.asc',
            'http://localhost:8909/e/d/c.txt',
            'http://localhost:8909/e/d/c.txt.asc',
            'http://localhost:8909/f/e/d.txt',
            'http://localhost:8909/f/e/d.txt.asc',
            ]))
        # Strip the temporary directory at the start of the local file path.
        self.assertEqual(set(os.path.basename(path) for path in paths),
                         set([
            '5.txt',
            '5.txt.asc',
            '6.txt',
            '6.txt.asc',
            '7.txt',
            '7.txt.asc',
            '8.txt',
            '8.txt.asc',
            '9.txt',
            '9.txt.asc',
            'a.txt',
            'a.txt.asc',
            'b.txt',
            'b.txt.asc',
            'c.txt',
            'c.txt.asc',
            'd.txt',
            'd.txt.asc',
            ]))

    def test_get_downloads_with_bootme(self):
        # Path B will win; it has one full and two deltas.  The first delta
        # has a bootme flag so the second delta's files are not downloaded.
        index = get_index('index_11.json')
        candidates = get_candidates(index, 20120600)
        winner = WeightedScorer().choose(candidates)
        self.assertEqual([image.description for image in winner],
                         ['Full B', 'Delta B.1', 'Delta B.2'])
        downloads = get_downloads(winner, self._cache)
        urls = set(url for url, path in downloads)
        paths = set(path for url, path in downloads)
        self.maxDiff = None
        self.assertEqual(urls, set([
            'http://localhost:8909/3/4/5.txt',
            'http://localhost:8909/3/4/5.txt.asc',
            'http://localhost:8909/4/5/6.txt',
            'http://localhost:8909/4/5/6.txt.asc',
            'http://localhost:8909/5/6/7.txt',
            'http://localhost:8909/5/6/7.txt.asc',
            'http://localhost:8909/6/7/8.txt',
            'http://localhost:8909/6/7/8.txt.asc',
            'http://localhost:8909/7/8/9.txt',
            'http://localhost:8909/7/8/9.txt.asc',
            'http://localhost:8909/8/9/a.txt',
            'http://localhost:8909/8/9/a.txt.asc',
            ]))
        # Strip the temporary directory at the start of the local file path.
        self.assertEqual(set(os.path.basename(path) for path in paths),
                         set([
            '5.txt',
            '5.txt.asc',
            '6.txt',
            '6.txt.asc',
            '7.txt',
            '7.txt.asc',
            '8.txt',
            '8.txt.asc',
            '9.txt',
            '9.txt.asc',
            'a.txt',
            'a.txt.asc',
            ]))
