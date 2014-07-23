# Copyright (C) 2013-2014 Canonical Ltd.
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

"""Test persistent settings."""

__all__ = [
    'TestSettings',
    ]


import os
import unittest

from systemimage.config import Configuration
from systemimage.settings import Settings
from systemimage.testing.helpers import configuration


class TestSettings(unittest.TestCase):
    @configuration
    def test_creation(self, ini_file):
        config = Configuration(ini_file)
        self.assertFalse(os.path.exists(config.system.settings_db))
        settings = Settings()
        self.assertTrue(os.path.exists(config.system.settings_db))
        del settings
        # The file still exists.
        self.assertTrue(os.path.exists(config.system.settings_db))
        Settings()
        self.assertTrue(os.path.exists(config.system.settings_db))

    @configuration
    def test_get_set(self):
        settings = Settings()
        settings.set('permanent', 'waves')
        self.assertEqual(settings.get('permanent'), 'waves')

    @configuration
    def test_delete(self):
        # Keys can be deleted.
        settings = Settings()
        settings.set('moving', 'pictures')
        self.assertEqual(settings.get('moving'), 'pictures')
        settings.delete('moving')
        # The empty string is the default.
        self.assertEqual(settings.get('moving'), '')

    @configuration
    def test_delete_missing(self):
        # Nothing much happens if you ask to delete a missing key.
        settings = Settings()
        settings.delete('missing')
        self.assertEqual(settings.get('missing'), '')

    @configuration
    def test_update(self):
        settings = Settings()
        settings.set('animal', 'ant')
        self.assertEqual(settings.get('animal'), 'ant')
        settings.set('animal', 'bee')
        self.assertEqual(settings.get('animal'), 'bee')

    @configuration
    def test_get_before_set(self):
        settings = Settings()
        self.assertEqual(settings.get('nothing'), '')

    @configuration
    def test_persistence(self):
        settings = Settings()
        settings.set('animal', 'cat')
        del settings
        self.assertEqual(Settings().get('animal'), 'cat')

    @configuration
    def test_prepopulated(self):
        # Some keys are pre-populated with default values.
        self.assertEqual(Settings().get('auto_download'), '1')

    @configuration
    def test_iterate(self):
        # Iterate over all keys.
        settings = Settings()
        settings.set('a', 'ant')
        settings.set('b', 'bee')
        settings.set('c', 'cat')
        keyval = list(settings)
        keyval.sort()
        self.assertEqual(keyval, [('a', 'ant'), ('b', 'bee'), ('c', 'cat')])
