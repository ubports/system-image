# Copyright (C) 2014-2016 Canonical Ltd.
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

"""Download files via ubuntu-download-manager."""

__all__ = [
    'UDMDownloadManager',
    ]


import os
import dbus
import logging

from systemimage.config import config
from systemimage.download import Canceled, DownloadManagerBase
from systemimage.reactor import Reactor
from systemimage.settings import Settings

log = logging.getLogger('systemimage')

# Parameterized for testing purposes.
DOWNLOADER_INTERFACE = 'com.canonical.applications.Downloader'
MANAGER_INTERFACE = 'com.canonical.applications.DownloadManager'
OBJECT_NAME = 'com.canonical.applications.Downloader'
OBJECT_INTERFACE = 'com.canonical.applications.GroupDownload'


def _headers():
    return {'User-Agent': config.user_agent}


def _print(*args, **kws):
    # We must import this here to avoid circular imports.
    ## from systemimage.testing.helpers import debug
    ## with debug() as ddlog:
    ##     ddlog(*args, **kws)
    pass


class DownloadReactor(Reactor):
    def __init__(self, bus, object_path, callback=None,
                 pausable=False, signal_started=False):
        super().__init__(bus)
        self._callback = callback
        self._pausable = pausable
        self._signal_started = signal_started
        # For _do_pause() percentage calculation.
        self._received = 0
        self._total = 0
        self.error = None
        self.canceled = False
        self.local_paths = None
        self.react_to('canceled', object_path)
        self.react_to('error', object_path)
        self.react_to('finished', object_path)
        self.react_to('paused', object_path)
        self.react_to('progress', object_path)
        self.react_to('resumed', object_path)
        self.react_to('started', object_path)

    def _do_started(self, signal, path, started):
        _print('STARTED:', started)
        if self._signal_started and config.dbus_service is not None:
            config.dbus_service.DownloadStarted()

    def _do_finished(self, signal, path, local_paths):
        _print('FINISHED:', local_paths)
        self.local_paths = local_paths
        self.quit()

    def _do_error(self, signal, path, error_message):
        _print('ERROR:', error_message)
        log.error(error_message)
        self.error = error_message
        self.quit()

    def _do_progress(self, signal, path, received, total):
        _print('PROGRESS:', received, total)
        # For _do_pause() percentage calculation.
        self._received = received
        self._total = total
        self._callback(received, total)

    def _do_canceled(self, signal, path, canceled):
        # Why would we get this signal if it *wasn't* canceled?  Anyway,
        # this'll be a D-Bus data type so converted it to a vanilla Python
        # boolean.
        _print('CANCELED:', canceled)
        self.canceled = bool(canceled)
        self.quit()

    def _do_paused(self, signal, path, paused):
        _print('PAUSE:', paused, self._pausable)
        send_paused = self._pausable and config.dbus_service is not None
        if send_paused:                             # pragma: no branch
            # We could plumb through the `service` object from service.py (the
            # main entry point for system-image-dbus, but that's actually a
            # bit of a pain, so do the expedient thing and grab the interface
            # here.
            percentage = (int(self._received / self._total * 100.0)
                          if self._total > 0 else 0)
            config.dbus_service.UpdatePaused(percentage)

    def _do_resumed(self, signal, path, resumed):
        _print('RESUME:', resumed)
        # There currently is no UpdateResumed() signal.

    def _default(self, *args, **kws):
        _print('SIGNAL:', args, kws)                # pragma: no cover


class UDMDownloadManager(DownloadManagerBase):
    """Download via ubuntu-download-manager (UDM)."""

    def __init__(self, callback=None):
        super().__init__()
        if callback is not None:
            self.callbacks.append(callback)
        self._iface = None

    def _get_files(self, records, pausable, signal_started):
        assert self._iface is None
        bus = dbus.SystemBus()
        service = bus.get_object(DOWNLOADER_INTERFACE, '/')
        iface = dbus.Interface(service, MANAGER_INTERFACE)
        object_path = iface.createDownloadGroup(
            records,
            'sha256',
            False,        # Don't allow GSM yet.
            # https://bugs.freedesktop.org/show_bug.cgi?id=55594
            dbus.Dictionary(signature='sv'),
            _headers())
        download = bus.get_object(OBJECT_NAME, object_path)
        self._iface = dbus.Interface(download, OBJECT_INTERFACE)
        # Are GSM downloads allowed?  Yes, except if auto_download is set to 1
        # (i.e. wifi-only).
        allow_gsm = Settings().get('auto_download') != '1'
        # See if the CLI was called with --override-gsm.
        if not allow_gsm and config.override_gsm:
            log.info('GSM-only overridden')
            allow_gsm = True
        log.info('Allow GSM? {}', ('Yes' if allow_gsm else 'No'))
        UDMDownloadManager._set_gsm(self._iface, allow_gsm=allow_gsm)
        # Start the download.
        reactor = DownloadReactor(
            bus, object_path, self._reactor_callback, pausable, signal_started)
        reactor.schedule(self._iface.start)
        log.info('[{}] Running group download reactor', object_path)
        log.info('self: {}, self._iface: {}', self, self._iface)
        reactor.run()
        # This download is complete so the object path is no longer
        # applicable.  Setting this to None will cause subsequent cancels to
        # be queued.
        self._iface = None
        log.info('[{}] Group download reactor done', object_path)
        if reactor.error is not None:
            log.error('Reactor error: {}'.format(reactor.error))
        if reactor.canceled:
            log.info('Reactor canceled')
        # Report any other problems.
        if reactor.error is not None:
            raise FileNotFoundError(reactor.error)
        if reactor.canceled:
            raise Canceled
        if reactor.timed_out:
            raise TimeoutError
        # Sanity check the downloaded results.
        # First, every requested destination file must exist, otherwise
        # udm would not have given us a `finished` signal.
        missing = [record.destination for record in records
                   if not os.path.exists(record.destination)]
        if len(missing) > 0:                        # pragma: no cover
            local_paths = sorted(reactor.local_paths)
            raise AssertionError(
                'Missing destination files: {}\nlocal_paths: {}'.format(
                    missing, local_paths))

    def _reactor_callback(self, received, total):
        self.received = received
        self.total = total
        self._do_callback()

    @staticmethod
    def _set_gsm(iface, *, allow_gsm):
        # This is a separate method for easier testing via mocks.
        iface.allowGSMDownload(allow_gsm)

    @staticmethod
    def allow_gsm():
        """See `DownloadManagerBase`."""
        # We can't rely on self._iface being the interface of the group
        # download object.  Use getAllDownloads() on UDM to get the group
        # download object path, assert that there is only one group download
        # in progress, then call allowGSMDownload() on that.
        bus = dbus.SystemBus()
        service = bus.get_object(DOWNLOADER_INTERFACE, '/')
        iface = dbus.Interface(service, MANAGER_INTERFACE)
        try:
            object_paths = iface.getAllDownloads()
        except TypeError:
            # If there is no download in progress, udm will cause this
            # exception to occur.  Allow this to no-op.
            log.info('Ignoring GSM force when no download is in progress.')
            return
        assert len(object_paths) == 1, object_paths
        download = bus.get_object(OBJECT_NAME, object_paths[0])
        dbus.Interface(download, OBJECT_INTERFACE).allowGSMDownload(True)

    def cancel(self):
        """Cancel any current downloads."""
        if self._iface is None:
            # Since there's no download in progress right now, there's nothing
            # to cancel.  Setting this flag queues the cancel signal once the
            # reactor starts running again.  Yes, this is a bit weird, but if
            # we don't do it this way, the caller will immediately get a
            # Canceled exception, which isn't helpful because it's expecting
            # one when the next download begins.
            super().cancel()
        else:
            self._iface.cancel()

    def pause(self):
        """Pause the download, but only if one is in progress."""
        if self._iface is not None:                 # pragma: no branch
            self._iface.pause()

    def resume(self):
        """Resume the download, but only if one is in progress."""
        if self._iface is not None:                 # pragma: no branch
            self._iface.resume()
