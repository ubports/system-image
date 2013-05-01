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
    'TestPolicies',
    ]


import unittest

from resolver.candidates import get_candidates
from resolver.policies import ByDownloadSize
from resolver.tests.helpers import get_index


class TestPolicies(unittest.TestCase):
    def setUp(self):
        self.index = get_index('sprint_nexus7_index_01.json')

    @unittest.skip('broken')
    def test_by_download_size(self):
        # This policy optimizes for minimal download size.
        ubuntu, android = get_candidates(self.index, '20130200', '20130200')
        # Going straight to the latest full is a smaller download.
        smallest = ByDownloadSize().choose(ubuntu)
        self.assertEqual(len(smallest), 1)
        self.assertEqual(smallest[0].checksum,
                         '5a37ba30664cde4ab245e337c12d16f8ad892278')
        # Because of the sample data, it's actually less to download (by 1
        # byte :) the Android monthly + delta.
        smallest = ByDownloadSize().choose(android)
        self.assertEqual(len(smallest), 2)
        monthly, delta = smallest
        self.assertEqual(monthly.checksum,
                         'd513dc5e4ed887d8c56e138386f68c8e33f93002')
        self.assertEqual(monthly.version, '20130300')
        self.assertEqual(delta.checksum,
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(delta.version, '20130301')
