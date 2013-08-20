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


import logging

from dbus.service import Object, method, signal
from gi.repository import GLib
from systemimage.api import Cancel, Mediator
from systemimage.settings import Settings


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path)
        self._loop = loop
        self._api = Mediator()
        self._checking = False
        self._completing = False
        self._rebootable = True

    def _check_for_update(self):
        # Asynchronous method call.
        update = self._api.check_for_update()
        # Do we have an update and can we auto-download it?
        downloading = False
        if update.is_available:
            settings = Settings()
            auto = settings.get('auto_download')
            if auto == '':
                # This has not yet been set.  The default is wifi-only.
                auto = '1'
                settings.set('auto_download', auto)
            if auto in ('1', '2'):
                # XXX When we have access to the download service, we can
                # check if we're on the wifi (auto == '1').
                GLib.timeout_add(100, self._download)
                downloading = True
        self.UpdateAvailableStatus(update.is_available,
                                   downloading,
                                   update.version,
                                   update.size,
                                   update.last_update_date,
                                   update.descriptions,
                                   "")
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
        GLib.timeout_add(100, self._check_for_update)

    def _download(self):
        pass

    def _complete_update(self):
        # Asynchronous method call.
        try:
            self._api.complete_update()
        except Cancel:
            # No additional Canceled signal is issued.
            pass
        except Exception:
            # If any other exception occurs, signal an UpdateFailed and log
            # the exception.
            log = logging.getLogger('systemimage')
            log.exception('GetUpdate() failed')
            self._rebootable = False
            self.UpdateFailed()
        else:
            self.ReadyToReboot()
        # Stop GLib from calling this method again.
        return False

    @method('com.canonical.SystemImage')
    def GetUpdate(self):
        """Download the available update.

        The download may be canceled during this time.
        """
        if self._completing:
            # Completing is already in progress, so there's nothing more to do.
            return
        self._completing = True
        # Arrange for the update to happen in a little while, so that this
        # method can return immediately.
        GLib.timeout_add(100, self._complete_update)

    @method('com.canonical.SystemImage')
    def Cancel(self):
        """Cancel a download and/or reboot.

        At any time between the `GetUpdate()` call and the `Reboot()` call, an
        upgrade may be canceled by calling this method.  Once canceled, the
        upgrade may not be restarted without killing the dbus client and
        restarting it.  The dbus client is short-lived any way, so it will
        timeout and restart via dbus activation automatically after a short
        period of time.
        """
        self._api.cancel()
        self.Canceled()

    @method('com.canonical.SystemImage')
    def Exit(self):
        """Quit the daemon immediately."""
        self._loop.quit()

    @method('com.canonical.SystemImage')
    def Reboot(self):
        """Reboot the device.

        Call this method after the download has completed.
        """
        if not self._rebootable:
            self.UpdateFailed()
            return
        try:
            self._api.reboot()
        except Cancel:
            # No additional Canceled signal is issued.
            pass
        except Exception:
            # If any other exception occurs, signal an UpdateFailed and log
            # the exception.
            log = logging.getLogger('systemimage')
            log.exception('Reboot() failed')
            self.UpdateFailed()

    @signal('com.canonical.SystemImage', signature='bbiisaa{ss}s')
    def UpdateAvailableStatus(self,
                              is_available, downloading,
                              available_version, update_size,
                              last_update_date, descriptions,
                              error_reason):
        """Signal sent in response to a CheckForUpdate()."""

    @signal('com.canonical.SystemImage')
    def ReadyToReboot(self):
        """The device is ready to reboot.

        This signal is sent whenever the download of an update is complete,
        and the device is ready to be rebooted to apply the update.
        """

    @signal('com.canonical.SystemImage')
    def UpdateFailed(self):
        """The update failed for some reason."""

    @signal('com.canonical.SystemImage')
    def Canceled(self):
        """A download has been canceled.

        This signal is sent whenever the download of an update has been
        canceled.  The cancellation can occur any time prior to a reboot being
        issued.
        """

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
        Settings().set(key, value)

    @method('com.canonical.SystemImage', in_signature='s', out_signature='s')
    def GetSetting(self, key):
        """Get a setting."""
        return Settings().get(key)
