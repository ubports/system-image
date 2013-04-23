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

"""Test the configuration parser."""

__all__ = [
    'TestConfiguration',
    ]


import unittest

from datetime import timedelta
from pkg_resources import resource_filename
from resolver.config import Configuration


class TestConfiguration(unittest.TestCase):
    def test_basic_ini_file(self):
        # Read a basic .ini file and check that the various attributes and
        # values are correct.
        ini_file = resource_filename('resolver.tests.data', 'config_01.ini')
        config = Configuration(ini_file)
        self.assertEqual(config.service.base, 'https://phablet.stgraber.org')
        self.assertEqual(config.cache.directory, '/var/cache/resolver')
        self.assertEqual(config.cache.lifetime, timedelta(days=14))
        self.assertEqual(config.upgrade.channel, 'stable')
        self.assertEqual(config.upgrade.device, 'nexus7')
