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


import os
import unittest

from datetime import timedelta
from pkg_resources import resource_filename
from systemimage.config import Configuration, config
from systemimage.reboot import Reboot
from systemimage.scores import WeightedScorer
from systemimage.tests.helpers import test_data_path, testable_configuration
from systemimage.tests.reboot import TestableReboot


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
        # [system]
        self.assertEqual(config.system.tempdir, '/tmp/system-image')
        self.assertEqual(config.system.channel, 'daily')
        self.assertEqual(config.system.device, 'mako')
        # [score]
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

    def test_basic_ini_file(self):
        # Read a basic .ini file and check that the various attributes and
        # values are correct.
        ini_file = test_data_path('config_01.ini')
        config = Configuration()
        config.load(ini_file)
        # [service]
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.service.http_base,
                         'http://phablet.example.com')
        self.assertEqual(config.service.https_base,
                         'https://phablet.example.com')
        self.assertEqual(config.service.threads, 5)
        self.assertEqual(config.service.timeout, timedelta(seconds=10))
        # [system]
        self.assertEqual(config.system.tempdir, '/var/tmp/system-image-update')
        self.assertEqual(config.system.channel, 'stable')
        self.assertEqual(config.system.device, 'nexus7')
        # [hooks]
        self.assertEqual(config.hooks.scorer, WeightedScorer)
        self.assertEqual(config.hooks.reboot, TestableReboot)
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

    def test_nonstandard_ports(self):
        # config_02.ini has non-standard http and https ports.
        ini_file = test_data_path('config_02.ini')
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.service.http_base,
                         'http://phablet.example.com:8080')
        self.assertEqual(config.service.https_base,
                         'https://phablet.example.com:80443')

    @testable_configuration
    def test_get_build_number(self):
        # The current build number is stored in a file specified in the
        # configuration file.
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130500, file=fp)
        self.assertEqual(config.build_number, 20130500)

    def test_get_build_number_missing(self):
        # The build file is missing, so the build number defaults to 0.
        self.assertEqual(config.build_number, 0)
