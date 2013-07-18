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

"""Test the SystemImage dbus service."""

__all__ = [
    'TestDBus',
    ]


import dbus
import unittest

from contextlib import ExitStack
from systemimage.config import Configuration
from systemimage.helpers import safe_remove
from systemimage.testing.dbus import Controller


_controller = None
_stack = ExitStack()


def setUpModule():
    global _controller
    _controller = Controller()
    _stack.callback(_controller.shutdown)
    _controller.start()


def tearDownModule():
    global _controller
    _stack.close()
    _controller = None


class TestDBus(unittest.TestCase):
    """Test the SystemImage dbus service."""

    def setUp(self):
        session_bus = dbus.SessionBus()
        service = session_bus.get_object(
            'com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        # We need a configuration file that agrees with the dbus client.
        self.config = Configuration()
        self.config.load(_controller.ini_path)

    def tearDown(self):
        safe_remove(self.config.system.build_file)

    def test_check_build_number(self):
        # Get the build number.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertEqual(self.iface.BuildNumber(), 20130701)

    def test_update_available(self):
        # There is an update available.
        self.assertTrue(self.iface.IsUpdateAvailable())

    def test_no_update_available(self):
        # Our device is newer than the version that's available.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(self.iface.IsUpdateAvailable())
