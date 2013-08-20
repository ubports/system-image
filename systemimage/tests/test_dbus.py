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
    'TestDBusCheckForUpdate',
    'TestDBusClient',
    'TestDBusMain',
    'TestDBusMocksNoUpdate',
    'TestDBusMocksUpdateAvailable',
    'TestDBusMocksUpdateFailed',
    ]


import os
import dbus
import time
import shutil
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta
from dbus.exceptions import DBusException
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from systemimage.bindings import DBusClient
from systemimage.config import Configuration
from systemimage.helpers import safe_remove
from systemimage.testing.controller import Controller
from systemimage.testing.helpers import (
    copy, make_http_server, setup_index, setup_keyring_txz, setup_keyrings,
    sign)


_stack = None
_controller = None

# Why are these tests set up this?
#
# LP: #1205163 provides the impetus.  Here's the problem: we have to start a
# dbus-daemon child process which will create an isolated system bus on which
# our com.canonical.SystemImage service will be started via dbus-activatiion.
# This closely mimics how the real system starts up our service.
#
# We ask dbus-daemon to return us its pid and the dbus address it's listening
# on.  We need the address because we have to ensure that the dbus client,
# i.e. this foreground test process, can communicate with the isolated
# service.  To do this, the foreground process sets the environment variable
# DBUS_SYSTEM_BUS_ADDRESS to the address that dbus-daemon gave us.
#
# The problem is that the low-level dbus client library only consults that
# envar when it initializes, which it only does once per process.  There's no
# way to get the library to listen on a new DBUS_SYSTEM_BUS_ADDRESS later on.
#
# This means that our first approach, which involved killing the granchild
# system-image-dbus process, and the child dbus-daemon process, and then
# restarting a new dbus-daemon process on a new address, doesn't work.
#
# We need a new system-image-dbus process for each of the TestCases below
# because we have to start them up in different testing modes, and there's no
# way to do that without exiting them and restarting them.  The grandchild
# processes get started via different com.canonical.SystemImage.service files
# with different commands.
#
# So, we have to restart the system-image-dbus process, but *not* the
# dbus-daemon process because for all of these tests, it must be listening on
# the same system bus.  Fortunately, dbus-daemon responds to SIGHUP, which
# tells it to re-read its configuration files, including its .service files.
# So how this works is that at the end of each test class, we tell the dbus
# service to .Exit(), wait until it has, then write a new .service file with
# the new command, HUP the dbus-daemon, and now the next time it activates the
# service, it will do so with the correct (i.e. newly written) command.


def setUpModule():
    global _controller, _stack
    _stack = ExitStack()
    _controller = Controller()
    _stack.callback(_controller.shutdown)
    DBusGMainLoop(set_as_default=True)


def tearDownModule():
    global _controller, _stack
    _stack.close()
    _controller = None


class _TestBase(unittest.TestCase):
    """Base class for all DBus testing."""

    # Override this to start the DBus server in a different testing mode.
    mode = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _controller.set_testing_mode(cls.mode)
        _controller.start()

    @classmethod
    def tearDownClass(cls):
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        iface = dbus.Interface(service, 'com.canonical.SystemImage')
        iface.Exit()
        # 2013-07-30 BAW: This sucks but there's no way to know exactly when
        # the process has exited, because we cannot know the pid of the
        # system-image-dbus process, which is our grandchild.  Just keep
        # pinging the server until it stops responding.
        until = datetime.now() + timedelta(seconds=60)
        while datetime.now() < until:
            time.sleep(0.2)
            try:
                iface.Exit()
            except DBusException:
                break
        # Clear out the temporary directory.
        config = Configuration()
        config.load(_controller.ini_path)
        try:
            shutil.rmtree(config.system.tempdir)
        except FileNotFoundError:
            pass
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.system_bus = dbus.SystemBus()
        service = self.system_bus.get_object(
            'com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')

    def tearDown(self):
        self.iface.Reset()
        super().tearDown()

    def _run_loop(self, method, signal):
        loop = GLib.MainLoop()
        # Here's the callback for when dbus receives the signal.
        signals = []
        def callback(*args):
            signals.append(args)
            loop.quit()
        self.system_bus.add_signal_receiver(
            callback, signal_name=signal,
            dbus_interface='com.canonical.SystemImage')
        GLib.timeout_add(100, method)
        GLib.timeout_add_seconds(10, loop.quit)
        loop.run()
        return signals

    def download_manually(self):
        self.iface.SetSetting('auto_download', '0')

    def download_on_wifi(self):
        self.iface.SetSetting('auto_download', '1')

    def download_always(self):
        self.iface.SetSetting('auto_download', '2')


class _LiveTesting(_TestBase):
    mode = 'live'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._resources = ExitStack()
        # Set up the http/https servers that the dbus client will talk to.
        # Start up both an HTTPS and HTTP server.  The data files are vended
        # over the latter, everything else, over the former.
        serverdir = _controller.serverdir
        try:
            cls._resources.push(
                make_http_server(serverdir, 8943, 'cert.pem', 'key.pem'))
            cls._resources.push(make_http_server(serverdir, 8980))
            # Set up the server files.
            copy('channels_06.json', serverdir, 'channels.json')
            sign(os.path.join(serverdir, 'channels.json'), 'image-signing.gpg')
            # Only the archive-master key is pre-loaded.  All the other keys
            # are downloaded and there will be both a blacklist and device
            # keyring.  The four signed keyring tar.xz files and their
            # signatures end up in the proper location after the state machine
            # runs to completion.
            config = Configuration()
            config.load(_controller.ini_path)
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
        except:
            cls._resources.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._resources.close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._prepare_index('index_13.json')
        # We need a configuration file that agrees with the dbus client.
        self.config = Configuration()
        self.config.load(_controller.ini_path)
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
            _controller.serverdir, 'stable', 'nexus7', 'index.json')
        head, tail = os.path.split(index_path)
        copy(index_file, head, tail)
        sign(index_path, 'device-signing.gpg')
        setup_index(index_file, _controller.serverdir, 'device-signing.gpg')

    def _set_build(self, version):
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(version, file=fp)


class TestDBusCheckForUpdate(_LiveTesting):
    """Test the SystemImage dbus service."""

    def test_update_available(self):
        # There is an update available.
        self.download_manually()
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date, descriptions, error_reason) = signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, 20130600)
        self.assertEqual(update_size, 314572800)
        # This is the first update applied.
        self.assertEqual(last_update_date, '')
        self.assertEqual(descriptions, [{'description': 'Full'}])
        self.assertEqual(error_reason, '')

    def test_update_available_auto_download(self):
        # When auto-updating (wifi-only is the default).
        self.download_always()
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date, descriptions, error_reason) = signals[0]
        self.assertTrue(is_available)
        self.assertTrue(downloading)
        self.assertEqual(available_version, 20130600)
        self.assertEqual(update_size, 314572800)
        # This is the first update applied.
        self.assertEqual(last_update_date, '')
        self.assertEqual(descriptions, [{'description': 'Full'}])
        self.assertEqual(error_reason, '')

    def test_no_update_available(self):
        # Our device is newer than the version that's available.
        self._set_build(20130701)
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date, descriptions, error_reason) = signals[0]
        self.assertFalse(is_available)
        # No update has been previously applied.
        self.assertEqual(last_update_date, '')
        # All other values are undefined.

    def test_get_multilingual_descriptions(self):
        # The descriptions are multilingual.
        self._prepare_index('index_14.json')
        signals = self._run_loop(
            self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self.assertEqual(len(signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date, descriptions, error_reason) = signals[0]
        self.assertEqual(descriptions, [
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


def TestDBusXXX(_LiveTesting):
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
        self.assertEqual(reboot, '/sbin/reboot -f recovery')

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
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)

    def test_reboot_after_update_failed(self):
        # Cause the update to fail by deleting a file from the server.
        #
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        signals = self._run_loop(self.iface.GetUpdate, 'UpdateFailed')
        self.assertEqual(len(signals), 1)
        signals = self._run_loop(self.iface.Reboot, 'UpdateFailed')
        self.assertEqual(len(signals), 1)

    def test_cancel(self):
        # The downloads can be canceled when there is an update available.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        # Cancel future operations.
        signals = self._run_loop(self.iface.Cancel, 'Canceled')
        self.assertEqual(len(signals), 1)
        # Run an update, which will no-op.
        self.assertFalse(os.path.exists(self.command_file))
        signals = self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.assertEqual(len(signals), 0)
        self.assertFalse(os.path.exists(self.command_file))
        # Similarly, if we still try to reboot, nothing will happen.
        self.assertFalse(os.path.exists(self.reboot_log))
        self.iface.Reboot()
        self.assertFalse(os.path.exists(self.reboot_log))

    def test_exit(self):
        self.iface.Exit()
        self.assertRaises(DBusException, self.iface.BuildNumber)
        # Re-establish a new connection.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        self.assertEqual(self.iface.BuildNumber(), 0)


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


class TestDBusMocksUpdateAvailable(_TestBase):
    mode = 'update-success'

    def setUp(self):
        super().setUp()
        config = Configuration()
        config.load(_controller.ini_path)
        self.reboot_log = os.path.join(
            config.updater.cache_partition, 'reboot.log')

    def tearDown(self):
        safe_remove(self.reboot_log)
        super().tearDown()

    def test_last_update_date(self):
        # After the initial update, the last update date is available.
        pass

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
        # Cancel the update.
        signals = self._run_loop(self.iface.Cancel, 'Canceled')
        self.assertEqual(len(signals), 1)
        # The next GetUpdate() will no-op.
        signals = self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.assertEqual(len(signals), 0)

    def test_reboot(self):
        # Read a reboot.log so we can prove that the "reboot" happened.
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        self.iface.Reboot()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')

    def test_reboot_canceled(self):
        self._run_loop(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        self._run_loop(self.iface.GetUpdate, 'ReadyToReboot')
        signals = self._run_loop(self.iface.Cancel, 'Canceled')
        self.assertEqual(len(signals), 1)
        # The next reboot will no-op.
        self.assertFalse(os.path.exists(self.reboot_log))
        self.iface.Reboot()
        self.assertFalse(os.path.exists(self.reboot_log))


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


class TestDBusMain(_TestBase):
    mode = 'live'

    def setUp(self):
        # Don't call super's setUp() since that will start the service, thus
        # creating the temporary directory.
        pass

    def tearDown(self):
        # We didn't call setUp() so don't call tearDown().
        pass

    def test_temp_directory(self):
        # The temporary directory gets created if it doesn't exist.
        config = Configuration()
        config.load(_controller.ini_path)
        self.assertFalse(os.path.exists(config.system.tempdir))
        # DBus activate the service, which should create the directory.
        bus = dbus.SystemBus()
        bus.get_object('com.canonical.SystemImage', '/Service')
        self.assertTrue(os.path.exists(config.system.tempdir))


class TestDBusClient(_LiveTesting):
    """Test the DBus client (used with --dbus)."""

    def setUp(self):
        super().setUp()
        self._client = DBusClient()

    def test_build_number(self):
        # Get the build number through the client.
        self._set_build(20130701)
        self.assertEqual(self._client.build_number, 20130701)

    def test_check_for_update(self):
        # There is an update available.
        self.assertTrue(self._client.check_for_update())

    def test_check_for_no_update(self):
        # There is no update available.
        self._set_build(20130701)
        self.assertFalse(self._client.check_for_update())

    def test_get_update_size(self):
        # The size of the available update.
        self.assertTrue(self._client.check_for_update())
        self.assertEqual(self._client.update_size, 314572800)

    def test_get_update_no_size(self):
        # Size is zero if there is no update available.
        self._set_build(20130701)
        self.assertFalse(self._client.check_for_update())
        self.assertEqual(self._client.update_size, 0)

    def test_get_update_version(self):
        # The target version of the upgrade.
        self.assertTrue(self._client.check_for_update())
        self.assertEqual(self._client.update_version, 20130600)

    def test_get_update_no_version(self):
        # Version is zero if there is no update available.
        self._set_build(20130701)
        self.assertFalse(self._client.check_for_update())
        self.assertEqual(self._client.update_version, 0)

    def test_get_update_descriptions(self):
        # The update has some descriptions.
        self.assertTrue(self._client.check_for_update())
        self.assertEqual(self._client.update_descriptions,
                         [{'description': 'Full'}])

    def test_get_update_no_descriptions(self):
        # Sometimes there's no update, and thus no descrptions.
        self._set_build(20130701)
        self.assertFalse(self._client.check_for_update())
        self.assertEqual(self._client.update_descriptions, [])

    def test_update(self):
        # Do the update, but wait to reboot.
        self.assertTrue(self._client.check_for_update())
        ready = self._client.update()
        self.assertTrue(ready)

    def test_update_failed(self):
        # For some reason <wink>, the update fails.
        self.assertTrue(self._client.check_for_update())
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        ready = self._client.update()
        self.assertFalse(ready)

    def test_reboot(self):
        # After a successful update, we can reboot.
        self.assertTrue(self._client.check_for_update())
        self.assertTrue(self._client.update())
        self._client.reboot()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')


class TestDBusGetSet(_TestBase):
    """Test the DBus client's key/value settings."""

    mode = 'live'

    def test_set_get_basic(self):
        # get/set a random key.
        self.iface.SetSetting('name', 'ant')
        self.assertEqual(self.iface.GetSetting('name'), 'ant')

    def test_set_get_change(self):
        # get/set a random key, then change it.
        self.iface.SetSetting('name', 'ant')
        self.assertEqual(self.iface.GetSetting('name'), 'ant')
        self.iface.SetSetting('name', 'bee')
        self.assertEqual(self.iface.GetSetting('name'), 'bee')

    def test_get_before_set(self):
        # Getting a key that doesn't exist returns the empty string.
        self.assertEqual(self.iface.GetSetting('thing'), '')
        self.iface.SetSetting('thing', 'one')
        self.assertEqual(self.iface.GetSetting('thing'), 'one')

    def test_setting_persists(self):
        # Set a key, restart the dbus server, and the key's value persists.
        self.iface.SetSetting('permanent', 'waves')
        self.assertEqual(self.iface.GetSetting('permanent'), 'waves')
        self.iface.Exit()
        self.assertRaises(DBusException, self.iface.GetSetting, 'permanent')
        # Re-establish a new connection.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        self.assertEqual(self.iface.GetSetting('permanent'), 'waves')

    def test_setting_min_battery_good(self):
        # min_battery has special semantics.
        self.iface.SetSetting('min_battery', '30')
        self.assertEqual(self.iface.GetSetting('min_battery'), '30')

    def test_setting_min_battery_bad(self):
        # min_battery requires the string representation of a percentage.
        self.iface.SetSetting('min_battery', 'standby')
        self.assertEqual(self.iface.GetSetting('min_battery'), '')
        self.iface.SetSetting('min_battery', '30')
        self.assertEqual(self.iface.GetSetting('min_battery'), '30')
        self.iface.SetSetting('min_battery', 'foo')
        self.assertEqual(self.iface.GetSetting('min_battery'), '30')
        self.iface.SetSetting('min_battery', '-10')
        self.assertEqual(self.iface.GetSetting('min_battery'), '30')
        self.iface.SetSetting('min_battery', '100')
        self.assertEqual(self.iface.GetSetting('min_battery'), '100')
        self.iface.SetSetting('min_battery', '101')
        self.assertEqual(self.iface.GetSetting('min_battery'), '100')
        self.iface.SetSetting('min_battery', 'standby')
        self.assertEqual(self.iface.GetSetting('min_battery'), '100')

    def test_setting_auto_downloads_good(self):
        # auto_downloads has special semantics.
        self.iface.SetSetting('auto_downloads', '0')
        self.assertEqual(self.iface.GetSetting('auto_downloads'), '0')
        self.iface.SetSetting('auto_downloads', '1')
        self.assertEqual(self.iface.GetSetting('auto_downloads'), '1')
        self.iface.SetSetting('auto_downloads', '2')
        self.assertEqual(self.iface.GetSetting('auto_downloads'), '2')

    def test_setting_auto_downloads_bad(self):
        # auto_downloads requires an integer between 0 and 2.
        self.iface.SetSetting('auto_download', 'standby')
        self.assertEqual(self.iface.GetSetting('auto_download'), '')
        self.iface.SetSetting('auto_download', '-1')
        self.assertEqual(self.iface.GetSetting('auto_download'), '')
        self.iface.SetSetting('auto_download', '0')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '3')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
