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
    'TestDBusMocksNoUpdate',
    'TestDBusMocksUpdateAvailable',
    'TestDBusMocksUpdateFailed',
    ]


import os
import dbus
import unittest

from contextlib import ExitStack
from dbus.exceptions import DBusException
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from systemimage.config import Configuration
from systemimage.helpers import safe_remove
from systemimage.testing.controller import Controller
from systemimage.testing.helpers import (
    copy, make_http_server, setup_index, setup_keyring_txz, setup_keyrings,
    sign)


# 2013-07-25 BAW: This is an ugly hack caused by a weird problem I have not
# been able to track down.  LP: #1205163
_WHICH = 1


class _TestBase(unittest.TestCase):
    """Base class for all DBus testing."""

    # Override this to start the DBus server in a different testing mode.
    mode = 'live'

    @classmethod
    def setUpClass(cls):
        cls._stack = ExitStack()
        cls._controller = Controller(cls.mode)
        cls._stack.callback(cls._controller.shutdown)
        cls._controller.start()
        DBusGMainLoop(set_as_default=True)

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()
        cls._controller = None

    def setUp(self):
        self.session_bus = dbus.SessionBus()
        service = self.session_bus.get_object(
            'com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')

    def tearDown(self):
        self.iface.Reset()

    def _run_loop(self, method, signal):
        loop = GLib.MainLoop()
        # Here's the callback for when dbus receives the signal.
        signals = []
        def callback(*args):
            signals.append(args)
            loop.quit()
        self.session_bus.add_signal_receiver(
            callback, signal_name=signal,
            dbus_interface='com.canonical.SystemImage')
        GLib.timeout_add(100, method)
        GLib.timeout_add_seconds(10, loop.quit)
        loop.run()
        return signals


@unittest.skipUnless(_WHICH == 1, 'TEST 1 - LP: #1205163')
class TestDBus(_TestBase):
    """Test the SystemImage dbus service."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Set up the http/https servers that the dbus client will talk to.
        # Start up both an HTTPS and HTTP server.  The data files are vended
        # over the latter, everything else, over the former.
        serverdir = cls._controller.serverdir
        cls._stack.push(make_http_server(
            serverdir, 8943, 'cert.pem', 'key.pem'))
        cls._stack.push(make_http_server(serverdir, 8980))
        # Set up the server files.
        copy('channels_06.json', serverdir, 'channels.json')
        sign(os.path.join(serverdir, 'channels.json'), 'image-signing.gpg')
        # Only the archive-master key is pre-loaded.  All the other keys are
        # downloaded and there will be both a blacklist and device keyring.
        # The four signed keyring tar.xz files and their signatures end up in
        # the proper location after the state machine runs to completion.
        config = Configuration()
        config.load(cls._controller.ini_path)
        setup_keyrings('archive-master', use_config=config)
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(serverdir, 'gpg', 'image-signing.tar.xz'))
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(serverdir, 'stable', 'nexus7',
                         'device-signing.tar.xz'))

    def setUp(self):
        super().setUp()
        self._prepare_index('index_13.json')
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
        super().tearDown()

    def _prepare_index(self, index_file):
        index_path = os.path.join(
            self._controller.serverdir, 'stable', 'nexus7', 'index.json')
        head, tail = os.path.split(index_path)
        copy(index_file, head, tail)
        sign(index_path, 'device-signing.gpg')
        setup_index(
            index_file, self._controller.serverdir, 'device-signing.gpg')

    def _set_build(self, version):
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(version, file=fp)

    def test_check_build_number(self):
        # Get the build number.
        self._set_build(20130701)
        self.assertEqual(self.iface.BuildNumber(), 20130701)

    def test_update_available(self):
        # There is an update available.
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        self.assertTrue(signals[0][0])

    def test_no_update_available(self):
        # Our device is newer than the version that's available.
        self._set_build(20130701)
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        self.assertFalse(signals[0][0])

    def test_get_update_size(self):
        # Check for an update and if one is available, get the size.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(self.iface.GetUpdateSize(), 314572800)

    def test_get_no_update_size(self):
        # No update is available, but the client still asks for the size.
        self._set_build(20130701)
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(self.iface.GetUpdateSize(), 0)

    def test_get_update_size_without_check(self):
        # Getting the update size implies a check.
        self.assertEqual(self.iface.GetUpdateSize(), 314572800)

    def test_get_update_size_without_check_none_available(self):
        # No explicit check for update, and none is available.
        self._set_build(20130701)
        self.assertEqual(self.iface.GetUpdateSize(), 0)

    def test_get_available_version(self):
        # An update is available, so get the target version.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(self.iface.GetUpdateVersion(), 20130600)

    def test_get_available_version_without_check(self):
        # Getting the target version implies a check.
        self.assertEqual(self.iface.GetUpdateVersion(), 20130600)

    def test_get_no_available_version(self):
        # No update is available, but the client still asks for the version.
        self._set_build(20130701)
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(self.iface.GetUpdateVersion(), 0)

    def test_get_available_version_without_check_none_available(self):
        # No explicit check for update, none is available.
        self._set_build(20130701)
        self.assertEqual(self.iface.GetUpdateVersion(), 0)

    def test_get_descriptions(self):
        # An update is available, with descriptions.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(self.iface.GetDescriptions(),
                         [{'description': 'Full'}])

    def test_get_descriptions_no_check(self):
        # Getting the descriptions implies a check.
        self.assertEqual(self.iface.GetDescriptions(),
                         [{'description': 'Full'}])

    def test_get_no_available_descriptions(self):
        # No update is available, so there are no descriptions.
        self._set_build(20130701)
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(self.iface.GetDescriptions()), 0)

    def test_get_no_available_descriptions_without_check(self):
        # No explicit check for update, none is available.
        self._set_build(20130701)
        self.assertEqual(len(self.iface.GetDescriptions()), 0)

    def test_get_multilingual_descriptions(self):
        # The descriptions are multilingual.
        self._prepare_index('index_14.json')
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
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertFalse(os.path.exists(self.command_file))
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
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
        self._set_build(20130701)
        self.assertFalse(os.path.exists(self.command_file))
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.assertFalse(os.path.exists(self.command_file))

    def test_reboot(self):
        # Do the reboot.
        self.assertFalse(os.path.exists(self.reboot_log))
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.iface.Reboot()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, 'reboot -f recovery')

    def test_reboot_no_update(self):
        # There's no update to reboot to.
        self.assertFalse(os.path.exists(self.reboot_log))
        self._set_build(20130701)
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.iface.Reboot()
        self.assertFalse(os.path.exists(self.reboot_log))

    def test_ready_to_reboot_signal(self):
        # A signal is issued when the client is ready to reboot.
        signals = self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.assertEqual(len(signals), 1)

    def test_update_failed_signal(self):
        # A signal is issued when the update failed.
        #
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(self._controller.serverdir, '4/5/6.txt.asc'))
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)

    def test_reboot_after_update_failed(self):
        # Cause the update to fail by deleting a file from the server.
        #
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(self._controller.serverdir, '4/5/6.txt.asc'))
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)
        signals = self._run_loop(self.iface.Reboot, 'UpdateFailed')
        self.assertEqual(len(signals), 1)

    def test_cancel(self):
        # The downloads can be canceled when there is an update available.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        # Pre-cancel the download.
        self.iface.Cancel()
        # Do the download.
        signals = self._run_loop(self.iface.GetUpdate, 'Canceled')
        self.assertEqual(len(signals), 1)

    def test_reboot_after_cancel(self):
        # The downloads can be canceled when there is an update available.  If
        # the reboot is subsequently attempted, a Canceled signal is issued
        # and no reboot occurs.
        #
        # Get the download.
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        # Cancel the reboot.
        self.iface.Cancel()
        # The reboot gets canceled.
        signals = self._run_loop(self.iface.Reboot, 'Canceled')
        self.assertEqual(len(signals), 1)
        self.assertFalse(os.path.exists(self.reboot_log))

    def test_exit(self):
        self.iface.Exit()
        self.assertRaises(DBusException, self.iface.BuildNumber)
        # Re-establish a new connection.
        bus = dbus.SessionBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        self.assertEqual(self.iface.BuildNumber(), 0)


@unittest.skipUnless(_WHICH == 2, 'TEST 2 - LP: #1205163')
class TestDBusMocksNoUpdate(_TestBase):
    mode = 'no-update'

    def test_build_number(self):
        self.assertEqual(self.iface.BuildNumber(), 42)

    def test_no_update_available(self):
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        self.assertFalse(signals[0][0])


@unittest.skipUnless(_WHICH == 3, 'TEST 3 - LP: #1205163')
class TestDBusMocksUpdateAvailable(_TestBase):
    mode = 'update-success'

    def test_build_number(self):
        self.assertEqual(self.iface.BuildNumber(), 42)

    def test_update_available(self):
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        self.assertTrue(signals[0][0])

    def test_size(self):
        self.assertEqual(self.iface.GetUpdateSize(), 1369088)

    def test_version(self):
        self.assertEqual(self.iface.GetUpdateVersion(), 44)

    def test_descriptions(self):
        self.assertEqual(self.iface.GetDescriptions(), [
            {'description': 'Ubuntu Edge support',
             'description-fr': "Support d'Ubuntu Edge",
             'description-en': 'Initialise your Colour',
             'description-en_US': 'Initialize your Color',
            },
            {'description': 'Flipped container with 200% faster boot'},
            ])

    def test_update(self):
        signals = self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.assertEqual(len(signals), 1)

    def test_update_canceled(self):
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        # Pre-cancel the update.
        self.iface.Cancel()
        signals = self._run_loop(self.iface.GetUpdate, 'Canceled')
        self.assertEqual(len(signals), 1)

    def test_reboot(self):
        # Read a reboot.log so we can prove that the "reboot" happened.
        config = Configuration()
        config.load(self._controller.ini_path)
        reboot_log = os.path.join(config.updater.cache_partition, 'reboot.log')
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.iface.Reboot()
        with open(reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, 'reboot -f recovery')

    def test_reboot_canceled(self):
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        # Cancel the reboot.
        self.iface.Cancel()
        signals = self._run_loop(self.iface.Reboot, 'Canceled')
        self.assertEqual(len(signals), 1)


@unittest.skipUnless(_WHICH == 4, 'TEST 4 - LP: #1205163')
class TestDBusMocksUpdateFailed(_TestBase):
    mode = 'update-failed'

    def test_build_number(self):
        self.assertEqual(self.iface.BuildNumber(), 42)

    def test_update_available(self):
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        self.assertTrue(signals[0][0])

    def test_size(self):
        self.assertEqual(self.iface.GetUpdateSize(), 1369088)

    def test_version(self):
        self.assertEqual(self.iface.GetUpdateVersion(), 44)

    def test_descriptions(self):
        self.assertEqual(self.iface.GetDescriptions(), [
            {'description': 'Ubuntu Edge support',
             'description-fr': "Support d'Ubuntu Edge",
             'description-en': 'Initialise your Colour',
             'description-en_US': 'Initialize your Color',
            },
            {'description': 'Flipped container with 200% faster boot'},
            ])

    def test_update(self):
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)

    def test_reboot(self):
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)
        signals = self._run_loop(self.iface.Reboot, 'UpdateFailed')
        self.assertEqual(len(signals), 1)
