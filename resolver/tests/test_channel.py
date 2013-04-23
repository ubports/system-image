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

__all__ = [
    'TestChannels',
    ]


import unittest

from pkg_resources import resource_string
from resolver.channel import Channels


class TestChannels(unittest.TestCase):
    def setUp(self):
        # Test that parsing a simple top level channels.json file produces the
        # expected set of channels.
        json_data = resource_string(
            'resolver.tests.data', 'channels_01.json').decode('utf-8')
        self.channels = Channels.from_json(json_data)

    def test_channels(self):
        self.assertEqual(
            self.channels.daily.nexus7, '/daily/nexus7/index.json')
        self.assertEqual(
            self.channels.daily.nexus4, '/daily/nexus4/index.json')
        self.assertEqual(
            self.channels.stable.nexus7, '/stable/nexus7/index.json')

    def test_getattr_failure(self):
        # Test the getattr syntax on an unknown channel or device combination.
        self.assertRaises(AttributeError, getattr, self.channels, 'bleeding')
        self.assertRaises(AttributeError,
                          getattr, self.channels.stable, 'nexus3')
