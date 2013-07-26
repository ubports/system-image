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


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)
        self._api = Mediator()
        self._checking = False
        self._completing = False
        self._rebootable = True

    @method('com.canonical.SystemImage', out_signature='i')
    def BuildNumber(self):
        """Return the system's current build number.

        :return: The current build number.
        :rtype: int
        """
        return self._api.get_build_number()

    def _check_for_update(self):
        # Asynchronous method call.
        update = self._api.check_for_update()
        self.UpdateAvailableStatus(bool(update))
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

    @method('com.canonical.SystemImage', out_signature='x')
    def GetUpdateSize(self):
        """Return the size in bytes of an available update.

        This method performs an implicit check for update, if one has not been
        previously done.  If no update is available, a size of zero is
        returned.

        :return: Size in bytes of any available update.
        :rtype: int
        """
        return self._api.check_for_update().size

    @method('com.canonical.SystemImage', out_signature='i')
    def GetUpdateVersion(self):
        """Return the build version for the update.

        The number returned from this method is the build number that the
        device will be left at, after any available update is applied.

        This method performs an implicit check for update, if one has
        not been previously done.  If no update is available, a build
        version of zero is returned.

        :return: Future build number, should the update be applied.
        :rtype: int
        """
        return self._api.check_for_update().version

    @method('com.canonical.SystemImage', out_signature='aa{ss}')
    def GetDescriptions(self):
        """Return all the descriptions for the available update.

        If an update is available, this method will return a list of
        dictionaries.  The number of items in this list will reflect the
        number of images that are downloaded in order to apply the update.
        Each image can come with a set of descriptions, in multiple languages,
        for the updates contained in that image.  The keys of the dictionaries
        always start with 'description' and may have suffixes indicating the
        language code for the description.  Thus, each image may have multiple
        descriptions in multiple languages.  The dictionary values are the
        UTF-8 encoded Unicode descriptions for the language specified in the
        key.

        This method performs an implicit check for update, if one has
        not been previously done.  If no update is available, an empty list is
        returned.

        :return: The descriptions in all languages for all images included in
            the winning update path.
        :rtype: list of dictionaries
        """
        return self._api.check_for_update().descriptions

    def _complete_update(self):
        # Asynchronous method call.
        try:
            self._api.complete_update()
        except Cancel:
            self.Canceled()
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
            self.Canceled()
        except Exception:
            # If any other exception occurs, signal an UpdateFailed and log
            # the exception.
            log = logging.getLogger('systemimage')
            log.exception('Reboot() failed')
            self.UpdateFailed()

    @signal('com.canonical.SystemImage', signature='b')
    def UpdateAvailableStatus(self, flag):
        """Signal sent when update checking is complete.

        This signal is sent whenever the asynchronous checking for an update
        completes.  Its argument includes the flag specifying whether an
        update is available or not.
        """

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
