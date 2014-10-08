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

"""Test helpers."""


__all__ = [
    'TestConverters',
    'TestLastUpdateDate',
    'TestMiscellaneous',
    'TestPhasedPercentage',
    'TestSignature',
    ]


import os
import shutil
import hashlib
import logging
import tempfile
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta
from systemimage.bag import Bag
from systemimage.config import Configuration, config
from systemimage.helpers import (
    MiB, NO_PORT, as_loglevel, as_object, as_port, as_stripped, as_timedelta,
    calculate_signature, last_update_date, phased_percentage,
    temporary_directory, version_detail)
from systemimage.testing.helpers import configuration, data_path, touch_build
from unittest.mock import patch


class TestConverters(unittest.TestCase):
    def test_as_object_good_path(self):
        self.assertEqual(as_object('systemimage.bag.Bag'), Bag)

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

    def test_as_object_not_equal(self):
        self.assertNotEqual(as_object('systemimage.bag.Bag'), object())

    def test_as_timedelta_seconds(self):
        self.assertEqual(as_timedelta('2s'), timedelta(seconds=2))

    def test_as_timedelta_unadorned(self):
        self.assertRaises(ValueError, as_timedelta, '5')

    def test_as_timedelta_minutes(self):
        self.assertEqual(as_timedelta('10m'), timedelta(seconds=600))

    def test_as_timedelta_unknown(self):
        self.assertRaises(ValueError, as_timedelta, '3x')

    def test_as_timedelta_no_keywords(self):
        self.assertRaises(ValueError, as_timedelta, '')

    def test_as_timedelta_repeated_interval(self):
        self.assertRaises(ValueError, as_timedelta, '2s2s')

    def test_as_timedelta_float(self):
        self.assertEqual(as_timedelta('0.5d'), timedelta(hours=12))

    def test_as_loglevel(self):
        # The default D-Bus log level is ERROR.
        self.assertEqual(as_loglevel('critical'),
                         (logging.CRITICAL, logging.ERROR))

    def test_as_loglevel_uppercase(self):
        self.assertEqual(as_loglevel('CRITICAL'),
                         (logging.CRITICAL, logging.ERROR))

    def test_as_dbus_loglevel(self):
        self.assertEqual(as_loglevel('error:info'),
                         (logging.ERROR, logging.INFO))

    def test_as_loglevel_unknown(self):
        self.assertRaises(ValueError, as_loglevel, 'BADNESS')

    def test_as_bad_dbus_loglevel(self):
        self.assertRaises(ValueError, as_loglevel, 'error:basicConfig')

    def test_as_port(self):
        self.assertEqual(as_port('801'), 801)

    def test_as_non_int_port(self):
        self.assertRaises(ValueError, as_port, 'not-a-port')

    def test_as_port_disabled(self):
        self.assertIs(as_port('disabled'), NO_PORT)
        self.assertIs(as_port('disable'), NO_PORT)
        self.assertIs(as_port('DISABLED'), NO_PORT)
        self.assertIs(as_port('DISABLE'), NO_PORT)

    def test_stripped(self):
        self.assertEqual(as_stripped('   field   '), 'field')


class TestLastUpdateDate(unittest.TestCase):
    @configuration
    def test_date_from_userdata(self):
        # The last upgrade data can come from /userdata/.last_update.
        with ExitStack() as stack:
            tmpdir = stack.enter_context(temporary_directory())
            userdata_path = os.path.join(tmpdir, '.last_update')
            stack.enter_context(patch('systemimage.helpers.LAST_UPDATE_FILE',
                                      userdata_path))
            timestamp = int(datetime(2012, 11, 10, 9, 8, 7).timestamp())
            with open(userdata_path, 'w'):
                # i.e. touch(1)
                pass
            os.utime(userdata_path, (timestamp, timestamp))
            self.assertEqual(last_update_date(), '2012-11-10 09:08:07')

    @configuration
    def test_date_from_channel_ini(self, config_d):
        # The last update date can come from the mtime of the channel.ini
        # file, which lives next to the configuration file.
        channel_ini = os.path.join(
            os.path.dirname(config_d), 'channel.ini')
        with open(channel_ini, 'w'):
            pass
        timestamp = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        os.utime(channel_ini, (timestamp, timestamp))
        self.assertEqual(last_update_date(), '2022-01-02 03:04:05')

    @configuration
    def test_date_from_channel_ini_instead_of_ubuntu_build(self, config_d):
        # The last update date can come from the mtime of the channel.ini
        # file, which lives next to the configuration file, even when there is
        # an /etc/ubuntu-build file.
        channel_ini = os.path.join(
            os.path.dirname(config_d), 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        # This creates the ubuntu-build file, but not the channel.ini file.
        timestamp_1 = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        touch_build(2, timestamp_1)
        timestamp_2 = int(datetime(2022, 3, 4, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        self.assertEqual(last_update_date(), '2022-03-04 05:06:07')

    @configuration
    def test_date_fallback(self, config_d):
        # If the channel.ini file doesn't exist, use the ubuntu-build file.
        channel_ini = os.path.join(
            os.path.dirname(config_d), 'channel.ini')
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
    def test_date_unknown(self, config_d):
        # No fallbacks.
        config = Configuration(config_d)
        channel_ini = os.path.join(config_d, 'channel.ini')
        self.assertFalse(os.path.exists(channel_ini))
        self.assertFalse(os.path.exists(config.system.build_file))
        self.assertEqual(last_update_date(), 'Unknown')

    @configuration
    def test_date_no_microseconds(self, config_d):
        # Resolution is seconds.
        channel_ini = os.path.join(config_d, 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        timestamp = datetime(2013, 12, 11, 10, 9, 8, 7).timestamp()
        # We need nanoseconds.
        timestamp *= 1000000000
        os.utime(channel_ini, ns=(timestamp, timestamp))
        self.assertEqual(last_update_date(), '2013-12-11 10:09:08')

    @configuration
    def test_version_detail(self):
        channel_ini = data_path('channel_03.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(version_detail(),
                         dict(ubuntu='123', mako='456', custom='789'))

    @configuration
    def test_no_version_detail(self):
        channel_ini = data_path('channel_01.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(version_detail(), {})

    def test_version_detail_from_argument(self):
        self.assertEqual(version_detail('ubuntu=123,mako=456,custom=789'),
                         dict(ubuntu='123', mako='456', custom='789'))

    def test_no_version_in_version_detail(self):
        self.assertEqual(version_detail('ubuntu,mako,custom'), {})

    @configuration
    def test_date_from_userdata_ignoring_fallbacks(self, config_d):
        # Even when /etc/system-image/channel.ini and /etc/ubuntu-build exist,
        # if there's a /userdata/.last_update file, that takes precedence.
        with ExitStack() as stack:
            # /userdata/.last_update
            tmpdir = stack.enter_context(temporary_directory())
            userdata_path = os.path.join(tmpdir, '.last_update')
            stack.enter_context(patch('systemimage.helpers.LAST_UPDATE_FILE',
                                      userdata_path))
            with open(userdata_path, 'w'):
                # i.e. touch(1)
                pass
            timestamp = int(datetime(2010, 9, 8, 7, 6, 5).timestamp())
            os.utime(userdata_path, (timestamp, timestamp))
            # /etc/channel.ini
            channel_ini = os.path.join(config_d, 'channel.ini')
            with open(channel_ini, 'w'):
                pass
            timestamp = int(datetime(2011, 10, 9, 8, 7, 6).timestamp())
            os.utime(channel_ini, (timestamp, timestamp))
            # /etc/ubuntu-build.
            timestamp = int(datetime(2012, 11, 10, 9, 8, 7).timestamp())
            touch_build(2, timestamp)
            # Run the test.
            self.assertEqual(last_update_date(), '2010-09-08 07:06:05')

    @configuration
    def test_last_date_no_permission(self, config_d):
        # LP: #1365761 reports a problem where stat'ing /userdata/.last_update
        # results in a PermissionError.  In that case it should just use a
        # fall back, in this case the channel.ini file.
        channel_ini = os.path.join(config_d, 'channel.ini')
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        # This creates the ubuntu-build file, but not the channel.ini file.
        timestamp_1 = int(datetime(2022, 1, 2, 3, 4, 5).timestamp())
        touch_build(2, timestamp_1)
        # Now, the channel.ini file.
        timestamp_2 = int(datetime(2022, 3, 4, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        # Now create an stat'able /userdata/.last_update file.
        with ExitStack() as stack:
            tmpdir = stack.enter_context(temporary_directory())
            userdata_path = os.path.join(tmpdir, '.last_update')
            stack.enter_context(patch('systemimage.helpers.LAST_UPDATE_FILE',
                                      userdata_path))
            timestamp = int(datetime(2012, 11, 10, 9, 8, 7).timestamp())
            with open(userdata_path, 'w'):
                # i.e. touch(1)
                pass
            os.utime(userdata_path, (timestamp, timestamp))
            # Make the file unreadable.
            stack.callback(os.chmod, tmpdir, 0o777)
            os.chmod(tmpdir, 0o000)
            # The last update date will be the date of the channel.ini file.
            self.assertEqual(last_update_date(), '2022-03-04 05:06:07')


class TestPhasedPercentage(unittest.TestCase):
    def setUp(self):
        phased_percentage(reset=True)

    def tearDown(self):
        phased_percentage(reset=True)

    def test_phased_percentage(self):
        # This function returns a percentage between 0 and 100.  If this value
        # is greater than a similar value in the index.json's 'image' section,
        # that image is completely ignored.
        with ExitStack() as stack:
            tmpdir = stack.enter_context(temporary_directory())
            path = os.path.join(tmpdir, 'machine-id')
            stack.enter_context(patch(
                'systemimage.helpers.UNIQUE_MACHINE_ID_FILE',
                path))
            stack.enter_context(patch(
                'systemimage.helpers.time.time',
                return_value=1380659512.983512))
            with open(path, 'wb') as fp:
                fp.write(b'0123456789abcdef\n')
            self.assertEqual(phased_percentage(), 81)
            # The value is cached, so it's always the same for the life of the
            # process, at least until we reset it.
            self.assertEqual(phased_percentage(), 81)

    def test_phased_percentage_reset(self):
        # Test the reset API.
        with ExitStack() as stack:
            tmpdir = stack.enter_context(temporary_directory())
            path = os.path.join(tmpdir, 'machine-id')
            stack.enter_context(patch(
                'systemimage.helpers.UNIQUE_MACHINE_ID_FILE',
                path))
            stack.enter_context(patch(
                'systemimage.helpers.time.time',
                return_value=1380659512.983512))
            with open(path, 'wb') as fp:
                fp.write(b'0123456789abcdef\n')
            self.assertEqual(phased_percentage(), 81)
            # The value is cached, so it's always the same for the life of the
            # process, at least until we reset it.
            with open(path, 'wb') as fp:
                fp.write(b'x0123456789abcde\n')
            self.assertEqual(phased_percentage(reset=True), 81)
            # The next one will have a different value.
            self.assertEqual(phased_percentage(), 17)


class TestSignature(unittest.TestCase):
    def test_calculate_signature(self):
        # Check the default hash algorithm.
        with tempfile.TemporaryFile() as fp:
            # Ensure the file is bigger than chunk size.
            fp.write(b'\0' * (MiB + 1))
            fp.seek(0)
            hash1 = calculate_signature(fp)
            fp.seek(0)
            hash2 = hashlib.sha256(fp.read()).hexdigest()
            self.assertEqual(hash1, hash2)

    def test_calculate_signature_alternative_hash(self):
        # Check an alternative hash algorithm.
        with tempfile.TemporaryFile() as fp:
            # Ensure the file is bigger than chunk size.
            fp.write(b'\0' * (MiB + 1))
            fp.seek(0)
            hash1 = calculate_signature(fp, hashlib.md5)
            fp.seek(0)
            hash2 = hashlib.md5(fp.read()).hexdigest()
            self.assertEqual(hash1, hash2)

    def test_calculate_signature_chunk_size(self):
        # Check that a file of exactly the chunk size works.
        with tempfile.TemporaryFile() as fp:
            fp.write(b'\0' * MiB)
            fp.seek(0)
            hash1 = calculate_signature(fp)
            fp.seek(0)
            hash2 = hashlib.sha256(fp.read()).hexdigest()
            self.assertEqual(hash1, hash2)


class TestMiscellaneous(unittest.TestCase):
    def test_temporary_directory_finally_test_coverage(self):
        with temporary_directory() as path:
            shutil.rmtree(path)
            self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(path))
