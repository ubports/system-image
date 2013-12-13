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

from systemimage.candidates import get_candidates
from systemimage.scores import WeightedScorer
from systemimage.testing.helpers import get_index


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
        candidates = get_candidates(index, 600)
        # There's only one path.
        scores = self.scorer.score(candidates)
        # The score is 200 for the two extra bootme flags.
        self.assertEqual(scores, [200])
        # And we upgrade to the only path available.
        winner = self.scorer.choose(candidates)
        # There are two images in the winning path.
        self.assertEqual(len(winner), 2)
        self.assertEqual([image.version for image in winner], [1300, 1301])

    def test_three_paths(self):
        # - Path A requires three extra reboots, is the smallest total
        #   download and leaves you at the highest available version.
        #   Score: 300
        #
        # - Path B requires one extra reboot, but is 100MiB bigger and leaves
        #   you at the highest available version.  Score: 200
        #
        # - Path C requires no extra reboots, but is 400MiB bigger and leaves
        #   you at 1303 instead of the highest 1304.  For that reason, it gets
        #   a huge score making it impossible to win.
        #
        # Path B wins.
        index = get_index('index_09.json')
        candidates = get_candidates(index, 600)
        # There are three paths.  The scores are as above.
        scores = self.scorer.score(candidates)
        self.assertEqual(scores, [300, 200, 9401])
        winner = self.scorer.choose(candidates)
        self.assertEqual(len(winner), 3)
        self.assertEqual([image.version for image in winner],
                         [1200, 1201, 1304])
        descriptions = []
        for image in winner:
            # There's only one description per image so order doesn't matter.
            descriptions.extend(image.descriptions.values())
        self.assertEqual(descriptions, ['Full B', 'Delta B.1', 'Delta B.2'])

    def test_tied_candidates(self):
        # LP: #1206866 - TypeError when two candidate paths scored equal.
        #
        # index_17.json was captured from real data causing the traceback.
        index = get_index('index_17.json')
        candidates = get_candidates(index, 1)
        path = self.scorer.choose(candidates)
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0].version, 1800)
