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
    'Service',
    ]


from dbus.service import Object, method, signal
from gi.repository import GLib
from systemimage.api import Mediator
from systemimage.settings import Settings


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path)
        self._loop = loop
        self._api = Mediator()
        self._checking = False
        self._update = None
        self._downloading = False
        self._rebootable = False
        self._failure_count = 0

    def _check_for_update(self):
        # Asynchronous method call.
        self._update = self._api.check_for_update()
        # Do we have an update and can we auto-download it?
        downloading = False
        if self._update.is_available:
            settings = Settings()
            auto = settings.get('auto_download')
            if auto == '':
                # This has not yet been set.  The default is wifi-only.
                auto = '1'
                settings.set('auto_download', auto)
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
        if self._checking:
            # Check is already in progress, so there's nothing more to do.
            return
        self._checking = True
        # Arrange for the actual check to happen in a little while, so that
        # this method can return immediately.
        GLib.timeout_add(50, self._check_for_update)

    def _download(self):
        if (self._downloading                        # Already in progress.
            or self._update is None                  # Not yet checked.
            or not self._update.is_available         # No update available.
            ):
            return
        self._downloading = True
        try:
            self._api.download()
        except Exception as error:
            self._failure_count += 1
            self.UpdateFailed(self._failure_count, str(error))
        else:
            self.UpdateDownloaded()
            self._failure_count = 0
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
        GLib.timeout_add(50, self._download)

    @method('com.canonical.SystemImage')
    def PauseDownload(self, out_signature='s'):
        """Pause a downloading update."""
        # XXX 2013-08-22 We cannot currently pause downloads until we
        # integrate with the download service.  LP: #1196991
        return ""

    @method('com.canonical.SystemImage')
    def CancelUpdate(self, out_signature='s'):
        """Cancel a download."""
        self._api.cancel()
        self.Canceled()
        # XXX 2013-08-22: If we can't cancel the current download, return the
        # reason in this string.
        return ""

    @method('com.canonical.SystemImage')
    def Exit(self):
        """Quit the daemon immediately."""
        self._loop.quit()

    @method('com.canonical.SystemImage', out_signature='s')
    def ApplyUpdate(self):
        """Apply the update, rebooting the device."""
        if not self._rebootable:
            return 'No update has been downloaded'
        self._api.reboot()
        return ''

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

    @signal('com.canonical.SystemImage', signature='id')
    def UpdateProgress(self, percentage, eta):
        """Download progress."""

    @signal('com.canonical.SystemImage')
    def UpdateDownloaded(self):
        """The update has been successfully downloaded."""

    @signal('com.canonical.SystemImage', signature='is')
    def UpdateFailed(self, consecutive_failure_count, last_reason):
        """The update failed for some reason."""

    @signal('com.canonical.SystemImage', signature='i')
    def UpdatePaused(self, percentage):
        """The download got paused."""

    @method('com.canonical.SystemImage', in_signature='ss')
    def SetSetting(self, key, value):
        """Set a key/value setting.

        Some values are special, e.g. min_battery and auto_downloads.
        Implement these special semantics here.
        """
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
        return Settings().get(key)

    @signal('com.canonical.SystemImage', signature='ss')
    def SettingChanged(self, key, new_value):
        """A setting value has change."""
