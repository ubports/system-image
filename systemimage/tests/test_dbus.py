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
    'TestDBusApply',
    'TestDBusCheckForUpdate',
    'TestDBusClient',
    'TestDBusDownload',
    'TestDBusGetSet',
    'TestDBusInfo',
    'TestDBusInfoNoDetails',
    'TestDBusMain',
    'TestDBusMockFailApply',
    'TestDBusMockFailPause',
    'TestDBusMockFailResume',
    'TestDBusMockNoUpdate',
    'TestDBusMockUpdateAutoSuccess',
    'TestDBusMockUpdateManualSuccess',
    'TestDBusRegressions',
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
from functools import partial
from systemimage.bindings import DBusClient
from systemimage.config import Configuration
from systemimage.dbus import Reactor
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
    _stack.callback(_controller.stop)
    DBusGMainLoop(set_as_default=True)


def tearDownModule():
    global _controller, _stack
    _stack.close()
    _controller = None


class SignalCapturingReactor(Reactor):
    def __init__(self, *signals):
        super().__init__(dbus.SystemBus())
        for signal in signals:
            self.react_to(signal)
        self.signals = []

    def _default(self, signal, path, *args, **kws):
        self.signals.append(args)
        self.quit()

    def run(self, method=None):
        if method is not None:
            self.schedule(method)
        super().run()

    def clear(self):
        del self.signals[:]


class AutoDownloadCancelingReactor(Reactor):
    def __init__(self, iface):
        super().__init__(dbus.SystemBus())
        self._iface = iface
        self.got_update_available_status = False
        self.got_update_failed = False
        self.react_to('UpdateAvailableStatus')
        self.react_to('UpdateFailed')

    def _do_UpdateAvailableStatus(self, signal, path, *args, **kws):
        self.got_update_available_status = True
        self._iface.CancelUpdate()

    def _do_UpdateFailed(self, signal, path, *args, **kws):
        self.got_update_failed = True
        self.quit()


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
        self.iface.CancelUpdate()
        # Consume the UpdateFailed that results from the cancellation.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run()
        safe_remove(self.config.system.build_file)
        for updater_dir in (self.config.updater.cache_partition,
                            self.config.updater.data_partition):
            try:
                all_files = os.listdir(updater_dir)
            except FileNotFoundError:
                # The directory itself may not exist.
                pass
            for filename in all_files:
                safe_remove(os.path.join(updater_dir, filename))
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

    def setUp(self):
        super().setUp()
        self._more_resources = ExitStack()

    def tearDown(self):
        self._more_resources.close()
        super().tearDown()

    def test_update_available(self):
        # There is an update available.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, '20130600')
        self.assertEqual(update_size, 314572800)
        # This is the first update applied.
        self.assertEqual(last_update_date, 'Unknown')
        ## self.assertEqual(descriptions, [{'description': 'Full'}])
        self.assertEqual(error_reason, '')

    def test_update_available_auto_download(self):
        # Automatically download the available update.
        self.download_always()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         # descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertTrue(downloading)
        self.assertEqual(available_version, '20130600')
        self.assertEqual(update_size, 314572800)
        # This is the first update applied.
        self.assertEqual(last_update_date, 'Unknown')
        ## self.assertEqual(descriptions, [{'description': 'Full'}])
        self.assertEqual(error_reason, '')

    def test_no_update_available(self):
        # Our device is newer than the version that's available.
        self._set_build(20130701)
        # Give /etc/ubuntu-build a predictable mtime.
        timestamp = int(datetime(2013, 8, 1, 10, 11, 12).timestamp())
        os.utime(self.config.system.build_file, (timestamp, timestamp))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertFalse(is_available)
        # No update has been previously applied.
        self.assertEqual(last_update_date, '2013-08-01 10:11:12')
        # All other values are undefined.

    def test_last_update_date(self):
        # Pretend the device got a previous update.  Now, there's no update
        # available, but the date of the last update is provided in the signal.
        self._set_build(20130701)
        # Fake that there was a previous update.
        timestamp = int(datetime(2013, 1, 20, 12, 1, 45).timestamp())
        channel_ini = os.path.join(
            os.path.dirname(_controller.ini_path), 'channel.ini')
        self._more_resources.callback(safe_remove, channel_ini)
        with open(channel_ini, 'w', encoding='utf-8'):
            pass
        os.utime(channel_ini, (timestamp, timestamp))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertFalse(is_available)
        # No update has been previously applied.
        self.assertEqual(last_update_date, '2013-01-20 12:01:45')
        # All other values are undefined.

    @unittest.skip('LP: #1215586')
    def test_get_multilingual_descriptions(self):
        # The descriptions are multilingual.
        self._prepare_index('index_14.json')
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date, descriptions, error_reason) = reactor.signals[0]
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


class TestDBusDownload(_LiveTesting):
    def test_auto_download(self):
        # When always auto-downloading, and there is an update available, the
        # update gets automatically downloaded.  First, we'll get an
        # UpdateAvailableStatus signal, followed by a bunch of UpdateProgress
        # signals (which for this test, we'll ignore), and finally an
        # UpdateDownloaded signal.
        self.download_always()
        self.assertFalse(os.path.exists(self.command_file))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertTrue(downloading)
        # Now, wait for the UpdateDownloaded signal.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run()
        self.assertEqual(len(reactor.signals), 1)
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

    def test_nothing_to_auto_download(self):
        # We're auto-downloading, but there's no update available.
        self.download_always()
        self._set_build(20130701)
        self.assertFalse(os.path.exists(self.command_file))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertFalse(is_available)
        self.assertFalse(downloading)
        # Now, wait for the UpdateDownloaded signal.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run()
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))

    def test_manual_download(self):
        # When manually downloading, and there is an update available, the
        # update does not get downloaded until we explicitly ask it to be.
        self.download_manually()
        self.assertFalse(os.path.exists(self.command_file))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        # This is false because we're in manual download mode.
        self.assertFalse(downloading)
        self.assertFalse(os.path.exists(self.command_file))
        # No UpdateDownloaded signal is coming.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run()
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))
        # Now we download manually and wait again for the signal.
        reactor.clear()
        reactor.run(self.iface.DownloadUpdate)
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

    def test_nothing_to_manually_download(self):
        # We're manually downloading, but there's no update available.
        self.download_manually()
        self._set_build(20130701)
        self.assertFalse(os.path.exists(self.command_file))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertFalse(is_available)
        # This is false because we're in manual download mode.
        self.assertFalse(downloading)
        # No UpdateDownloaded signal is coming
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run()
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))
        # Now we download manually, but no signal is coming.
        reactor.clear()
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))

    def test_update_failed_signal(self):
        # A signal is issued when the update failed.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, last_reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        # Don't count on a specific error message.
        self.assertNotEqual(last_reason, '')


class TestDBusApply(_LiveTesting):
    def setUp(self):
        super().setUp()
        self.download_always()

    def test_reboot(self):
        # Apply the update, which reboots the device.
        self.assertFalse(os.path.exists(self.reboot_log))
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(self.iface.CheckForUpdate)
        self.iface.ApplyUpdate()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')

    def test_reboot_no_update(self):
        # There's no update to reboot to.
        self.assertFalse(os.path.exists(self.reboot_log))
        self._set_build(20130701)
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        response = self.iface.ApplyUpdate()
        # Let's not count on the exact response, except that success returns
        # the empty string.
        self.assertNotEqual(response, '')
        self.assertFalse(os.path.exists(self.reboot_log))

    def test_reboot_after_update_failed(self):
        # Cause the update to fail by deleting a file from the server.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        self.assertNotEqual(reason, '')
        # The reboot fails, so we get an error message.
        self.assertNotEqual(self.iface.ApplyUpdate(), '')

    def test_cancel_manual(self):
        # While manually downloading, cancel the update.
        self.download_manually()
        # The downloads can be canceled when there is an update available.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Cancel future operations.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.CancelUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        self.assertNotEqual(reason, '')
        self.assertFalse(os.path.exists(self.command_file))
        # Try to download the update again, though this will fail again.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, reason = reactor.signals[0]
        self.assertEqual(failure_count, 2)
        self.assertNotEqual(reason, '')
        self.assertFalse(os.path.exists(self.command_file))
        # The next check resets the failure count and succeeds.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        # And now we can successfully download the update.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)

    def test_auto_download_cancel(self):
        # While automatically downloading, cancel the update.
        self.download_always()
        reactor = AutoDownloadCancelingReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        self.assertTrue(reactor.got_update_available_status)
        self.assertTrue(reactor.got_update_failed)

    def test_exit(self):
        self.iface.Exit()
        self.assertRaises(DBusException, self.iface.Info)
        # Re-establish a new connection.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        # There's no update to apply, so we'll get an error string instead of
        # the empty string for this call.  But it will restart the server.
        self.assertNotEqual(self.iface.ApplyUpdate(), '')


class MockReactor(Reactor):
    def __init__(self, iface):
        super().__init__(dbus.SystemBus())
        self._iface = iface
        self.timeout = 120
        self.react_to('UpdateProgress')
        self.pause_at_percentage = None
        self.cancel_at_percentage = None
        self.pause_start = None
        self.pause_end = None
        self.progress = []
        self.react_to('UpdateDownloaded')
        self.downloaded = False
        self.react_to('UpdateAvailableStatus')
        self.status = None
        self.auto_download = True
        self.react_to('UpdateFailed')
        self.failed = []
        self.react_to('UpdatePaused')
        self.pauses = []
        self.pauses_should_quit = True

    def _resume(self):
        self.pause_end = time.time()
        self._iface.DownloadUpdate()
        return False

    def _do_UpdateProgress(self, signal, path, percentage, eta):
        self.progress.append((percentage, eta))
        if percentage == self.pause_at_percentage:
            self.pause_start = time.time()
            self._iface.PauseDownload()
            # Wait 5 seconds, then resume the download.
            self.schedule(self._resume, 5000)
        elif percentage == self.cancel_at_percentage:
            self._iface.CancelUpdate()

    def _do_UpdateDownloaded(self, *args, **kws):
        self.downloaded = True
        self.quit()

    def _do_UpdateAvailableStatus(self, signal, path, *args, **kws):
        self.status = args
        if not self.auto_download:
            # The download must be started manually.
            self.quit()

    def _do_UpdateFailed(self, signal, path, *args, **kws):
        self.failed.append(args)
        self.quit()

    def _do_UpdatePaused(self, signal, path, percentage):
        self.pauses.append(percentage)
        if self.pauses_should_quit:
            self.quit()


class TestDBusMockUpdateAutoSuccess(_TestBase):
    mode = 'update-auto-success'

    def test_scenario_1(self):
        # Start the ball rolling.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertTrue(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, '')
        # We should have gotten 100 UpdateProgress signals, where each
        # increments the percentage by 1 and decrements the eta by 0.5.
        self.assertEqual(len(reactor.progress), 100)
        for i in range(100):
            percentage, eta = reactor.progress[i]
            self.assertEqual(percentage, i)
            self.assertEqual(eta, 50 - (i * 0.5))
        self.assertTrue(reactor.downloaded)
        self.assertEqual(self.iface.ApplyUpdate(), '')

    def test_scenario_2(self):
        # Like scenario 1, but with PauseDownload called during the downloads.
        reactor = MockReactor(self.iface)
        reactor.pauses_should_quit = False
        reactor.pause_at_percentage = 35
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        # We got a pause signal.
        self.assertEqual(len(reactor.pauses), 1)
        self.assertEqual(reactor.pauses[0], 35)
        # Make sure that we still got 100 progress reports.
        self.assertEqual(len(reactor.progress), 100)
        # And we still completed successfully.
        self.assertTrue(reactor.downloaded)
        # And that we paused successfully.  We can't be exact about the amount
        # of time we paused, but it should always be at least 4 seconds.
        self.assertGreater(reactor.pause_end - reactor.pause_start, 4)

    def test_scenario_3(self):
        # Like scenario 2, but PauseDownload is called when not downloading,
        # so it is a no-op.  The test service waits 3 seconds after a
        # CheckForUpdate before it begins downloading, so let's issue a
        # no-op PauseDownload after 1 second.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.PauseDownload, 1000)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        self.assertEqual(len(reactor.pauses), 0)
        self.assertIsNone(reactor.pause_start)
        self.assertIsNone(reactor.pause_end)

    def test_scenario_4(self):
        # If DownloadUpdate is called when not paused, downloading, or
        # update-checked, it is a no-op.
        self.iface.DownloadUpdate()
        # Only run for 15 seconds, but still, we'll never see an
        # UpdateAvailableStatus or UpdateDownloaded.
        reactor = MockReactor(self.iface)
        reactor.timeout = 15
        reactor.run()
        self.assertIsNone(reactor.status)
        self.assertFalse(reactor.downloaded)

    def test_scenario_5(self):
        # In this scenario, we cancel the download midway through.  This will
        # result in an UpdateFailed signal.
        reactor = MockReactor(self.iface)
        reactor.cancel_at_percentage = 27
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        # Our failed signal will tell us we got one consecutive failure and
        # the reason is that we canceled (but don't depend on the exact
        # content of the last_reason, just that it's not the empty string).
        self.assertEqual(len(reactor.failed), 1)
        failure_count, reason = reactor.failed[0]
        self.assertEqual(failure_count, 1)
        self.assertNotEqual(reason, '')
        # We also didn't download anything.
        self.assertFalse(reactor.downloaded)

    def test_scenario_6(self):
        # Like secenario 5, but after a cancel, CheckForUpdate will restart
        # things again.
        reactor = MockReactor(self.iface)
        reactor.cancel_at_percentage = 13
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        # Our failed signal will tell us we got one consecutive failure and
        # the reason is that we canceled (but don't depend on the exact
        # content of the last_reason, just that it's not the empty string).
        self.assertEqual(len(reactor.failed), 1)
        failure_count, reason = reactor.failed[0]
        self.assertEqual(failure_count, 1)
        self.assertNotEqual(reason, '')
        # We also didn't download anything.
        self.assertFalse(reactor.downloaded)
        # Now, restart the download.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        # This time, we've downloaded everything
        self.assertTrue(reactor.downloaded)
        self.assertEqual(len(reactor.failed), 0)


class TestDBusMockUpdateManualSuccess(_TestBase):
    mode = 'update-manual-success'

    def test_scenario_1(self):
        # Like scenario 1 for auto-downloading except that the download must
        # be started explicitly.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.auto_download = False
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, '')
        # There should be no progress yet.
        self.assertEqual(len(reactor.progress), 0)
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.DownloadUpdate)
        reactor.auto_download = False
        reactor.run()
        # We should have gotten 100 UpdateProgress signals, where each
        # increments the percentage by 1 and decrements the eta by 0.5.
        self.assertEqual(len(reactor.progress), 100)
        for i in range(100):
            percentage, eta = reactor.progress[i]
            self.assertEqual(percentage, i)
            self.assertEqual(eta, 50 - (i * 0.5))
        self.assertTrue(reactor.downloaded)
        self.assertEqual(self.iface.ApplyUpdate(), '')


class TestDBusMockUpdateFailed(_TestBase):
    mode = 'update-failed'

    def test_scenario_1(self):
        # The server is already in falure mode.  A CheckForUpdate() restarts
        # the check, which returns information about the new update.  It
        # auto-starts, but this fails.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, 'You need some network for downloading')
        self.assertEqual(len(reactor.failed), 1)
        failure_count, reason = reactor.failed[0]
        self.assertEqual(failure_count, 2)
        self.assertEqual(reason, 'You need some network for downloading')


class TestDBusMockFailApply(_TestBase):
    mode = 'fail-apply'

    def test_scenario_1(self):
        # The update has been downloaded, client sends CheckForUpdate and
        # receives a response.  The update is downloaded successfully.  An
        # error occurs when we try to apply the update.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, '')
        self.assertTrue(reactor.downloaded)
        self.assertEqual(self.iface.ApplyUpdate(),
                         'Not enough battery, you need to plug in your phone')


class TestDBusMockFailResume(_TestBase):
    mode = 'fail-resume'

    def test_scenario_1(self):
        # The server download is paused at 42%.  A CheckForUpdate is issued
        # and gets a response.  An UpdatePaused signal is sent.  A problem
        # occurs that prevents resuming.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, '')
        # The download is already paused.
        self.assertEqual(len(reactor.pauses), 1)
        self.assertEqual(reactor.pauses[0], 42)
        # We try to resume the download, but that fails.
        self.assertEqual(len(reactor.failed), 0)
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.DownloadUpdate)
        reactor.run()
        self.assertEqual(len(reactor.failed), 1)
        failure_count, reason = reactor.failed[0]
        self.assertEqual(failure_count, 9)
        self.assertEqual(reason, 'You need some network for downloading')


class TestDBusMockFailPause(_TestBase):
    mode = 'fail-pause'

    def test_scenario_1(self):
        # The server is downloading, currently at 10% with no known ETA.  The
        # client tries to pause the download but is unable to do so.
        reactor = MockReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        # Only run the loop for a few seconds, since otherwise there's no
        # natural way to pause the download.
        reactor.timeout = 5
        reactor.run()
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.status
        self.assertTrue(is_available)
        self.assertTrue(downloading)
        self.assertEqual(available_version, '42')
        self.assertEqual(update_size, 1337 * 1024 * 1024)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        ## self.assertEqual(descriptions, [
        ##     {'description': 'Ubuntu Edge support',
        ##      'description-en_GB': 'change the background colour',
        ##      'description-fr': "Support d'Ubuntu Edge",
        ##     },
        ##     {'description':
        ##      'Flipped container with 200% boot speed improvement',
        ##     }])
        self.assertEqual(error_reason, '')
        self.assertEqual(len(reactor.progress), 1)
        percentage, eta = reactor.progress[0]
        self.assertEqual(percentage, 10)
        self.assertEqual(eta, 0)
        reason = self.iface.PauseDownload()
        self.assertEqual(reason, 'no no, not now')


class TestDBusMockNoUpdate(_TestBase):
    mode = 'no-update'

    def test_scenario_1(self):
        # No update is available.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertFalse(is_available)
        self.assertFalse(downloading)
        self.assertEqual(last_update_date, '1983-09-13T12:13:14')
        # All the other status variables can be ignored.

    def test_lp_1215946(self):
        reactor = MockReactor(self.iface)
        reactor.auto_download = False
        # no-update mock sends UpdateFailed before UpdateAvailableStatus.
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        self.assertEqual(len(reactor.failed), 0)
        self.assertIsNotNone(reactor.status)


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

    def test_check_for_update(self):
        # There is an update available.
        self._client.check_for_update()
        self.assertTrue(self._client.is_available)
        self.assertTrue(self._client.downloaded)

    def test_check_for_no_update(self):
        # There is no update available.
        self._set_build(20130701)
        self._client.check_for_update()
        self.assertFalse(self._client.is_available)
        self.assertFalse(self._client.downloaded)

    def test_update_failed(self):
        # For some reason <wink>, the update fails.
        #
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(_controller.serverdir, '4/5/6.txt.asc'))
        self._client.check_for_update()
        self.assertTrue(self._client.is_available)
        self.assertFalse(self._client.downloaded)
        self.assertTrue(self._client.failed)

    def test_reboot(self):
        # After a successful update, we can reboot.
        self._client.check_for_update()
        self.assertTrue(self._client.is_available)
        self.assertTrue(self._client.downloaded)
        self._client.reboot()
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')


class TestDBusRegressions(_LiveTesting):
    """Test that various regressions have been fixed."""

    def test_lp_1205398(self):
        # Reset state after cancel.
        self.download_manually()
        # This test requires that the download take more than 50ms, since
        # that's the quickest we can issue the cancel, so make one of the
        # files huge.
        index_path = os.path.join(
            _controller.serverdir, 'stable', 'nexus7', 'index.json')
        file_path = os.path.join(_controller.serverdir, '5', '6', '7.txt')
        # This index file has a 5/6/7/txt checksum equal to the one we're
        # going to create below.
        setup_index(
            'index_18.json', _controller.serverdir, 'device-signing.gpg')
        head, tail = os.path.split(index_path)
        copy('index_18.json', head, tail)
        sign(index_path, 'device-signing.gpg')
        with open(file_path, 'wb') as fp:
            # 50MB
            for chunk in range(12800):
                fp.write(b'x' * 4096)
        sign(file_path, 'device-signing.gpg')
        # An update is available.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        self.assertFalse(os.path.exists(self.command_file))
        # Pre-cancel the download.  This works because cancelling currently
        # just sets an event.  XXX This test will have to change once LP:
        # #1196991 is fixed.
        self.iface.CancelUpdate()
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, reason = reactor.signals[0]
        self.assertNotEqual(reason, '')
        self.assertFalse(os.path.exists(self.command_file))
        # There's still an update available though, so check again.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        # Now we'll let the download proceed to completion.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # And now there is a command file for the update.
        self.assertTrue(os.path.exists(self.command_file))


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

    def test_setting_auto_download_good(self):
        # auto_download has special semantics.
        self.iface.SetSetting('auto_download', '0')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '1')
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')
        self.iface.SetSetting('auto_download', '2')
        self.assertEqual(self.iface.GetSetting('auto_download'), '2')

    def test_setting_auto_download_bad(self):
        # auto_download requires an integer between 0 and 2.  Don't forget
        # that it gets pre-populated when the database is created.
        self.iface.SetSetting('auto_download', 'standby')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '-1')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '1')
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')
        self.iface.SetSetting('auto_download', '3')
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')
        self.iface.SetSetting('auto_download', '2')
        self.assertEqual(self.iface.GetSetting('auto_download'), '2')

    def test_prepopulated_settings(self):
        # Some settings are pre-populated.
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')

    def test_setting_changed_signal(self):
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'foo', 'yes'))
        self.assertEqual(len(reactor.signals), 1)
        key, new_value = reactor.signals[0]
        self.assertEqual(key, 'foo')
        self.assertEqual(new_value, 'yes')
        # The value did not change.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'foo', 'yes'))
        reactor.run()
        self.assertEqual(len(reactor.signals), 0)
        # This is the default value, so nothing changes.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'auto_download', '0'))
        self.assertEqual(len(reactor.signals), 0)
        # This is a bogus value, so nothing changes.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'min_battery', '200'))
        self.assertEqual(len(reactor.signals), 0)
        # Change back.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'auto_download', '1'))
        self.assertEqual(len(reactor.signals), 1)
        key, new_value = reactor.signals[0]
        self.assertEqual(key, 'auto_download')
        self.assertEqual(new_value, '1')
        # Change back.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'min_battery', '30'))
        self.assertEqual(len(reactor.signals), 1)
        key, new_value = reactor.signals[0]
        self.assertEqual(key, 'min_battery')
        self.assertEqual(new_value, '30')


class TestDBusInfo(_TestBase):
    mode = 'more-info'

    def test_info(self):
        # .Info() with a channel.ini containing version details.
        buildno, device, channel, last_update, details = self.iface.Info()
        self.assertEqual(buildno, 45)
        self.assertEqual(device, 'nexus11')
        self.assertEqual(channel, 'daily-proposed')
        self.assertEqual(last_update, '2099-08-01 04:45:45')
        self.assertEqual(details, dict(ubuntu='123', mako='456', custom='789'))


class TestDBusInfoNoDetails(_LiveTesting):
    def test_info_no_version_details(self):
        # .Info() where there is no channel.ini with version details.
        self._set_build(45)
        timestamp = datetime(2022, 8, 1, 4, 45, 45).timestamp()
        os.utime(self.config.system.build_file, (timestamp, timestamp))
        buildno, device, channel, last_update, details = self.iface.Info()
        self.assertEqual(buildno, 45)
        self.assertEqual(device, 'nexus7')
        self.assertEqual(channel, 'stable')
        self.assertEqual(last_update, '2022-08-01 04:45:45')
        self.assertEqual(details, {})
