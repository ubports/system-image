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

"""Test helpers."""


__all__ = [
    'TestConverters',
    'TestLastUpdateDate',
    ]


import os
import logging
import unittest

from datetime import datetime, timedelta
from systemimage.config import Configuration, config
from systemimage.helpers import (
    Bag, as_loglevel, as_object, as_timedelta, last_update_date,
    version_detail)
from systemimage.testing.helpers import configuration, data_path, touch_build


class TestConverters(unittest.TestCase):
    def test_as_object_good_path(self):
        self.assertEqual(as_object('systemimage.helpers.Bag'), Bag)

    def test_as_object_no_dot(self):
        self.assertRaises(ValueError, as_object, 'foo')

    def test_as_object_import_error(self):
        # Because as_object() returns a proxy in order to avoid circular
        # imports, we actually have to call the return value of as_object() in
        # order to trigger the module lookup.
        self.assertRaises(
            ImportError,
            as_object('systemimage.doesnotexist.Foo'))

    def test_as_object_attribute_error(self):
        # Because as_object() returns a proxy in order to avoid circular
        # imports, we actually have to call the return value of as_object() in
        # order to trigger the module lookup.
        self.assertRaises(
            AttributeError,
            as_object('systemimage.tests.test_helpers.NoSuchTest'))

    def test_as_timedelta_seconds(self):
        self.assertEqual(as_timedelta('2s'), timedelta(seconds=2))

    def test_as_timedelta_unadorned(self):
        self.assertRaises(ValueError, as_timedelta, '5')

    def test_as_timedelta_minutes(self):
        self.assertEqual(as_timedelta('10m'), timedelta(seconds=600))

    def test_as_timedelta_unknown(self):
        self.assertRaises(ValueError, as_timedelta, '3x')

    def test_as_loglevel(self):
        self.assertEqual(as_loglevel('error'), logging.ERROR)

    def test_as_loglevel_uppercase(self):
        self.assertEqual(as_loglevel('ERROR'), logging.ERROR)

    def test_as_loglevel_unknown(self):
        self.assertRaises(ValueError, as_loglevel, 'BADNESS')


class TestLastUpdateDate(unittest.TestCase):
    @configuration
    def test_date_from_channel_ini(self, ini_file):
        # The last update date can come from the mtime of the channel.ini
        # file, which lives next to the configuration file.
        channel_ini = os.path.join(
            os.path.dirname(ini_file), 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        timestamp = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        os.utime(channel_ini, (timestamp, timestamp))
        self.assertEqual(last_update_date(), '2022-01-02 03:04:05')

    @configuration
    def test_date_from_channel_ini_instead_of_ubuntu_build(self, ini_file):
        # The last update date can come from the mtime of the channel.ini
        # file, which lives next to the configuration file, even when there is
        # an /etc/ubuntu-build file.
        channel_ini = os.path.join(
            os.path.dirname(ini_file), 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        # This creates the ubuntu-build file, but not the channel.ini file.
        timestamp_1 = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        touch_build(2, timestamp_1)
        timestamp_2 = int(datetime(2022, 3, 4, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        self.assertEqual(last_update_date(), '2022-03-04 05:06:07')

    @configuration
    def test_date_fallback(self, ini_file):
        # If the channel.ini file doesn't exist, use the ubuntu-build file.
        channel_ini = os.path.join(
            os.path.dirname(ini_file), 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        # This creates the ubuntu-build file, but not the channel.ini file.
        timestamp_1 = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        touch_build(2, timestamp_1)
        timestamp_2 = int(datetime(2022, 3, 4, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        # Like the above test, but with this file removed.
        os.remove(channel_ini)
        self.assertEqual(last_update_date(), '2022-01-02 03:04:05')

    @configuration
    def test_date_unknown(self, ini_file):
        # No fallbacks.
        config = Configuration()
        config.load(ini_file)
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        self.assertFalse(os.path.exists(channel_ini))
        self.assertFalse(os.path.exists(config.system.build_file))
        self.assertEqual(last_update_date(), 'Unknown')

    @configuration
    def test_date_no_microseconds(self, ini_file):
        # Resolution is seconds.
        channel_ini = os.path.join(
            os.path.dirname(ini_file), 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        timestamp = datetime(2013, 12, 11, 10, 9, 8, 7).timestamp()
        # We need nanoseconds.
        timestamp *= 1000000000
        os.utime(channel_ini, ns=(timestamp, timestamp))
        self.assertEqual(last_update_date(), '2013-12-11 10:09:08')

    @configuration
    def test_version_details(self, ini_file):
        channel_ini = data_path('channel_03.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(version_detail(),
                         dict(ubuntu='123', mako='456', custom='789'))

    @configuration
    def test_no_version_detail(self, ini_file):
        channel_ini = data_path('channel_01.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(version_detail(), {})
