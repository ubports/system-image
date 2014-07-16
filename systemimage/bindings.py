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

"""Helpers for when the command line script is used as a DBus client."""


__all__ = [
    'DBusClient',
    'UASRecord',
    ]


import dbus
import logging

from collections import namedtuple
from systemimage.reactor import Reactor

log = logging.getLogger('systemimage')


# Use a namedtuple for more convenient argument unpacking.
UASRecord = namedtuple('UASRecord',
    'is_available downloading available_version update_size '
    'last_update_date error_reason')


class DBusClient(Reactor):
    """Python bindings to be used as a DBus client."""

    def __init__(self):
        super().__init__(dbus.SystemBus())
        service = self._bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        self.react_to('UpdateAvailableStatus')
        self.react_to('UpdateDownloaded')
        self.react_to('UpdateFailed')
        self.failed = False
        self.is_available = False
        self.downloaded = False

    def _do_UpdateAvailableStatus(self, signal, path, *args):
        payload = UASRecord(*args)
        if payload.error_reason != '':
            # Cancel the download, set the failed flag and log the reason.
            log.error('CheckForUpdate returned an error: {}',
                      payload.error_reason)
            self.failed = True
            self.quit()
            return
        if not payload.is_available:
            log.info('No update available')
            self.quit()
            return
        if not payload.downloading:
            # We should be in auto download mode, so why aren't we downloading
            # the update?  Do it manually.
            log.info('Update available, downloading manually')
            self.iface.DownloadUpdate()
        self.is_available = True

    def _do_UpdateDownloaded(self, signal, path):
        self.downloaded = True
        self.quit()

    def _do_UpdateFailed(self, signal, path,
                         consecutive_failure_count, last_reason):
        log.error('UpdateFailed: {}', last_reason)
        self.failed = True
        self.quit()

    def check_for_update(self):
        # Switch to auto-download mode for this run.
        old_value = self.iface.GetSetting('auto_download')
        self.iface.SetSetting('auto_download', '2')
        self.schedule(self.iface.CheckForUpdate)
        self.run()
        self.iface.SetSetting('auto_download', old_value)

    def _do_Rebooting(self, signal, path, status):
        self.quit()

    def reboot(self):
        self.react_to('Rebooting')
        self.schedule(self.iface.ApplyUpdate)
        self.run()
