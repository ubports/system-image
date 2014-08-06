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

"""Helpers for the DBus service when run with --testing."""

__all__ = [
    'get_service',
    'instrument',
    ]


import os

from dbus.service import method, signal
from gi.repository import GLib
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.dbus import Service
from systemimage.helpers import MiB, makedirs, safe_remove, version_detail
from unittest.mock import patch


SPACE = ' '
SIGNAL_DELAY_SECS = 5


class _ActionLog:
    def __init__(self, filename):
        self._path = os.path.join(config.updater.cache_partition, filename)

    def write(self, *args, **kws):
        with open(self._path, 'w', encoding='utf-8') as fp:
            fp.write(SPACE.join(args[0]).strip())


def instrument(config, stack):
    """Instrument the system for testing."""
    # Ensure the destination directories exist.
    makedirs(config.updater.data_partition)
    makedirs(config.updater.cache_partition)
    # Patch the subprocess call to write the reboot command to a log
    # file which the testing parent process can open and read.
    safe_reboot = _ActionLog('reboot.log')
    stack.enter_context(
        patch('systemimage.reboot.check_call', safe_reboot.write))
    stack.enter_context(
        patch('systemimage.device.check_output', return_value='nexus7'))
    # Integrate with subprocess coverage.
    ## from systemimage.testing.helpers import debug
    ## ini_file = os.environ.get('COVERAGE_PROCESS_START')
    ## if ini_file is not None:
    ##     with debug() as ddlog:
    ##         ddlog('DBUS:', ini_file)
    ##     try:
    ##         import coverage
    ##     except ImportError as e:
    ##         with debug() as ddlog:
    ##             ddlog('DBUS: Could not import coverage', e)
    ##         pass
    ##     else:
    ##         with debug() as ddlog:
    ##             ddlog('DBUS: starting coverage:',
    ##                   os.getpid(), os.getcwd())
    ##         coverage.process_startup()
    ##         with debug() as ddlog:
    ##             ddlog('DBUS: coverage started')


class _LiveTestableService(Service):
    """For testing purposes only."""

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._api = Mediator()
        try:
            self._checking.release()
        except RuntimeError:
            # Lock is already released.
            pass
        self._update = None
        self._downloading = False
        self._rebootable = False
        self._failure_count = 0
        del config.build_number
        safe_remove(config.system.settings_db)

    @method('com.canonical.SystemImage')
    def TearDown(self):
        # Like CancelUpdate() except it sends a different signal that's only
        # useful for the test suite.
        self._api.cancel()
        self.TornDown()

    @signal('com.canonical.SystemImage')
    def TornDown(self):
        pass


class _UpdateAutoSuccess(Service):
    """Normal update in auto-download mode."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path, loop)
        self._reset()

    def _reset(self):
        self._auto_download = True
        self._canceled = False
        self._downloading = False
        self._eta = 50.0
        self._failure_count = 0
        self._paused = False
        self._percentage = 0
        self._rebootable = False

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._reset()

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        if self._failure_count > 0:
            self._reset()
        GLib.timeout_add_seconds(3, self._send_status)

    def _send_status(self):
        if self._auto_download:
            self._downloading = True
        self.UpdateAvailableStatus(
            True, self._downloading, '42', 1337 * MiB,
            '1983-09-13T12:13:14',
            '')
        if self._downloading and not self._rebootable:
            self.UpdateProgress(0, 50.0)
            GLib.timeout_add(500, self._send_more_status)
        if self._paused:
            self.UpdatePaused(self._percentage)
        elif self._rebootable:
            self.UpdateDownloaded()
        return False

    def _send_more_status(self):
        if self._canceled:
            self._downloading = False
            self._failure_count += 1
            self.UpdateFailed(self._failure_count, 'canceled')
            return False
        if not self._paused:
            self._percentage += 1
            self._eta -= 0.5
            if self._percentage == 100:
                # We're done.
                self._downloading = False
                self._rebootable = True
                self.UpdateDownloaded()
                return False
            self.UpdateProgress(self._percentage, self._eta)
        # Continue sending more status.
        return True

    @method('com.canonical.SystemImage', out_signature='s')
    def PauseDownload(self):
        if self._downloading:
            self._paused = True
            self.UpdatePaused(self._percentage)
        # Otherwise it's a no-op.
        return ''

    @method('com.canonical.SystemImage')
    def DownloadUpdate(self):
        self._paused = False
        if not self._downloading:
            if not self._auto_download:
                self._downloading = True
                self.UpdateProgress(0, 50.0)
                GLib.timeout_add(500, self._send_more_status)

    @method('com.canonical.SystemImage', out_signature='s')
    def CancelUpdate(self):
        if self._downloading:
            self._canceled = True
        # Otherwise it's a no-op.
        return ''

    @method('com.canonical.SystemImage')
    def ApplyUpdate(self):
        # Always succeeds.
        def _rebooting():
            self.Rebooting(True)
        GLib.timeout_add(50, _rebooting)


class _UpdateManualSuccess(_UpdateAutoSuccess):
    def _reset(self):
        super()._reset()
        self._auto_download = False


class _UpdateFailed(Service):
    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path, loop)
        self._reset()

    def _reset(self):
        self._failure_count = 1

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._reset()

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        msg = ('You need some network for downloading'
               if self._failure_count > 0
               else '')
        self.UpdateAvailableStatus(
            True, False, '42', 1337 * MiB,
            '1983-09-13T12:13:14',
            msg)
        if self._failure_count > 0:
            self._failure_count += 1
            self.UpdateFailed(self._failure_count, msg)

    @method('com.canonical.SystemImage', out_signature='s')
    def CancelUpdate(self):
        self._failure_count = 0
        return ''


class _FailApply(Service):
    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        self.UpdateAvailableStatus(
            True, False, '42', 1337 * MiB,
            '1983-09-13T12:13:14',
            '')
        self.UpdateDownloaded()

    @method('com.canonical.SystemImage')
    def ApplyUpdate(self):
        # The update cannot be applied.
        def _rebooting():
            self.Rebooting(False)
        GLib.timeout_add(50, _rebooting)


class _FailResume(Service):
    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        self.UpdateAvailableStatus(
            True, False, '42', 1337 * MiB,
            '1983-09-13T12:13:14',
            '')
        self.UpdatePaused(42)

    @method('com.canonical.SystemImage')
    def DownloadUpdate(self):
        self.UpdateFailed(9, 'You need some network for downloading')


class _FailPause(Service):
    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        self.UpdateAvailableStatus(
            True, True, '42', 1337 * MiB,
            '1983-09-13T12:13:14',
            '')
        self.UpdateProgress(10, 0)

    @method('com.canonical.SystemImage', out_signature='s')
    def PauseDownload(self):
        return 'no no, not now'


class _NoUpdate(Service):
    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        GLib.timeout_add_seconds(3, self._send_status)

    def _send_status(self):
        self.UpdateAvailableStatus(
            False, False, '', 0,
            '1983-09-13T12:13:14',
            '')


class _MoreInfo(Service):
    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path, loop)
        self._buildno = 45
        self._device = 'nexus11'
        self._channel = 'daily-proposed'
        self._updated = '2099-08-01 04:45:45'
        self._version = 'ubuntu=123,mako=456,custom=789'
        self._checked = '2099-08-01 04:45:00'

    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage', out_signature='isssa{ss}')
    def Info(self):
        return (self._buildno, self._device, self._channel, self._updated,
                version_detail(self._version))

    @method('com.canonical.SystemImage', out_signature='a{ss}')
    def Information(self):
        return dict(current_build_number=str(self._buildno),
                    device_name=self._device,
                    channel_name=self._channel,
                    last_update_date=self._updated,
                    version_detail=self._version,
                    last_check_date=self._checked)


def get_service(testing_mode, system_bus, object_path, loop):
    """Return the appropriate service class for the testing mode."""
    if testing_mode == 'live':
        ServiceClass = _LiveTestableService
    elif testing_mode == 'update-auto-success':
        ServiceClass = _UpdateAutoSuccess
    elif testing_mode == 'update-manual-success':
        ServiceClass = _UpdateManualSuccess
    elif testing_mode == 'update-failed':
        ServiceClass = _UpdateFailed
    elif testing_mode == 'fail-apply':
        ServiceClass = _FailApply
    elif testing_mode == 'fail-resume':
        ServiceClass = _FailResume
    elif testing_mode == 'fail-pause':
        ServiceClass = _FailPause
    elif testing_mode == 'no-update':
        ServiceClass = _NoUpdate
    elif testing_mode == 'more-info':
        ServiceClass = _MoreInfo
    else:
        raise RuntimeError('Invalid testing mode: {}'.format(testing_mode))
    return ServiceClass(system_bus, object_path, loop)
