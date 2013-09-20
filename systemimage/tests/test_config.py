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


import logging
import unittest

from datetime import timedelta
from pkg_resources import resource_filename
from systemimage.config import Configuration
from systemimage.device import SystemProperty
from systemimage.reboot import Reboot
from systemimage.scores import WeightedScorer
from systemimage.testing.helpers import configuration, data_path, touch_build
from unittest.mock import patch


class TestConfiguration(unittest.TestCase):
    def test_defaults(self):
        default_ini = resource_filename('systemimage.data', 'client.ini')
        config = Configuration()
        config.load(default_ini)
        # [service]
        self.assertEqual(config.service.base, 'system-image.ubuntu.com')
        self.assertEqual(config.service.http_base,
                         'http://system-image.ubuntu.com')
        self.assertEqual(config.service.https_base,
                         'https://system-image.ubuntu.com')
        self.assertEqual(config.service.channel, 'daily')
        self.assertEqual(config.service.build_number, 0)
        # [system]
        self.assertEqual(config.system.tempdir, '/tmp/system-image')
        self.assertEqual(config.system.build_file, '/etc/ubuntu-build')
        self.assertEqual(config.system.logfile,
                         '/var/log/system-image/client.log')
        self.assertEqual(config.system.loglevel, logging.ERROR)
        self.assertEqual(config.system.state_file,
                         '/var/lib/system-image/state.pck')
        self.assertEqual(config.system.settings_db,
                         '/var/lib/system-image/settings.db')
        # [hooks]
        self.assertEqual(config.hooks.device, SystemProperty)
        self.assertEqual(config.hooks.scorer, WeightedScorer)
        self.assertEqual(config.hooks.reboot, Reboot)
        # [gpg]
        self.assertEqual(config.gpg.archive_master,
                         '/etc/system-image/archive-master.tar.xz')
        self.assertEqual(
            config.gpg.image_master,
            '/var/lib/system-image/keyrings/image-master.tar.xz')
        self.assertEqual(
            config.gpg.image_signing,
            '/var/lib/system-image/keyrings/image-signing.tar.xz')
        self.assertEqual(
            config.gpg.device_signing,
            '/var/lib/system-image/keyrings/device-signing.tar.xz')
        # [updater]
        self.assertEqual(config.updater.cache_partition,
                         '/android/cache/recovery')
        self.assertEqual(config.updater.data_partition,
                         '/var/lib/system-image')
        # [dbus]
        self.assertEqual(config.dbus.lifetime.total_seconds(), 600)

    def test_basic_ini_file(self):
        # Read a basic .ini file and check that the various attributes and
        # values are correct.
        ini_file = data_path('config_01.ini')
        config = Configuration()
        config.load(ini_file)
        # [service]
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.service.http_base,
                         'http://phablet.example.com')
        self.assertEqual(config.service.https_base,
                         'https://phablet.example.com')
        self.assertEqual(config.service.channel, 'stable')
        self.assertEqual(config.service.build_number, 0)
        # [system]
        self.assertEqual(config.system.tempdir, '/var/tmp/system-image-update')
        self.assertEqual(config.system.build_file, '/etc/ubuntu-build')
        self.assertEqual(config.system.logfile,
                         '/var/log/system-image/client.log')
        self.assertEqual(config.system.loglevel, logging.ERROR)
        self.assertEqual(config.system.state_file,
                         '/var/lib/phablet/state.pck')
        self.assertEqual(config.system.settings_db,
                         '/var/lib/phablet/settings.db')
        self.assertEqual(config.system.threads, 5)
        self.assertEqual(config.system.timeout, timedelta(seconds=10))
        # [hooks]
        self.assertEqual(config.hooks.device, SystemProperty)
        self.assertEqual(config.hooks.scorer, WeightedScorer)
        self.assertEqual(config.hooks.reboot, Reboot)
        # [gpg]
        self.assertEqual(config.gpg.archive_master,
                         '/etc/phablet/archive-master.tar.xz')
        self.assertEqual(config.gpg.image_master,
                         '/etc/phablet/image-master.tar.xz')
        self.assertEqual(config.gpg.image_signing,
                         '/var/lib/phablet/image-signing.tar.xz')
        self.assertEqual(config.gpg.device_signing,
                         '/var/lib/phablet/device-signing.tar.xz')
        # [updater]
        self.assertEqual(config.updater.cache_partition, '/android/cache')
        self.assertEqual(config.updater.data_partition,
                         '/var/lib/phablet/updater')
        # [dbus]
        self.assertEqual(config.dbus.lifetime.total_seconds(), 120)

    def test_nonstandard_ports(self):
        # config_02.ini has non-standard http and https ports.
        ini_file = data_path('config_02.ini')
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.service.http_base,
                         'http://phablet.example.com:8080')
        self.assertEqual(config.service.https_base,
                         'https://phablet.example.com:80443')

    @configuration
    def test_get_build_number(self, ini_file):
        # The current build number is stored in a file specified in the
        # configuration file.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130500)
        self.assertEqual(config.build_number, 20130500)

    @configuration
    def test_get_build_number_missing(self, ini_file):
        # The build file is missing, so the build number defaults to 0.
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.build_number, 0)

    @configuration
    def test_get_device_name(self, ini_file):
        config = Configuration()
        config.load(ini_file)
        # The device name as we'd expect it to work on a real image.
        with patch('systemimage.device.check_output', return_value='nexus7'):
            self.assertEqual(config.device, 'nexus7')
            # Get it again to test out the cache.
            self.assertEqual(config.device, 'nexus7')

    def test_get_device_name_fallback(self):
        # Fallback for testing on non-images.
        config = Configuration()
        # Silence the log exceptions this will provoke.
        with patch('systemimage.device.logging.getLogger'):
            self.assertEqual(config.device, '?')

    @configuration
    def test_get_channel(self, ini_file):
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.channel, 'stable')

    @configuration
    def test_overrides(self, ini_file):
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.build_number, 0)
        self.assertEqual(config.device, 'nexus7')
        self.assertEqual(config.channel, 'stable')
        config.build_number = 20250801
        config.device = 'phablet'
        config.channel = 'daily-proposed'
        self.assertEqual(config.build_number, 20250801)
        self.assertEqual(config.device, 'phablet')
        self.assertEqual(config.channel, 'daily-proposed')

    def test_bad_override(self):
        config = Configuration()
        with self.assertRaises(ValueError) as cm:
            # Looks like an int, but isn't.
            config.build_number = '20150801'
        self.assertEqual(str(cm.exception), 'integer is required, got: str')

    def test_reset_build_number(self):
        config = Configuration()
        old_build = config.build_number
        self.assertEqual(old_build, 0)
        config.build_number = 20990000
        self.assertEqual(config.build_number, 20990000)
        del config.build_number
        self.assertEqual(config.build_number, 0)
        config.build_number = 21000000
        self.assertEqual(config.build_number, 21000000)

    def test_channel_ini_overrides(self):
        # If a /etc/system-image/channels.ini file exists, it overrides any
        # previously set options.
        default_ini = resource_filename('systemimage.data', 'client.ini')
        config = Configuration()
        config.load(default_ini)
        # [service]
        self.assertEqual(config.service.base, 'system-image.ubuntu.com')
        self.assertEqual(config.service.http_base,
                         'http://system-image.ubuntu.com')
        self.assertEqual(config.service.https_base,
                         'https://system-image.ubuntu.com')
        self.assertEqual(config.service.channel, 'daily')
        self.assertEqual(config.service.build_number, 0)
        # Load the overrides.
        channel_ini = resource_filename(
            'systemimage.tests.data', 'channel_01.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(config.service.base, 'systum-imaje.ubuntu.com')
        self.assertEqual(config.service.http_base,
                         'http://systum-imaje.ubuntu.com:88')
        self.assertEqual(config.service.https_base,
                         'https://systum-imaje.ubuntu.com:89')
        self.assertEqual(config.service.channel, 'proposed')
        self.assertEqual(config.service.build_number, 20130833)

    def test_channel_ini_ignored_sections(self):
        # Only the [service] section in channel.ini is used.
        default_ini = resource_filename('systemimage.data', 'client.ini')
        config = Configuration()
        config.load(default_ini)
        channel_ini = resource_filename(
            'systemimage.tests.data', 'channel_02.ini')
        config.load(channel_ini, override=True)
        self.assertEqual(config.system.build_file, '/etc/ubuntu-build')
