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
    'TestDBusDescriptions',
    ]


import os
import dbus
import unittest

from contextlib import ExitStack
from systemimage.config import Configuration
from systemimage.helpers import safe_remove
from systemimage.testing.controller import Controller


class TestDBus(unittest.TestCase):
    """Test the SystemImage dbus service."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        cls._controller = Controller()
        cls._stack.callback(cls._controller.shutdown)
        cls._controller.start()

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()
        cls._controller = None

    def setUp(self):
        self._controller.prepare_index('index_13.json')
        session_bus = dbus.SessionBus()
        service = session_bus.get_object(
            'com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        # We need a configuration file that agrees with the dbus client.
        self.config = Configuration()
        self.config.load(self._controller.ini_path)
        # For testing reboot preparation.
        self.command_file = os.path.join(
            self.config.updater.cache_partition, 'ubuntu_command')
        # For testing the reboot command without actually rebooting.
        self.reboot_log = os.path.join(
            self.config.updater.cache_partition, 'reboot.log')

    def tearDown(self):
        safe_remove(self.config.system.build_file)
        safe_remove(self.command_file)
        safe_remove(self.reboot_log)

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

    def test_get_update_size(self):
        # Check for an update and if one is available, get the size.
        self.assertTrue(self.iface.IsUpdateAvailable())
        self.assertEqual(self.iface.GetUpdateSize(), 314572800)

    def test_get_no_update_size(self):
        # No update is available, but the client still asks for the size.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(self.iface.IsUpdateAvailable())
        self.assertEqual(self.iface.GetUpdateSize(), 0)

    def test_get_update_size_without_check(self):
        # Getting the update size implies a check.
        self.assertEqual(self.iface.GetUpdateSize(), 314572800)

    def test_get_update_size_without_check_none_available(self):
        # No explicit check for update, and none is available.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertEqual(self.iface.GetUpdateSize(), 0)

    def test_get_available_version(self):
        # An update is available, so get the target version.
        self.assertTrue(self.iface.IsUpdateAvailable())
        self.assertEqual(self.iface.GetUpdateVersion(), 20130600)

    def test_get_available_version_without_check(self):
        # Getting the target version implies a check.
        self.assertEqual(self.iface.GetUpdateVersion(), 20130600)

    def test_get_no_available_version(self):
        # No update is available, but the client still asks for the version.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(self.iface.IsUpdateAvailable())
        self.assertEqual(self.iface.GetUpdateVersion(), 0)

    def test_get_available_version_without_check_none_available(self):
        # No explicit check for update, none is available.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertEqual(self.iface.GetUpdateVersion(), 0)

    def test_get_descriptions(self):
        # An update is available, with descriptions.
        self.assertTrue(self.iface.IsUpdateAvailable())
        self.assertEqual(self.iface.GetDescriptions(),
                         [{'description': 'Full'}])

    def test_get_descriptions_no_check(self):
        # Getting the descriptions implies a check.
        self.assertEqual(self.iface.GetDescriptions(),
                         [{'description': 'Full'}])

    def test_get_no_available_descriptions(self):
        # No update is available, so there are no descriptions.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(self.iface.IsUpdateAvailable())
        self.assertEqual(len(self.iface.GetDescriptions()), 0)

    def test_get_no_available_descriptions_without_check(self):
        # No explicit check for update, none is available.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertEqual(len(self.iface.GetDescriptions()), 0)

    def test_get_multilingual_descriptions(self):
        # The descriptions are multilingual.
        self._controller.prepare_index('index_14.json')
        self.assertEqual(self.iface.GetDescriptions(), [
            {'description': 'Full B',
             'description-en': 'The full B',
            },
            {'description': 'Delta B.1',
             'description-en_US': 'This is the delta B.1',
             'description-xx': 'XX This is the delta B.1',
             'description-yy': 'YY This is the delta B.1',
             'description-yy_ZZ': 'YY-ZZ This is the delta B.1',
            },
            {'description': 'Delta B.2',
             'description-xx': 'Oh delta, my delta',
             'description-xx_CC': 'This hyar is the delta B.2',
            }])

    def test_complete_update(self):
        # Complete the update; up until the reboot call.
        self.assertTrue(self.iface.IsUpdateAvailable())
        self.assertFalse(os.path.exists(self.command_file))
        self.iface.GetUpdate()
        with open(self.command_file, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
format system
mount system
update 6.txt 6.txt.asc
update 7.txt 7.txt.asc
update 5.txt 5.txt.asc
unmount system
""")

    def test_no_update_to_complete(self):
        # Complete the update; up until the reboot call.
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(os.path.exists(self.command_file))
        self.iface.GetUpdate()
        self.assertFalse(os.path.exists(self.command_file))

    def test_reboot(self):
        # Do the reboot.
        self.assertFalse(os.path.exists(self.reboot_log))
        self.assertTrue(self.iface.IsUpdateAvailable())
        self.iface.Reboot()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, 'reboot -f recovery')

    def test_reboot_no_update(self):
        # There's no update to reboot to.
        self.assertFalse(os.path.exists(self.reboot_log))
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(20130701, file=fp)
        self.assertFalse(self.iface.IsUpdateAvailable())
        self.iface.Reboot()
        self.assertFalse(os.path.exists(self.reboot_log))
