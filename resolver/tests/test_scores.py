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
        score = self.scorer.score(candidates)
        # The score is 200 for the two extra bootme flags.
        self.assertEqual(score, [200])
