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
from resolver.tests.helpers import get_index, make_index
from textwrap import dedent


class TestCandidates(unittest.TestCase):
    def test_no_bundles(self):
        # If there are no bundles defined, then there are no updates.
        index = make_index("""\
        {"bundles": [],
         "global": {"generated_at": "Thu Apr 11 15:01:46 UTC 2013"},
         "images": []
        }
        """)
        ubuntu, android = get_candidates(index, '20130301', '20130301')
        self.assertEqual(ubuntu, [])
        self.assertEqual(android, [])

    def test_duplicate_bundle_version(self):
        # It should not be possible to have duplicate bundles with the same
        # version string.
        index = make_index("""\
        {"bundles": [
            {"version": "20130304", "images": {}},
            {"version": "20130304", "images": {}},
            {"version": "20130201", "images": {}}
            ],
         "global": {"generated_at": "Thu Apr 11 15:01:46 UTC 2013"},
         "images": []
        }
        """)
        self.assertRaises(ValueError,
                          get_candidates, index, '20130301', '20130301')

    def test_at_current(self):
        # If we're already at the current bundle versions, there's no upgrade
        # paths available.  This data names the 20130304 bundle version, with
        # image versions of 20130301 for both.
        index = get_index('stable_nexus7_index_01.json')
        ubuntu, android = get_candidates(index, '20130301', '20130301')
        self.assertEqual(ubuntu, [])
        self.assertEqual(android, [])

    def test_needs_delta_update(self):
        # We're one delta behind.  This should give us two upgrade paths per
        # image flavor, one through the delta and one from the full.
        index = get_index('stable_nexus7_index_01.json')
        ubuntu, android = get_candidates(index, '20130300', '20130300')
        # Ubuntu upgrade paths:
        # -> 20130301-full
        # -> 20130301-delta
        self.assertEqual(len(ubuntu), 2)
        path0, path1 = ubuntu
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # We don't know which path has the full upgrade.
        if path0[0].type == 'full':
            full = path0[0]
            delta = path1[0]
        else:
            full = path1[0]
            delta = path0[0]
        self.assertEqual(full.version, '20130301')
        self.assertEqual(full.checksum,
                         '5a37ba30664cde4ab245e337c12d16f8ad892278')
        self.assertEqual(full.path, '/stable/ubuntu/ubuntu-20130301.full.zip')
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.checksum,
                         'ca124997894fa5be76f42a9404f6375d3aca1664')
        self.assertEqual(delta.path,
                         '/stable/ubuntu/ubuntu-20130301.delta-20130300.zip')
        # Android upgrade paths:
        # -> 20130301-delta
        # (there is no 20130301-full image in the sample data)
        self.assertEqual(len(android), 1)
        path0 = android[0]
        self.assertEqual(len(path0), 1)
        delta = path0[0]
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.checksum,
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(delta.path,
                         '/stable/nexus7/android-20130301.delta-20130300.zip')

    def test_missing_base(self):
        # If we need to upgrade to full monthly for which there is no image,
        # we have a problem.  In this case, because the current Android
        # version is at 20130200, we need the 20130300 full image, but that is
        # missing from the Android data.
        index = get_index('stable_nexus7_index_01.json')
        self.assertRaises(ValueError, get_candidates,
                          index, '20130200', '20130200')

    def test_ubuntu_upgrade_only(self):
        # We're up to date with Android, but out of date for Ubuntu.
        index = get_index('stable_nexus7_index_01.json')
        ubuntu, android = get_candidates(index, '20130300', '20130301')
        self.assertEqual(len(ubuntu), 2)
        path0, path1 = ubuntu
        # Ubuntu upgrade paths:
        # -> 20130301-full
        # -> 20130301-delta
        self.assertEqual(len(path0), 1)
        self.assertEqual(len(path1), 1)
        # We don't know which path has the full upgrade.
        if path0[0].type == 'full':
            full = path0[0]
            delta = path1[0]
        else:
            full = path1[0]
            delta = path0[0]
        self.assertEqual(full.version, '20130301')
        self.assertEqual(full.checksum,
                         '5a37ba30664cde4ab245e337c12d16f8ad892278')
        self.assertEqual(full.path, '/stable/ubuntu/ubuntu-20130301.full.zip')
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.checksum,
                         'ca124997894fa5be76f42a9404f6375d3aca1664')
        self.assertEqual(delta.path,
                         '/stable/ubuntu/ubuntu-20130301.delta-20130300.zip')
        # Android is up to date.
        self.assertEqual(len(android), 0)

    def test_android_upgrade_only(self):
        # We're up to date on Ubuntu but out of date on Android.
        index = get_index('stable_nexus7_index_01.json')
        ubuntu, android = get_candidates(index, '20130301', '20130300')
        # Ubuntu is up to date.
        self.assertEqual(len(ubuntu), 0)
        # Android upgrade paths:
        # -> 20130301-delta
        # (there is no 20130301-full image in the sample data)
        self.assertEqual(len(android), 1)
        path0 = android[0]
        self.assertEqual(len(path0), 1)
        delta = path0[0]
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.checksum,
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(delta.path,
                         '/stable/nexus7/android-20130301.delta-20130300.zip')

    def test_upgrade_by_a_bunch(self):
        # We're out of date by a full and a few deltas, so there are multiple
        # paths to the current version.
        index = get_index('stable_nexus7_index_02.json')
        ubuntu, android = get_candidates(index, '20130200', '20130200')
        # Ubuntu paths to upgrade:
        # -> 20130300 -> 20130301
        # -> 20130301
        self.assertEqual(len(ubuntu), 2)
        sorted_paths = sorted(ubuntu, key=len)
        full = sorted_paths[0]
        self.assertEqual(len(full), 1)
        monthly = full[0]
        self.assertEqual(monthly.version, '20130301')
        self.assertEqual(monthly.type, 'full')
        self.assertEqual(monthly.checksum,
                         '5a37ba30664cde4ab245e337c12d16f8ad892278')
        staged = sorted_paths[1]
        self.assertEqual(len(staged), 2)
        monthly = staged[0]
        self.assertEqual(monthly.version, '20130300')
        self.assertEqual(monthly.type, 'full')
        self.assertEqual(monthly.checksum,
                         'c513dc5e4ed887d8c56e138386f68c8e33f93002')
        delta = staged[1]
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.type, 'delta')
        self.assertEqual(delta.checksum,
                         'ca124997894fa5be76f42a9404f6375d3aca1664')
        self.assertEqual(delta.base, '20130300')
        # Android paths to upgrade:
        # -> 20130300 -> 20130301
        # -> 20130301
        self.assertEqual(len(android), 2)
        sorted_paths = sorted(android, key=len)
        full = sorted_paths[0]
        self.assertEqual(len(full), 1)
        monthly = full[0]
        self.assertEqual(monthly.version, '20130301')
        self.assertEqual(monthly.type, 'full')
        self.assertEqual(monthly.checksum,
                         'ea37ba30664cde4ab245e337c12d16f8ad892278')
        staged = sorted_paths[1]
        self.assertEqual(len(staged), 2)
        monthly = staged[0]
        self.assertEqual(monthly.version, '20130300')
        self.assertEqual(monthly.type, 'full')
        self.assertEqual(monthly.checksum,
                         'd513dc5e4ed887d8c56e138386f68c8e33f93002')
        delta = staged[1]
        self.assertEqual(delta.version, '20130301')
        self.assertEqual(delta.type, 'delta')
        self.assertEqual(delta.checksum,
                         'da39a3ee5e6b4b0d3255bfef95601890afd80709')
        self.assertEqual(delta.base, '20130300')

    def test_ignore_android(self):
        # Passing None ignores those candidates.
        index = get_index('stable_nexus7_index_02.json')
        ubuntu, android = get_candidates(index, '20130200')
        self.assertEqual(len(ubuntu), 2)
        self.assertEqual(len(android), 0)

    def test_ignore_ubuntu(self):
        # Passing None ignores those candidates.
        index = get_index('stable_nexus7_index_02.json')
        ubuntu, android = get_candidates(index, android_version='20130200')
        self.assertEqual(len(ubuntu), 0)
        self.assertEqual(len(android), 2)

    def test_ignore_both(self):
        # Passing None ignores those candidates.
        index = get_index('stable_nexus7_index_02.json')
        ubuntu, android = get_candidates(index)
        self.assertEqual(len(ubuntu), 0)
        self.assertEqual(len(android), 0)
