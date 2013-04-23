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

"""Test the node classes."""

import unittest

from datetime import datetime, timezone
from pkg_resources import resource_string
from resolver.channel import Channels


class TestNodes(unittest.TestCase):
    def test_channels(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channel objects.
        json_data = resource_string(
            'resolver.tests.data', 'channels_01.json').decode('utf-8')
        channels = Channels(json_data)
        self.assertEqual(len(channels.channels), 2)
        self.assertEqual(sorted(channels.channels),
                         sorted(channel.name
                                for channel in channels.channels.values()))
        # The stable channel has a single index.
        stable = channels.channels['stable']
        self.assertEqual(stable.name, 'stable')
        self.assertEqual(list(stable.indexes), ['nexus7'])
        # The daily channel has two indexes.
        daily = channels.channels['daily']
        self.assertEqual(daily.name, 'daily')
        self.assertEqual(sorted(daily.indexes), ['nexus4', 'nexus7'])

    def test_indexes(self):
        # Test that the expected top level index data gets parsed correctly.
        json_data = resource_string(
            'resolver.tests.data', 'channels_01.json').decode('utf-8')
        channels = Channels(json_data)
        stable = channels.channels['stable']
        nexus7 = stable.indexes['nexus7']
        self.assertEqual(nexus7.name, 'nexus7')
        self.assertEqual(nexus7.path, '/stable/nexus7/index.json')
        daily = channels.channels['daily']
        nexus7 = daily.indexes['nexus7']
        self.assertEqual(nexus7.name, 'nexus7')
        self.assertEqual(nexus7.path, '/daily/nexus7/index.json')
        nexus4 = daily.indexes['nexus4']
        self.assertEqual(nexus4.name, 'nexus4')
        self.assertEqual(nexus4.path, '/daily/nexus4/index.json')

    def test_timestamp(self):
        # Make sure that an index filled out with a separately downloaded
        # index.json will have a proper UTC aware timestamp.
        json_data = resource_string(
            'resolver.tests.data', 'channels_01.json').decode('utf-8')
        channels = Channels(json_data)
        nexus7 = channels.channels['stable'].indexes['nexus7']
        # This isn't available until we've filled it in with additional JSON
        # data.
        self.assertIsNone(nexus7.generated_at)
        json_data = resource_string(
            'resolver.tests.data', 'stable_nexus7_index.json').decode('utf-8')
        nexus7.extend(json_data)
        self.assertEqual(nexus7.generated_at,
                         datetime(2013, 4, 11, 15, 1, 46, tzinfo=timezone.utc))
