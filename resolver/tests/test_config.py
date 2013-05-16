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
from resolver.config import Configuration, config
from resolver.tests.helpers import testable_configuration


class TestConfiguration(unittest.TestCase):
    def test_defaults(self):
        config = Configuration()
        self.assertEqual(config.service.base, 'phablet.stgraber.org')
        self.assertEqual(config.service.http_base,
                         'http://phablet.stgraber.org')
        self.assertEqual(config.service.https_base,
                         'https://phablet.stgraber.org')
        self.assertEqual(config.system.tempdir,
                         os.path.expanduser('~/.cache/phablet'))
        self.assertEqual(config.system.channel, 'stable')
        self.assertEqual(config.system.device, 'nexus7')

    def test_basic_ini_file(self):
        # Read a basic .ini file and check that the various attributes and
        # values are correct.
        ini_file = resource_filename('resolver.tests.data', 'config_01.ini')
        config = Configuration()
        config.load(ini_file)
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.service.http_base,
                         'http://phablet.example.com')
        self.assertEqual(config.service.https_base,
                         'https://phablet.example.com')
        self.assertEqual(config.service.threads, 5)
        self.assertEqual(config.service.timeout, timedelta(seconds=10))
        self.assertEqual(config.system.tempdir, '/var/tmp/resolver')
        self.assertEqual(config.system.channel, 'stable')
        self.assertEqual(config.system.device, 'nexus7')

    def test_nonstandard_ports(self):
        # config_02.ini has non-standard http and https ports.
        ini_file = resource_filename('resolver.tests.data', 'config_02.ini')
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
        self.assertEqual(config.get_build_number(), 20130500)

    def test_get_build_number_missing(self):
        # The build file is missing, so the build number defaults to 0.
        self.assertEqual(config.get_build_number(), 0)
