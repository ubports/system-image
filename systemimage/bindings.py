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

"""Helpers for when the command line script is used as a DBus client."""


__all__ = [
    'DBusClient',
    ]


import dbus
import logging

from gi.repository import GLib

log = logging.getLogger('systemimage')


class DBusClient:
    """Python bindings to be used as a DBus client."""

    def __init__(self):
        self.bus = dbus.SystemBus()
        service = self.bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        for signal in ('UpdateAvailableStatus',
                       'UpdateDownloaded', 'UpdateFailed'):
            self.bus.add_signal_receiver(
                self._handle, signal_name=signal,
                member_keyword='member',
                dbus_interface='com.canonical.SystemImage')
        self.failed = False
        self.is_available = False
        self.downloaded = False

    def _handle(self, *args, **kws):
        signal = kws.pop('member')
        handler = getattr(self, '_do_' + signal, None)
        if handler is not None:
            handler(*args, **kws)

    def _run(self, method):
        self.loop = GLib.MainLoop()
        GLib.timeout_add(50, method)
        quitter_id = GLib.timeout_add_seconds(600, self.loop.quit)
        self.loop.run()
        GLib.source_remove(quitter_id)

    def _do_UpdateAvailableStatus(self, is_available, downloading,
                                  available_version, update_size,
                                  last_update_date,
                                  #descriptions,
                                  error_reason):
        if error_reason != '':
            # Cancel the download, set the failed flag and log the reason.
            log.error('CheckForUpdate returned an error: {}', error_reason)
            self.failed = True
            self.loop.quit()
            return
        if not is_available:
            log.info('No update available')
            self.loop.quit()
            return
        if not downloading:
            # We should be in auto download mode, so why aren't we downloading
            # the update?  Do it manually.
            log.info('Update available, downloading manually')
            self.iface.DownloadUpdate()
        self.is_available = True

    def _do_UpdateDownloaded(self):
        self.downloaded = True
        self.loop.quit()

    def _do_UpdateFailed(self, consecutive_failure_count, last_reason):
        log.error('UpdateFailed: {}', last_reason)
        self.failed = True
        self.loop.quit()

    def check_for_update(self):
        # Switch to auto-download mode for this run.
        old_value = self.iface.GetSetting('auto_download')
        self.iface.SetSetting('auto_download', '2')
        self._run(self.iface.CheckForUpdate)
        self.iface.SetSetting('auto_download', old_value)

    def reboot(self):
        self.iface.ApplyUpdate()
