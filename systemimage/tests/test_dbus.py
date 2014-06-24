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

"""Test the SystemImage dbus service."""

__all__ = [
    'TestDBusApply',
    'TestDBusCheckForUpdate',
    'TestDBusCheckForUpdateToUnwritablePartition',
    'TestDBusCheckForUpdateWithBrokenIndex',
    'TestDBusClient',
    'TestDBusDownload',
    'TestDBusFactoryReset',
    'TestDBusGetSet',
    'TestDBusInfo',
    'TestDBusMockFailApply',
    'TestDBusMockFailPause',
    'TestDBusMockFailResume',
    'TestDBusMockNoUpdate',
    'TestDBusMockUpdateAutoSuccess',
    'TestDBusMockUpdateManualSuccess',
    'TestDBusMultipleChecksInFlight',
    'TestDBusPauseResume',
    'TestDBusProgress',
    'TestDBusRegressions',
    'TestDBusUseCache',
    'TestLiveDBusInfo',
    'TestLiveDBusInfoWithChannelIni',
    ]


import os
import dbus
import json
import time
import shutil
import unittest

from contextlib import ExitStack
from datetime import datetime
from dbus.exceptions import DBusException
from functools import partial
from pathlib import Path
from systemimage.bindings import DBusClient
from systemimage.config import Configuration
from systemimage.helpers import MiB, atomic, safe_remove
from systemimage.reactor import Reactor
from systemimage.settings import Settings
from systemimage.testing.helpers import (
    copy, find_dbus_process, make_http_server, setup_index, setup_keyring_txz,
    setup_keyrings, sign)
from systemimage.testing.nose import SystemImagePlugin


class SignalCapturingReactor(Reactor):
    def __init__(self, *signals):
        super().__init__(dbus.SystemBus())
        for signal in signals:
            self.react_to(signal)
        self.signals = []

    def _default(self, signal, path, *args, **kws):
        self.signals.append(args)
        self.quit()

    def run(self, method=None, timeout=None):
        if method is not None:
            self.schedule(method)
        super().run(timeout=timeout)


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


class ProgressRecordingReactor(Reactor):
    def __init__(self):
        super().__init__(dbus.SystemBus())
        self.react_to('UpdateDownloaded')
        self.react_to('UpdateProgress')
        self.progress = []

    def _do_UpdateDownloaded(self, signal, path, *args, **kws):
        self.quit()

    def _do_UpdateProgress(self, signal, path, *args, **kws):
        self.progress.append(args)


class PausingReactor(Reactor):
    def __init__(self, iface):
        super().__init__(dbus.SystemBus())
        self._iface = iface
        self.pause_progress = 0
        self.paused = False
        self.percentage = 0
        self.react_to('UpdateProgress')
        self.react_to('UpdatePaused')

    def _do_UpdateProgress(self, signal, path, percentage, eta):
        if self.pause_progress == 0 and percentage > 0:
            self._iface.PauseDownload()
            self.pause_progress = percentage

    def _do_UpdatePaused(self, signal, path, percentage):
        self.paused = True
        self.percentage = percentage
        self.quit()


class DoubleCheckingReactor(Reactor):
    def __init__(self, iface):
        super().__init__(dbus.SystemBus())
        self.iface = iface
        self.uas_signals = []
        self.react_to('UpdateAvailableStatus')
        self.react_to('UpdateDownloaded')
        self.schedule(self.iface.CheckForUpdate)

    def _do_UpdateAvailableStatus(self, signal, path, *args, **kws):
        # We'll keep doing this until we get the UpdateDownloaded signal.
        self.uas_signals.append(args)
        self.schedule(self.iface.CheckForUpdate)

    def _do_UpdateDownloaded(self, *args, **kws):
        self.quit()


class ManualUpdateReactor(Reactor):
    def __init__(self, iface):
        super().__init__(dbus.SystemBus())
        self.iface = iface
        self.rebooting = False
        self.react_to('UpdateAvailableStatus')
        self.react_to('UpdateProgress')
        self.react_to('UpdateDownloaded')
        self.react_to('Rebooting')
        self.react_to('UpdateFailed')
        self.iface.CheckForUpdate()

    def _do_UpdateAvailableStatus(self, signal, path, *args, **kws):
        # When the update is available, start the download.
        self.iface.DownloadUpdate()

    def _do_UpdateProgress(self, signal, path, *args, **kws):
        # Once the download is in progress, initiate another check.  Only do
        # this on the first progress signal.
        if args == (0, 0):
            self.iface.CheckForUpdate()

    def _do_UpdateDownloaded(self, signal, path, *args, **kws):
        # The update successfully downloaded, so apply the update now.
        self.iface.ApplyUpdate()

    def _do_UpdateFailed(self, signal, path, *args, **kws):
        # Before LP: #1287919 was fixed, this signal would have been sent.
        self.rebooting = False
        self.quit()

    def _do_Rebooting(self, signal, path, *args, **kws):
        # The system is now rebooting <wink>.
        self.rebooting = True
        self.quit()


class _TestBase(unittest.TestCase):
    """Base class for all DBus testing."""

    # For unittest's assertMultiLineEqual().
    maxDiff = None

    # Override this to start the DBus server in a different testing mode.
    mode = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        SystemImagePlugin.controller.set_mode(
            cert_pem='cert.pem',
            service_mode=cls.mode)

    @classmethod
    def tearDownClass(cls):
        # Try to find the system-image-dbus process matching the current ini
        # file used by the controller.  We'll use this to ensure that the
        # process has exited.
        process = find_dbus_process(SystemImagePlugin.controller.ini_path)
        if process is not None:
            bus = dbus.SystemBus()
            service = bus.get_object('com.canonical.SystemImage', '/Service')
            iface = dbus.Interface(service, 'com.canonical.SystemImage')
            iface.Exit()
            # Wait for the process to exit, but only for a little while.
            process.wait(60)
        # Clear out the temporary directory.
        config = Configuration()
        config.load(SystemImagePlugin.controller.ini_path)
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
        serverdir = SystemImagePlugin.controller.serverdir
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
            config.load(SystemImagePlugin.controller.ini_path)
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
        self.config.load(SystemImagePlugin.controller.ini_path)
        # For testing reboot preparation.
        self.command_file = os.path.join(
            self.config.updater.cache_partition, 'ubuntu_command')
        # For testing the reboot command without actually rebooting.
        self.reboot_log = os.path.join(
            self.config.updater.cache_partition, 'reboot.log')

    def tearDown(self):
        # Consume the UpdateFailed that results from the cancellation.
        reactor = SignalCapturingReactor('TornDown')
        reactor.run(self.iface.TearDown, timeout=15)
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

    def _prepare_index(self, index_file, write_callback=None):
        serverdir = SystemImagePlugin.controller.serverdir
        index_path = os.path.join(serverdir, 'stable', 'nexus7', 'index.json')
        head, tail = os.path.split(index_path)
        copy(index_file, head, tail)
        sign(index_path, 'device-signing.gpg')
        setup_index(index_file, serverdir, 'device-signing.gpg',
                    write_callback)

    def _touch_build(self, version, timestamp=None):
        # Unlike the touch_build() helper, this one uses our own config object
        # rather than the global one.   It's not worth messing with
        # touch_build() to generalize it.
        assert 0 <= version < (1 << 16), (
            'old style version number: {}'.format(version))
        with open(self.config.system.build_file, 'w', encoding='utf-8') as fp:
            print(version, file=fp)
        if timestamp is not None:
            timestamp = int(timestamp.timestamp())
            os.utime(self.config.system.build_file, (timestamp, timestamp))


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
        self.assertEqual(available_version, '1600')
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
        self.assertEqual(available_version, '1600')
        self.assertEqual(update_size, 314572800)
        # This is the first update applied.
        self.assertEqual(last_update_date, 'Unknown')
        ## self.assertEqual(descriptions, [{'description': 'Full'}])
        self.assertEqual(error_reason, '')

    def test_no_update_available(self):
        # Our device is newer than the version that's available.
        self._touch_build(1701, datetime(2013, 8, 1, 10, 11, 12))
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
        # available, but the date of the last update is provided in the
        # signal.
        timestamp = datetime(2013, 1, 20, 12, 1, 45)
        self._touch_build(1701, timestamp)
        timestamp = int(timestamp.timestamp())
        # Fake that there was a previous update.
        channel_ini = os.path.join(
            os.path.dirname(SystemImagePlugin.controller.ini_path),
            'channel.ini')
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

    def test_check_for_update_twice(self):
        # Issue two CheckForUpdate calls immediate after each other.
        self.download_always()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        def two_calls():
            self.iface.CheckForUpdate()
            self.iface.CheckForUpdate()
        reactor.run(two_calls)
        self.assertEqual(len(reactor.signals), 1)
        # There's one boolean argument to the result.
        (is_available, downloading, available_version, update_size,
         last_update_date,
         # descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertTrue(downloading)

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
        self._touch_build(1701)
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
        # Now, wait for the UpdateDownloaded signal, which isn't coming.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(timeout=15)
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
        reactor.run(timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))
        # Now we download manually and wait again for the signal.
        reactor = SignalCapturingReactor('UpdateDownloaded')
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
        self._touch_build(1701)
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
        reactor.run(timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))
        # Now we download manually, but no signal is coming.
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(self.iface.DownloadUpdate, timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        self.assertFalse(os.path.exists(self.command_file))

    def test_update_failed_signal(self):
        # A signal is issued when the update failed.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(SystemImagePlugin.controller.serverdir,
                               '4/5/6.txt.asc'))
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, last_reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        self.assertEqual(last_reason[:17], 'FileNotFoundError')

    def test_duplicate_destinations(self):
        # A faulty index.json might specify that two different urls yield the
        # same local destination file.  This is a bug on the server and the
        # client cannot perform an update.
        self.download_manually()
        self._prepare_index('index_23.json')
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         #descriptions,
         error_reason) = reactor.signals[0]
        self.assertTrue(is_available)
        self.assertFalse(downloading)
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, last_reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        # Don't count on a specific error message.
        self.assertEqual(
            last_reason[:46], 'systemimage.download.DuplicateDestinationError')


class TestDBusApply(_LiveTesting):
    def setUp(self):
        super().setUp()
        self.download_always()

    def test_reboot(self):
        # Apply the update, which reboots the device.
        self.assertFalse(os.path.exists(self.reboot_log))
        reactor = SignalCapturingReactor('UpdateDownloaded')
        reactor.run(self.iface.CheckForUpdate)
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertTrue(reactor.signals[0])
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')

    def test_reboot_no_update(self):
        # There's no update to reboot to.
        self.assertFalse(os.path.exists(self.reboot_log))
        self._touch_build(1701)
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertFalse(reactor.signals[0][0])
        self.assertFalse(os.path.exists(self.reboot_log))

    def test_reboot_after_update_failed(self):
        # Cause the update to fail by deleting a file from the server.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        os.remove(os.path.join(SystemImagePlugin.controller.serverdir,
                               '4/5/6.txt.asc'))
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate)
        self.assertEqual(len(reactor.signals), 1)
        failure_count, reason = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        self.assertNotEqual(reason, '')
        # The reboot fails, so we get an error message.
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertFalse(reactor.signals[0][0])

    def test_auto_download_cancel(self):
        # While automatically downloading, cancel the update.
        self.download_always()
        reactor = AutoDownloadCancelingReactor(self.iface)
        reactor.schedule(self.iface.CheckForUpdate)
        reactor.run()
        self.assertTrue(reactor.got_update_available_status)
        self.assertTrue(reactor.got_update_failed)

    def test_exit(self):
        # There is a D-Bus method to exit the server immediately.
        self.iface.Exit()
        self.assertRaises(DBusException, self.iface.Info)
        # Re-establish a new connection.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        # There's no update to apply, so we'll get an error string instead of
        # the empty string for this call.  But it will restart the server.
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertFalse(reactor.signals[0][0])

    def test_cancel_while_not_downloading(self):
        # If we call CancelUpdate() when we're not downloading anything, no
        # UpdateFailed signal is sent.
        self.download_manually()
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # Since we're downloading manually, no signal will be sent.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.CancelUpdate, timeout=15)
        self.assertEqual(len(reactor.signals), 0)

    def test_cancel_manual(self):
        # While manually downloading, cancel the update.
        self.download_manually()
        # The downloads can be canceled when there is an update available.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Cancel future operations.  However, since no download is in
        # progress, we will not get a signal.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.CancelUpdate, timeout=15)
        self.assertEqual(len(reactor.signals), 0)
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
        self.assertEqual(update_size, 1337 * MiB)
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
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertTrue(reactor.signals[0])

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
        self.assertEqual(update_size, 1337 * MiB)
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
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertTrue(reactor.signals[0])


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
        self.assertEqual(update_size, 1337 * MiB)
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
        self.assertEqual(update_size, 1337 * MiB)
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
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertFalse(bool(reactor.signals[0][0]))


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
        self.assertEqual(update_size, 1337 * MiB)
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
        self.assertEqual(update_size, 1337 * MiB)
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
        self._touch_build(1701)
        self._client.check_for_update()
        self.assertFalse(self._client.is_available)
        self.assertFalse(self._client.downloaded)

    def test_update_failed(self):
        # For some reason <wink>, the update fails.
        #
        # Cause the update to fail by deleting a file from the server.
        os.remove(os.path.join(SystemImagePlugin.controller.serverdir,
                               '4/5/6.txt.asc'))
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
        serverdir = SystemImagePlugin.controller.serverdir
        index_path = os.path.join(serverdir, 'stable', 'nexus7', 'index.json')
        file_path = os.path.join(serverdir, '5', '6', '7.txt')
        # This index file has a 5/6/7/txt checksum equal to the one we're
        # going to create below.
        setup_index('index_18.json', serverdir, 'device-signing.gpg')
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
        # Arrange for the download to be canceled after it starts.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.schedule(self.iface.CancelUpdate)
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
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')
        self.iface.SetSetting('auto_download', '-1')
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')
        self.iface.SetSetting('auto_download', '0')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '3')
        self.assertEqual(self.iface.GetSetting('auto_download'), '0')
        self.iface.SetSetting('auto_download', '2')
        self.assertEqual(self.iface.GetSetting('auto_download'), '2')

    def test_prepopulated_settings(self):
        # Some settings are pre-populated.
        self.assertEqual(self.iface.GetSetting('auto_download'), '1')

    def test_setting_changed_signal(self):
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'foo', 'yes'))
        self.assertEqual(len(reactor.signals), 1)
        key, new_value = reactor.signals[0]
        self.assertEqual(key, 'foo')
        self.assertEqual(new_value, 'yes')
        # The value did not change.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'foo', 'yes'), timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        # This is the default value, so nothing changes.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'auto_download', '1'),
                    timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        # This is a bogus value, so nothing changes.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'min_battery', '200'),
                    timeout=15)
        self.assertEqual(len(reactor.signals), 0)
        # Change back.
        reactor = SignalCapturingReactor('SettingChanged')
        reactor.run(partial(self.iface.SetSetting, 'auto_download', '0'))
        self.assertEqual(len(reactor.signals), 1)
        key, new_value = reactor.signals[0]
        self.assertEqual(key, 'auto_download')
        self.assertEqual(new_value, '0')
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

    def test_information(self):
        # .Information() with a channel.ini containing version details.
        response = self.iface.Information()
        self.assertEqual(
            sorted(str(key) for key in response), [
                'channel_name',
                'current_build_number',
                'device_name',
                'last_check_date',
                'last_update_date',
                'version_detail',
                ])
        self.assertEqual(response['current_build_number'], '45')
        self.assertEqual(response['device_name'], 'nexus11')
        self.assertEqual(response['channel_name'], 'daily-proposed')
        self.assertEqual(response['last_update_date'], '2099-08-01 04:45:45')
        self.assertEqual(response['version_detail'],
                         'ubuntu=123,mako=456,custom=789')
        self.assertEqual(response['last_check_date'], '2099-08-01 04:45:00')


class TestLiveDBusInfo(_LiveTesting):
    def test_info_no_version_detail(self):
        # .Info() where there is no channel.ini with version details.
        self._touch_build(45, datetime(2022, 8, 1, 4, 45, 45))
        buildno, device, channel, last_update, details = self.iface.Info()
        self.assertEqual(buildno, 45)
        self.assertEqual(device, 'nexus7')
        self.assertEqual(channel, 'stable')
        self.assertEqual(last_update, '2022-08-01 04:45:45')
        self.assertEqual(details, {})

    def test_information_before_check_no_details(self):
        # .Information() where there is no channel.ini with version details,
        # and no previous CheckForUpdate() call was made.
        self._touch_build(45, datetime(2022, 8, 1, 4, 45, 45))
        response = self.iface.Information()
        self.assertEqual(response['current_build_number'], '45')
        self.assertEqual(response['device_name'], 'nexus7')
        self.assertEqual(response['channel_name'], 'stable')
        self.assertEqual(response['last_update_date'], '2022-08-01 04:45:45')
        self.assertEqual(response['version_detail'], '')
        self.assertEqual(response['last_check_date'], '')

    def test_information_no_details(self):
        # .Information() where there is no channel.ini with version details,
        # but a previous CheckForUpdate() call was made.
        self._touch_build(45, datetime(2022, 8, 1, 4, 45, 45))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Before we get the information, let's poke a known value into the
        # settings database.  Before we do that, make sure that the database
        # already has a value in it.
        config = Configuration()
        config.load(SystemImagePlugin.controller.ini_path)
        settings = Settings(config)
        real_last_check_date = settings.get('last_check_date')
        # We can't really test the last check date against anything in a
        # robust way.  E.g. what if we just happen to be at 12:59:59 on
        # December 31st?  Let's at least make sure it has a sane format.
        self.assertRegex(real_last_check_date,
                         r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        settings.set('last_check_date', '2055-08-01 21:12:00')
        response = self.iface.Information()
        self.assertEqual(response['current_build_number'], '45')
        self.assertEqual(response['device_name'], 'nexus7')
        self.assertEqual(response['channel_name'], 'stable')
        self.assertEqual(response['last_update_date'], '2022-08-01 04:45:45')
        self.assertEqual(response['version_detail'], '')
        self.assertEqual(response['last_check_date'], '2055-08-01 21:12:00')

    def test_information(self):
        # .Information() where there is a channel.ini with version details,
        # and a previous CheckForUpdate() call was made.
        self._touch_build(45)
        ini_path = Path(SystemImagePlugin.controller.ini_path)
        channel_path = ini_path.with_name('channel.ini')
        with channel_path.open('w', encoding='utf-8') as fp:
            print("""\
[service]
version_detail: ubuntu=222,mako=333,custom=444
""", file=fp)
        # Set last_update_date.
        timestamp = int(datetime(2022, 8, 1, 4, 45, 45).timestamp())
        os.utime(str(channel_path), (timestamp, timestamp))
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        # Before we get the information, let's poke a known value into the
        # settings database.  Before we do that, make sure that the database
        # already has a value in it.
        config = Configuration()
        config.load(SystemImagePlugin.controller.ini_path)
        settings = Settings(config)
        real_last_check_date = settings.get('last_check_date')
        # We can't really test the last check date against anything in a
        # robust way.  E.g. what if we just happen to be at 12:59:59 on
        # December 31st?  Let's at least make sure it has a sane format.
        self.assertRegex(real_last_check_date,
                         r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        settings.set('last_check_date', '2055-08-01 21:12:01')
        response = self.iface.Information()
        self.assertEqual(response['current_build_number'], '45')
        self.assertEqual(response['device_name'], 'nexus7')
        self.assertEqual(response['channel_name'], 'stable')
        self.assertEqual(response['last_update_date'], '2022-08-01 04:45:45')
        self.assertEqual(response['version_detail'], '')
        # We can't really check the returned last check date against anything
        # in a robust way.  E.g. what if we just happen to be at 12:59:59 on
        # December 31st?  Let's at least make sure it has a sane format.
        self.assertRegex(response['last_check_date'], '2055-08-01 21:12:01')


class TestLiveDBusInfoWithChannelIni(_LiveTesting):
    @classmethod
    def setUpClass(cls):
        # This must be done before the D-Bus service is started.
        ini_path = Path(SystemImagePlugin.controller.ini_path)
        channel_path = ini_path.with_name('channel.ini')
        with channel_path.open('w', encoding='utf-8') as fp:
            print("""\
[service]
version_detail: ubuntu=222,mako=333,custom=444
build_number: 42
""", file=fp)
        # Set last_update_date.
        timestamp = int(datetime(2022, 8, 1, 4, 45, 45).timestamp())
        os.utime(str(channel_path), (timestamp, timestamp))
        # Set the build number.
        config = Configuration()
        config.load(SystemImagePlugin.controller.ini_path)
        # We can't use _touch_build().
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(45, file=fp)
        super().setUpClass()

    def test_information_before_check(self):
        self._touch_build(45)
        # .Information() where there is a channel.ini with version details,
        # and no previous CheckForUpdate() call was made.
        response = self.iface.Information()
        self.assertEqual(response['current_build_number'], '42')
        self.assertEqual(response['device_name'], 'nexus7')
        self.assertEqual(response['channel_name'], 'stable')
        self.assertEqual(response['last_update_date'], '2022-08-01 04:45:45')
        self.assertEqual(response['version_detail'],
                         'ubuntu=222,mako=333,custom=444')
        self.assertEqual(response['last_check_date'], '')


class TestDBusFactoryReset(_LiveTesting):
    def test_factory_reset(self):
        # A factory reset is applied.
        command_file = os.path.join(
            self.config.updater.cache_partition, 'ubuntu_command')
        self.assertFalse(os.path.exists(self.reboot_log))
        self.assertFalse(os.path.exists(command_file))
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.FactoryReset)
        self.assertEqual(len(reactor.signals), 1)
        self.assertTrue(reactor.signals[0])
        with open(self.reboot_log, encoding='utf-8') as fp:
            reboot = fp.read()
        self.assertEqual(reboot, '/sbin/reboot -f recovery')
        with open(command_file, encoding='utf-8') as fp:
            command = fp.read()
        self.assertEqual(command, 'format data\n')


class TestDBusProgress(_LiveTesting):
    def test_progress(self):
        self.download_always()
        self._touch_build(0)
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # Start the download and watch the progress meters.
        reactor = ProgressRecordingReactor()
        reactor.schedule(self.iface.DownloadUpdate)
        reactor.run()
        # The only progress we can count on is the first and last ones.  All
        # will have an eta of 0, since that value is not calculatable right
        # now.  The first progress will have percentage 0 and the last will
        # have percentage 100.
        self.assertGreaterEqual(len(reactor.progress), 2)
        percentage, eta = reactor.progress[0]
        self.assertEqual(percentage, 0)
        self.assertEqual(eta, 0)
        percentage, eta = reactor.progress[-1]
        self.assertEqual(percentage, 100)
        self.assertEqual(eta, 0)


class TestDBusPauseResume(_LiveTesting):
    def setUp(self):
        super().setUp()
        # We have to hack the files to be rather large so that the download
        # doesn't complete before we get a chance to pause it.  Of course,
        # this breaks the signatures because we're changing the file contents
        # after the .asc files have been written.  We do have to update the
        # checksums in the index.json file, and then resign the index.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            full_path = os.path.join(
                SystemImagePlugin.controller.serverdir, path)
            with open(full_path, 'wb') as fp:
                # 300 MiB
                for i in range(76800):
                    fp.write(b'x' * 4096)
        # Disable the checksums - they just get in the way of these tests.
        index_path = os.path.join(SystemImagePlugin.controller.serverdir,
                                  'stable', 'nexus7', 'index.json')
        with open(index_path, 'r', encoding='utf-8') as fp:
            index = json.load(fp)
        for i in range(3):
            index['images'][0]['files'][i]['checksum'] = ''
        with open(index_path, 'w', encoding='utf-8') as fp:
            json.dump(index, fp)
        sign(index_path, 'device-signing.gpg')

    def test_pause(self):
        self.download_manually()
        self._touch_build(0)
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        # We're ready to start downloading.  We schedule a pause to happen in
        # a little bit and then ensure that we get the proper signal.
        reactor = PausingReactor(self.iface)
        reactor.schedule(self.iface.DownloadUpdate)
        reactor.run(timeout=15)
        self.assertTrue(reactor.paused)
        # There's a race condition between issuing the PauseDownload() call to
        # u-d-m and it reacting to send us a `paused` signal.  The best we can
        # know is that the pause percentage is in the range (0:100) and that
        # it's greater than the percentage at which we issued the pause.  Even
        # this is partly timing related, so we've hopefully tuned the file
        # size to be big enough to trigger the expected behavior.  There's no
        # other way to control the live u-d-m process.
        self.assertGreater(reactor.percentage, 0)
        self.assertLess(reactor.percentage, 100)
        self.assertGreaterEqual(reactor.percentage, reactor.pause_progress)
        # Now let's resume the download.  Because we intentionally corrupted
        # the downloaded files, we'll get an UpdateFailed signal instead of
        # the successful UpdateDownloaded signal.
        reactor = SignalCapturingReactor('UpdateFailed')
        reactor.run(self.iface.DownloadUpdate, timeout=60)
        self.assertEqual(len(reactor.signals), 1)
        # The error message will include lots of details on the SignatureError
        # that results.  The key thing is that it's 5.txt that is the first
        # file to fail its signature check.
        failure_count, last_error = reactor.signals[0]
        self.assertEqual(failure_count, 1)
        check_next = False
        for line in last_error.splitlines():
            line = line.strip()
            if check_next:
                self.assertEqual(os.path.basename(line), '5.txt')
                break
            if line.startswith('data path:'):
                check_next = True
        else:
            raise AssertionError('Did not find expected error output')


class TestDBusUseCache(_LiveTesting):
    # See LP: #1217098

    def test_use_cache(self):
        # We run the D-Bus service once through to download all the relevant
        # files.  Then we kill the service before performing the reboot, and
        # try to do another download.  The second one should only try to
        # download the ancillary files (i.e. channels.json, index.json,
        # keyrings), but not the data files.
        self.download_always()
        self._touch_build(0)
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
        config = Configuration()
        config.load(SystemImagePlugin.controller.ini_path)
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set((
                             '5.txt',
                             '5.txt.asc',
                             '6.txt',
                             '6.txt.asc',
                             '7.txt',
                             '7.txt.asc',
                             'device-signing.tar.xz',
                             'device-signing.tar.xz.asc',
                             'image-master.tar.xz',
                             'image-master.tar.xz.asc',
                             'image-signing.tar.xz',
                             'image-signing.tar.xz.asc',
                             'ubuntu_command',
                             )))
        # To prove that the data files are not downloaded again, let's
        # actually remove them from the server.
        for dirpath, dirnames, filenames in os.walk(
                SystemImagePlugin.controller.serverdir):
            for filename in filenames:
                if filename.endswith('.txt') or filename.endswith('.txt.asc'):
                    os.remove(os.path.join(dirpath, filename))
        # As extra proof, get the mtime in nanoseconds for the .txt and
        # .txt.asc files.
        mtimes = {}
        for filename in os.listdir(config.updater.cache_partition):
            path = os.path.join(config.updater.cache_partition, filename)
            if filename.endswith('.txt') or filename.endswith('.txt.asc'):
                mtimes[filename] = os.stat(path).st_mtime_ns
        # Don't issue the reboot.  Instead, kill the services, which throws
        # away all state, but does not delete the cached files.
        # Re-establish a new connection.
        process = find_dbus_process(SystemImagePlugin.controller.ini_path)
        if process is not None:
            self.iface.Exit()
            process.wait(60)
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        # Now, if we just apply the update, it will succeed, since it knows
        # that the cached files are valid.
        reactor = SignalCapturingReactor('Rebooting')
        reactor.run(self.iface.ApplyUpdate)
        self.assertEqual(len(reactor.signals), 1)
        self.assertTrue(reactor.signals[0])
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set((
                             '5.txt',
                             '5.txt.asc',
                             '6.txt',
                             '6.txt.asc',
                             '7.txt',
                             '7.txt.asc',
                             'device-signing.tar.xz',
                             'device-signing.tar.xz.asc',
                             'image-master.tar.xz',
                             'image-master.tar.xz.asc',
                             'image-signing.tar.xz',
                             'image-signing.tar.xz.asc',
                             # This file exists because reboot is mocked out
                             # in the dbus tests to just write to a log file.
                             'reboot.log',
                             'ubuntu_command',
                             )))
        for filename in os.listdir(config.updater.cache_partition):
            path = os.path.join(config.updater.cache_partition, filename)
            if filename.endswith('.txt') or filename.endswith('.txt.asc'):
                self.assertEqual(mtimes[filename], os.stat(path).st_mtime_ns)
        # Make sure the ubuntu_command file has the full update.
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
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


class TestDBusMultipleChecksInFlight(_LiveTesting):
    def test_multiple_check_for_updates(self):
        # Log analysis of LP: #1277589 appears to show the following scenario,
        # reproduced in this test case:
        #
        # * Automatic updates are enabled.
        # * No image signing or image master keys are present.
        # * A full update is checked.
        #   - A new image master key and image signing key is downloaded.
        #   - Update is available
        #
        # Start by creating some big files which will take a while to
        # download.
        def write_callback(dst):
            # Write a 100 MiB sized file.
            with open(dst, 'wb') as fp:
                for i in range(25600):
                    fp.write(b'x' * 4096)
        self._prepare_index('index_24.json', write_callback)
        # Create a reactor that will exit when the UpdateDownloaded signal is
        # received.  We're going to issue a CheckForUpdate with automatic
        # updates enabled.  As soon as we receive the UpdateAvailableStatus
        # signal, we'll immediately issue *another* CheckForUpdate, which
        # should run while the auto-download is working.
        #
        # As per LP: #1284217, we will get a second UpdateAvailableStatus
        # signal, since the status is available even while the original
        # request is being downloaded.
        reactor = DoubleCheckingReactor(self.iface)
        reactor.run()
        # We need to have received at least 2 signals, but due to timing
        # issues it could possibly be more.
        self.assertGreater(len(reactor.uas_signals), 1)
        # All received signals should have the same information.
        for signal in reactor.uas_signals:
            (is_available, downloading, available_version, update_size,
             last_update_date,
             #descriptions,
             error_reason) = signal
            self.assertTrue(is_available)
            self.assertTrue(downloading)
            self.assertEqual(available_version, '1600')
            self.assertEqual(update_size, 314572800)
            self.assertEqual(last_update_date, 'Unknown')
            self.assertEqual(error_reason, '')

    def test_multiple_check_for_updates_with_manual_downloading(self):
        # Log analysis of LP: #1287919 (a refinement of LP: #1277589 with
        # manual downloading enabled) shows that it's possible to enter the
        # checking phase while a download of the data files is still running.
        # When manually downloading, this will start another check, and as
        # part of that check, the blacklist and other files will be deleted
        # (in anticipation of them being re-downloaded).  When the data files
        # are downloaded, the state machine that just did the data download
        # may find its files deleted out from underneath it by the state
        # machine doing the checking.
        self.download_manually()
        # Start by creating some big files which will take a while to
        # download.
        def write_callback(dst):
            # Write a 100 MiB sized file.
            with open(dst, 'wb') as fp:
                for i in range(25600):
                    fp.write(b'x' * 4096)
        self._prepare_index('index_24.json', write_callback)
        self._touch_build(0)
        # Create a reactor that implements the following test plan:
        # * Set the device to download manually.
        # * Flash to an older revision
        # * Open System Settings and wait for it to say Updates available
        # * Click on About this phone
        # * Click on Check for Update and wait for it to say Install 1 update
        # * Click on Install 1 update and while the files are downloading,
        #   swipe up from the bottom and click Back
        # * Click on Check for Update again
        # * Wait for the Update System overlay to come up, and then install
        #   the update, and reboot
        reactor = ManualUpdateReactor(self.iface)
        reactor.run()
        self.assertTrue(reactor.rebooting)


class TestDBusCheckForUpdateToUnwritablePartition(_LiveTesting):
    @classmethod
    def setUpClass(cls):
        ini_path = SystemImagePlugin.controller.ini_path
        with open(ini_path, 'r', encoding='utf-8') as fp:
            lines = fp.readlines()
        with atomic(ini_path) as fp:
            for line in lines:
                key, sep, value = line.partition(': ')
                if key == 'cache_partition':
                    cls.bad_path = os.path.join(value.strip(), 'unwritable')
                    print('{}: {}'.format(key, cls.bad_path), file=fp)
                    os.makedirs(cls.bad_path, mode=0)
                else:
                    fp.write(line)
        super().setUpClass()

    def tearDown(self):
        os.chmod(self.bad_path, 0o777)
        super().tearDown()

    def test_check_for_update_error(self):
        # CheckForUpdate sees an error, in this case because the destination
        # directory for downloads is not writable.  We'll get an
        # UpdateAvailableStatus with an error string.
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         # descriptions,
         error_reason) = reactor.signals[0]
        self.assertIn('Permission denied', error_reason)


class TestDBusCheckForUpdateWithBrokenIndex(_LiveTesting):

    def test_bad_index_file_crashes_hash(self):
        # LP: #1222910.  A broken index.json file contained an image with type
        # == 'delta' but no base field.  This breaks the hash calculation of
        # that image and causes the check-for-update to fail.
        self._prepare_index('index_25.json')
        reactor = SignalCapturingReactor('UpdateAvailableStatus')
        reactor.run(self.iface.CheckForUpdate)
        self.assertEqual(len(reactor.signals), 1)
        (is_available, downloading, available_version, update_size,
         last_update_date,
         # descriptions,
         error_reason) = reactor.signals[0]
        self.assertEqual(
            error_reason, "'Image' object has no attribute 'base'")
