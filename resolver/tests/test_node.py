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

from pkg_resources import resource_string
from resolver.node import Channels


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
