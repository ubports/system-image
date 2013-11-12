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

"""DBus service."""

__all__ = [
    'Loop',
    'Service',
    ]


import os
import sys
import traceback

from dbus.service import Object, method, signal
from gi.repository import GLib
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.helpers import last_update_date, version_detail
from systemimage.settings import Settings


EMPTYSTRING = ''


class Loop:
    """Keep track of the main loop."""

    def __init__(self):
        self._loop = GLib.MainLoop()
        self._quitter = None

    def keepalive(self):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        self._quitter = GLib.timeout_add_seconds(
            config.dbus.lifetime.total_seconds(),
            self.quit)

    def quit(self):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        self._loop.quit()

    def run(self):
        self._loop.run()


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path)
        self._loop = loop
        self._api = Mediator(self._progress_callback)
        self._checking = False
        self._update = None
        self._downloading = False
        self._paused = False
        self._rebootable = False
        self._failure_count = 0
        self._last_error = ''

    def _check_for_update(self):
        # Asynchronous method call.
        self._update = self._api.check_for_update()
        # Do we have an update and can we auto-download it?
        downloading = False
        if self._update.is_available:
            settings = Settings()
            auto = settings.get('auto_download')
            if auto in ('1', '2'):
                # XXX When we have access to the download service, we can
                # check if we're on the wifi (auto == '1').
                GLib.timeout_add(50, self._download)
                downloading = True
        self.UpdateAvailableStatus(
            self._update.is_available,
            downloading,
            self._update.version,
            self._update.size,
            self._update.last_update_date,
            # XXX 2013-08-22 - the u/i cannot currently currently handle the
            # array of dictionaries data type.  LP: #1215586
            #self._update.descriptions,
            "")
        self._checking = False
        # Stop GLib from calling this method again.
        return False

    # 2013-07-25 BAW: should we use the rather underdocumented async_callbacks
    # argument to @method?
    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        """Find out whether an update is available.

        This method is used to explicitly check whether an update is
        available, by communicating with the server and calculating an
        upgrade path from the current build number to a later build
        available on the server.

        This method runs asynchronously and thus does not return a result.
        Instead, an `UpdateAvailableStatus` signal is triggered when the check
        completes.  The argument to that signal is a boolean indicating
        whether the update is available or not.
        """
        self._loop.keepalive()
        if self._checking:
            # Check is already in progress, so there's nothing more to do.
            return
        self._checking = True
        # Reset any failure or in-progress state.  Get a new mediator to reset
        # any of its state.
        self._api = Mediator(self._progress_callback)
        self._failure_count = 0
        self._last_error = ''
        # Arrange for the actual check to happen in a little while, so that
        # this method can return immediately.
        GLib.timeout_add(50, self._check_for_update)

    def _progress_callback(self, received, total):
        # Plumb the progress through our own D-Bus API.  Our API is defined as
        # signalling a percentage and an eta.  We can calculate the percentage
        # easily, but the eta is harder.  For now, we just send 0 as the eta.
        percentage = received * 100 // total
        eta = 0
        self.UpdateProgress(percentage, eta)

    def _download(self):
        if self._downloading and self._paused:
            self._api.resume()
            self._paused = False
            return
        if (self._downloading                        # Already in progress.
            or self._update is None                  # Not yet checked.
            or not self._update.is_available         # No update available.
            ):
            return
        if self._failure_count > 0:
            self._failure_count += 1
            self.UpdateFailed(self._failure_count, self._last_error)
            return
        self._downloading = True
        try:
            # Always start by sending a UpdateProgress(0, 0).  This is enough
            # to get the u/i's attention.
            self.UpdateProgress(0, 0)
            self._api.download()
        except Exception:
            self._failure_count += 1
            # This will return both the exception name and the exception
            # value, but not the traceback.
            self._last_error = EMPTYSTRING.join(
                traceback.format_exception_only(*sys.exc_info()[:2]))
            self.UpdateFailed(self._failure_count, self._last_error)
        else:
            self.UpdateDownloaded()
            self._failure_count = 0
            self._last_error = ''
            self._rebootable = True
        self._downloading = False
        # Stop GLib from calling this method again.
        return False

    @method('com.canonical.SystemImage')
    def DownloadUpdate(self):
        """Download the available update.

        The download may be canceled during this time.
        """
        # Arrange for the update to happen in a little while, so that this
        # method can return immediately.
        self._loop.keepalive()
        GLib.timeout_add(50, self._download)

    @method('com.canonical.SystemImage', out_signature='s')
    def PauseDownload(self):
        """Pause a downloading update."""
        self._loop.keepalive()
        if self._downloading:
            self._api.pause()
            self._paused = True
            error_message = ''
        else:
            error_message = 'not downloading'
        return error_message

    @method('com.canonical.SystemImage', out_signature='s')
    def CancelUpdate(self):
        """Cancel a download."""
        self._loop.keepalive()
        self._api.cancel()
        # We're now in a failure state until the next CheckForUpdate.
        self._failure_count += 1
        self._last_error = 'Canceled'
        # Only send this signal if we were in the middle of downloading.
        if self._downloading:
            self.UpdateFailed(self._failure_count, self._last_error)
        # XXX 2013-08-22: If we can't cancel the current download, return the
        # reason in this string.
        return ''

    def _apply_update(self):
        # This signal may or may not get sent.  We're racing against the
        # system reboot procedure.
        self._loop.keepalive()
        if not self._rebootable:
            command_file = os.path.join(
                config.updater.cache_partition, 'ubuntu_command')
            if not os.path.exists(command_file):
                # Not enough has been downloaded to allow for a reboot.
                self.Rebooting(False)
                return
        self._api.reboot()
        self.Rebooting(True)

    @method('com.canonical.SystemImage')
    def ApplyUpdate(self):
        """Apply the update, rebooting the device."""
        GLib.timeout_add(50, self._apply_update)

    @method('com.canonical.SystemImage', out_signature='isssa{ss}')
    def Info(self):
        self._loop.keepalive()
        return (config.build_number,
                config.device,
                config.channel,
                last_update_date(),
                version_detail())

    @method('com.canonical.SystemImage', in_signature='ss')
    def SetSetting(self, key, value):
        """Set a key/value setting.

        Some values are special, e.g. min_battery and auto_downloads.
        Implement these special semantics here.
        """
        self._loop.keepalive()
        if key == 'min_battery':
            try:
                as_int = int(value)
            except ValueError:
                return
            if as_int < 0 or as_int > 100:
                return
        if key == 'auto_download':
            try:
                as_int = int(value)
            except ValueError:
                return
            if as_int not in (0, 1, 2):
                return
        settings = Settings()
        old_value = settings.get(key)
        settings.set(key, value)
        if value != old_value:
            # Send the signal.
            self.SettingChanged(key, value)

    @method('com.canonical.SystemImage', in_signature='s', out_signature='s')
    def GetSetting(self, key):
        """Get a setting."""
        self._loop.keepalive()
        return Settings().get(key)

    @method('com.canonical.SystemImage')
    def Exit(self):
        """Quit the daemon immediately."""
        self._loop.quit()

    # XXX 2013-08-22 The u/i cannot currently handle the array of dictionaries
    # data type for the descriptions.  LP: #1215586
    #@signal('com.canonical.SystemImage', signature='bbsisaa{ss}s')
    @signal('com.canonical.SystemImage', signature='bbsiss')
    def UpdateAvailableStatus(self,
                              is_available, downloading,
                              available_version, update_size,
                              last_update_date,
                              #descriptions,
                              error_reason):
        """Signal sent in response to a CheckForUpdate()."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage', signature='id')
    def UpdateProgress(self, percentage, eta):
        """Download progress."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage')
    def UpdateDownloaded(self):
        """The update has been successfully downloaded."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage', signature='is')
    def UpdateFailed(self, consecutive_failure_count, last_reason):
        """The update failed for some reason."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage', signature='i')
    def UpdatePaused(self, percentage):
        """The download got paused."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage', signature='ss')
    def SettingChanged(self, key, new_value):
        """A setting value has change."""
        self._loop.keepalive()

    @signal('com.canonical.SystemImage', signature='b')
    def Rebooting(self, status):
        """The system is rebooting."""
        # We don't need to keep the loop alive since we're probably just going
        # to shutdown anyway.
