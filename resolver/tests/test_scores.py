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

__all__ = [
    'TestWeightedScorer',
    ]


import unittest

from resolver.candidates import get_candidates
from resolver.scores import WeightedScorer
from resolver.tests.helpers import get_index


class TestWeightedScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = WeightedScorer()

    def test_choose_no_candidates(self):
        # If there are no candidates, then there is no path to upgrade.
        self.assertEqual(self.scorer.choose([]), [])

    def test_score_no_candidates(self):
        self.assertEqual(self.scorer.score([]), [])

    def test_one_path(self):
        index = get_index('index_08.json')
        candidates = get_candidates(index, 20120600)
        # There's only one path.
        scores = self.scorer.score(candidates)
        # The score is 200 for the two extra bootme flags.
        self.assertEqual(scores, [200])
        # And we upgrade to the only path available.
        winner = self.scorer.choose(candidates)
        # There are two images in the winning path.
        self.assertEqual(len(winner), 2)
        self.assertEqual([image.version for image in winner],
                         [20130300, 20130301])

    def test_three_paths(self):
        # - Path A requires three extra reboots, is the smallest total
        #   download and leaves you at the highest available version.
        #   Score: 300
        #
        # - Path B requires one extra reboot, but is 100MiB bigger and leaves
        #   you at the highest available version.  Score: 200
        #
        # - Path C requires no extra reboots, but is 400MiB bigger and leaves
        #   you at 20130303 instead of the highest 20130304.  Score: 401
        #
        # Path B wins.
        index = get_index('index_09.json')
        candidates = get_candidates(index, 20120600)
        # There are three paths.  The scores are as above.
        scores = self.scorer.score(candidates)
        self.assertEqual(scores, [300, 200, 401])
        winner = self.scorer.choose(candidates)
        self.assertEqual(len(winner), 3)
        self.assertEqual([image.version for image in winner],
                         [20130200, 20130201, 20130304])
        self.assertEqual([image.description for image in winner],
                         ['Full B', 'Delta B.1', 'Delta B.2'])
