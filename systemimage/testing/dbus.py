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

"""Helpers for the DBus service when run with --testing."""

__all__ = [
    'get_service',
    'instrument',
    ]


import os

from dbus.service import method
from functools import partial
from gi.repository import GLib
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.dbus import Service
from systemimage.helpers import makedirs, safe_remove
from systemimage.testing.helpers import data_path
from unittest.mock import patch
from urllib.request import urlopen


SPACE = ' '
SIGNAL_DELAY_SECS = 5


class _ActionLog:
    def __init__(self, filename):
        makedirs(config.updater.cache_partition)
        self._path = os.path.join(config.updater.cache_partition, filename)

    def write(self, *args, **kws):
        with open(self._path, 'w', encoding='utf-8') as fp:
            fp.write(SPACE.join(args[0]).strip())


def instrument(config, stack):
    """Instrument the system for testing."""
    # The testing infrastructure requires that the built-in downloader
    # accept self-signed certificates.  We have to invoke the context
    # manager here so that the function actually gets patched.
    stack.enter_context(
        patch('systemimage.download.urlopen',
              partial(urlopen, cafile=data_path('cert.pem'))))
    # Patch the subprocess call to write the reboot command to a log
    # file which the testing parent process can open and read.
    safe_reboot = _ActionLog('reboot.log')
    stack.enter_context(
        patch('systemimage.reboot.check_call', safe_reboot.write))
    stack.enter_context(
        patch('systemimage.device.check_output', return_value='nexus7'))


class _LiveTestableService(Service):
    """For testing purposes only."""

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._api = Mediator()
        self._checking = False
        self._update = None
        self._downloading = False
        self._rebootable = False
        self._failure_count = 0
        safe_remove(config.system.state_file)
        safe_remove(config.system.settings_db)


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
        self.UpdateAvailableStatus(
            True, self._auto_download, '42', 1337 * 1024 * 1024,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #"}],
            '')
        if (    self._auto_download and
                not self._downloading and
                not self._rebootable):
            self._downloading = True
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

    @method('com.canonical.SystemImage', out_signature='s')
    def ApplyUpdate(self):
        # Always succeeds.
        return ''


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
            True, False, '42', 1337 * 1024 * 1024,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #}],
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
            True, False, '42', 1337 * 1024 * 1024,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #}],
            '')
        self.UpdateDownloaded()

    @method('com.canonical.SystemImage', out_signature='s')
    def ApplyUpdate(self):
        # The update cannot be applied.
        return 'Not enough battery, you need to plug in your phone'


class _FailResume(Service):
    @method('com.canonical.SystemImage')
    def Reset(self):
        pass

    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        self.UpdateAvailableStatus(
            True, False, '42', 1337 * 1024 * 1024,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #}],
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
            True, True, '42', 1337 * 1024 * 1024,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #}],
            '')
        self.UpdateProgress(10, 0)

    @method('com.canonical.SystemImage', out_signature='s')
    def PauseDownload(self):
        return 'no no, not now'

class _NoUpdate(Service):
    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        GLib.timeout_add_seconds(3, self._send_status)

    def _send_status(self):
        self.UpdateAvailableStatus(
            False, False, '', 0,
            '1983-09-13T12:13:14',
            #[
            #{'description': 'Ubuntu Edge support',
            # 'description-en_GB': 'change the background colour',
            # 'description-fr': "Support d'Ubuntu Edge",
            #},
            #{'description':
            # 'Flipped container with 200% boot speed improvement',
            #}],
            '')


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
    else:
        raise RuntimeError('Invalid testing mode: {}'.format(testing_mode))
    return ServiceClass(system_bus, object_path, loop)
