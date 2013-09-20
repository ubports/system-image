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

"""Download files."""

__all__ = [
    'Canceled',
    'DBusDownloadManager',
    'get_files',
    ]


import dbus
import logging

from gi.repository import GLib
from systemimage.config import config


# Parameterized for testing purposes.
DOWNLOADER_INTERFACE = 'com.canonical.applications.Downloader'
MANAGER_INTERFACE = 'com.canonical.applications.DownloadManager'
OBJECT_NAME = 'com.canonical.applications.Downloader'
OBJECT_INTERFACE = 'com.canonical.applications.GroupDownload'
SIGNALS = ('started', 'paused', 'resumed', 'canceled', 'finished',
           'error', 'progress')
USER_AGENT = 'Ubuntu System Image Upgrade Client; Build {}'
TIMEOUT_SECONDS = 10

log = logging.getLogger('systemimage')


def _headers():
    return {'User-Agent': USER_AGENT.format(config.build_number)}


class Canceled(BaseException):
    """Raised when the download was canceled."""



class Reactor:
    """A reactor base class for DBus signals."""

    def __init__(self, bus):
        self._bus = bus
        self._loop = None
        self._quitters = []
        self._signal_matches = []
        self.timeout = TIMEOUT_SECONDS

    def _handle_signal(self, *args, **kws):
        signal = kws.pop('member')
        path = kws.pop('path')
        method = getattr(self, '_do_' + signal, None)
        if method is None:
            # See if there's a default catch all.
            method = getattr(self, '_default', None)
        if method is None:
            log.info('No handler for signal {}: {} {}', signal, args, kws)
        else:
            method(signal, path, *args, **kws)

    def react_to(self, signal):
        signal_match = self._bus.add_signal_receiver(
            self._handle_signal, signal_name=signal,
            member_keyword='member',
            path_keyword='path')
        self._signal_matches.append(signal_match)

    def schedule(self, method, milliseconds=50):
        GLib.timeout_add(milliseconds, method)

    def run(self):
        self._loop = GLib.MainLoop()
        source_id = GLib.timeout_add_seconds(self.timeout, self.quit)
        self._quitters.append(source_id)
        self._loop.run()

    def quit(self):
        self._loop.quit()
        for match in self._signal_matches:
            match.remove()
        del self._signal_matches[:]
        for source_id in self._quitters:
            GLib.source_remove(source_id)
        del self._quitters[:]


class DownloadReactor(Reactor):
    def __init__(self, bus, callback=None):
        super().__init__(bus)
        self._callback = callback
        self.error = None
        self.canceled = False
        self.react_to('canceled')
        self.react_to('error')
        self.react_to('finished')
        self.react_to('paused')
        self.react_to('progress')
        self.react_to('resumed')
        self.react_to('started')

    def _print(*args, **kws):
        import sys; kws['file'] = sys.stderr
        print(*args, **kws)
        pass

    def _do_finished(self, signal, path, local_paths):
        self._print('FINISHED:', local_paths)
        self.quit()

    def _do_error(self, signal, path, error_message):
        self._print('ERROR:', error_message)
        log.error(error_message)
        self.error = error_message
        self.quit()

    def _do_progress(self, signal, path, received, total):
        self._print('PROGRESS:', received, total)
        if self._callback is not None:
            self._callback(received, total)

    def _do_canceled(self, signal, path, canceled):
        # Why would we get this signal if it *wasn't* canceled?  Anyway,
        # this'll be a D-Bus data type so converted it to a vanilla Python
        # boolean.
        self._print('CANCELED:', canceled)
        self.canceled = bool(canceled)

    def _default(self, *args, **kws):
        self._print('SIGNAL:', args, kws)


class DBusDownloadManager:
    def __init__(self, callback=None):
        """
        :param callback: If given, a function that's called every so often in
            all the download threads - so it must be prepared to be called
            asynchronously.  You don't have to worry about thread safety though
            because of the GIL.
        :type callback: A function that takes three or four arguments:
            the full source url including the base, the absolute path of the
            destination, and the total number of bytes read so far from this
            url. The optional fourth argument is the total size of the source
            file, and is only present if the `sizes` argument was given (see
            below).
        """
        self._callback = callback
        self._iface = None
        self._reactor = None

    def get_files(self, downloads):
        """Download a bunch of files concurrently.

        The files named in `downloads` are downloaded in separate threads,
        concurrently using asynchronous I/O.  Occasionally, the callback is
        called to report on progress.  This function blocks until all files
        have been downloaded or an exception occurs.  In the latter case,
        the download directory will be cleared of the files that succeeded
        and the exception will be re-raised.

        This means that 1) the function blocks until all files are
        downloaded, but at least we do that concurrently; 2) this is an
        all-or-nothing function.  Either you get all the requested files or
        none of them.

        :param downloads: A list of 2-tuples where the first item is the url to
            download, and the second item is the destination file.
        :type downloads: List of 2-tuples.
        :param sizes: Optional sequence of sizes of the files being downloaded.
            If given, then the callback is called with a fourth argument,
            which is the size of the source file.  `sizes` is unused if there
            is no callback; this option is primarily for better progress
            feedback.
        :param sizes: Sequence of integers which must be the same length as the
            number of arguments given in `download`.
        :raises: FileNotFoundError if any download error occurred.  In this
            case, all download files are deleted.

        The API is a little funky for backward compatibility reasons.
        """
        bus = dbus.SystemBus()
        service = bus.get_object(DOWNLOADER_INTERFACE, '/')
        iface = dbus.Interface(service, MANAGER_INTERFACE)
        object_path = iface.createDownloadGroup(
            [(url, dst, '') for url, dst in downloads],
            '',           # No hashes yet.
            False,        # Don't allow GSM yet.
            # https://bugs.freedesktop.org/show_bug.cgi?id=55594
            dbus.Dictionary(signature='sv'),
            _headers())
        download = bus.get_object(OBJECT_NAME, object_path)
        self._iface = dbus.Interface(download, OBJECT_INTERFACE)
        self._reactor = DownloadReactor(bus, self._callback)
        self._reactor.schedule(self._iface.start)
        self._reactor.run()
        if self._reactor.error is not None:
            raise FileNotFoundError(self._reactor.error)
        if self._reactor.canceled:
            raise Canceled

    def cancel(self):
        """Cancel any current downloads."""
        if self._iface is not None:
            self._iface.cancel()


def get_files(downloads, callback=None):
    """See `DBusDownloadManager.get_files()`."""
    DBusDownloadManager(callback).get_files(downloads)
