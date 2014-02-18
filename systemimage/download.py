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

"""Download files."""

__all__ = [
    'Canceled',
    'DBusDownloadManager',
    'DuplicateDestinationError',
    ]


import os
import dbus
import logging
import tempfile

from contextlib import ExitStack
from io import StringIO
from pprint import pformat
from systemimage.config import config
from systemimage.helpers import safe_remove
from systemimage.reactor import Reactor


# Parameterized for testing purposes.
DOWNLOADER_INTERFACE = 'com.canonical.applications.Downloader'
MANAGER_INTERFACE = 'com.canonical.applications.DownloadManager'
OBJECT_NAME = 'com.canonical.applications.Downloader'
OBJECT_INTERFACE = 'com.canonical.applications.GroupDownload'
USER_AGENT = 'Ubuntu System Image Upgrade Client; Build {}'


log = logging.getLogger('systemimage')


def _headers():
    return {'User-Agent': USER_AGENT.format(config.build_number)}


class Canceled(Exception):
    """Raised when the download was canceled."""


class DuplicateDestinationError(Exception):
    """Raised when two files are downloaded to the same destination."""

    def __init__(self, duplicates):
        super().__init__()
        self.duplicates = duplicates

    def __str__(self):
        return '\n' + pformat(self.duplicates, indent=4, width=79)


class DownloadReactor(Reactor):
    def __init__(self, bus, callback=None, pausable=False):
        super().__init__(bus)
        self._callback = callback
        self._pausable = pausable
        self.error = None
        self.canceled = False
        self.react_to('canceled')
        self.react_to('error')
        self.react_to('finished')
        self.react_to('paused')
        self.react_to('progress')
        self.react_to('resumed')
        self.react_to('started')

    def _print(self, *args, **kws):
        ## from systemimage.testing.helpers import debug
        ## with debug() as ddlog:
        ##     ddlog(*args, **kws)
        pass

    def _do_started(self, signal, path, started):
        self._print('STARTED:', started)

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
        self.quit()

    def _do_paused(self, signal, path, paused):
        self._print('PAUSE:', paused, self._pausable)
        if self._pausable and config.dbus_service is not None:
            # We could plumb through the `service` object from service.py (the
            # main entry point for system-image-dbus, but that's actually a
            # bit of a pain, so do the expedient thing and grab the interface
            # here.
            config.dbus_service.UpdatePaused(0)

    def _do_resumed(self, signal, path, resumed):
        self._print('RESUME:', resumed)
        # There currently is no UpdateResumed() signal.

    def _default(self, *args, **kws):
        self._print('SIGNAL:', args, kws)


class DBusDownloadManager:
    def __init__(self, callback=None):
        """
        :param callback: If given, a function that is called every so often
            during downloading.
        :type callback: A function that takes two arguments, the number
            of bytes received so far, and the total amount of bytes to be
            downloaded.
        """
        self._iface = None
        self._queued_cancel = False
        self.callback = callback

    def get_files(self, downloads, *, pausable=False):
        """Download a bunch of files concurrently.

        Occasionally, the callback is called to report on progress.
        This function blocks until all files have been downloaded or an
        exception occurs.  In the latter case, the download directory
        will be cleared of the files that succeeded and the exception
        will be re-raised.

        This means that 1) the function blocks until all files are
        downloaded, but at least we do that concurrently; 2) this is an
        all-or-nothing function.  Either you get all the requested files
        or none of them.

        :param downloads: A list of 2-tuples where the first item is the url to
            download, and the second item is the destination file.
        :type downloads: List of 2-tuples.
        :param pausable: A flag specifying whether this download can be paused
            or not.  In general, data file downloads are pausable, but
            preliminary downloads are not.
        :type pausable: bool
        :raises: FileNotFoundError if any download error occurred.  In
            this case, all download files are deleted.
        :raises: DuplicateDestinationError if more than one source url is
            downloaded to the same destination file.
        """
        assert self._iface is None
        if self._queued_cancel:
            # A cancel is queued, so don't actually download anything.
            raise Canceled
        if len(downloads) == 0:
            # Nothing to download.  See LP: #1245597.
            return
        destinations = set(dst for url, dst in downloads)
        if len(destinations) < len(downloads):
            # Spend some extra effort to provide reasonable exception details.
            reverse = {}
            for url, dst in downloads:
                reverse.setdefault(dst, []).append(url)
            duplicates = []
            for dst, urls in reverse.items():
                if len(urls) > 1:
                    duplicates.append((dst, urls))
            raise DuplicateDestinationError(sorted(duplicates))
        bus = dbus.SystemBus()
        service = bus.get_object(DOWNLOADER_INTERFACE, '/')
        iface = dbus.Interface(service, MANAGER_INTERFACE)
        # Better logging of the requested downloads.
        fp = StringIO()
        print('Requesting group download:', file=fp)
        for url, dst in downloads:
            print('\t{} -> {}'.format(url, dst), file=fp)
        log.info('{}'.format(fp.getvalue()))
        # As a workaround for LP: #1277589, ask u-d-m to download the files to
        # .tmp files, and if they succeed, then atomically move them into
        # their real location.
        renames = []
        requests = []
        for url, dst in downloads:
            head, tail = os.path.split(dst)
            fd, path = tempfile.mkstemp(suffix='.tmp', prefix='', dir=head)
            os.close(fd)
            renames.append((path, dst))
            requests.append((url, path, ''))
        # mkstemp() creates the file system path, but if the files exist when
        # the group download is requested, ubuntu-download-manager will
        # complain and return an error.  So, delete all temporary files now so
        # udm has a clear path to download to.
        for path, dst in renames:
            os.remove(path)
        object_path = iface.createDownloadGroup(
            requests,     # The temporary requests.
            '',           # No hashes yet.
            False,        # Don't allow GSM yet.
            # https://bugs.freedesktop.org/show_bug.cgi?id=55594
            dbus.Dictionary(signature='sv'),
            _headers())
        download = bus.get_object(OBJECT_NAME, object_path)
        self._iface = dbus.Interface(download, OBJECT_INTERFACE)
        reactor = DownloadReactor(bus, self.callback, pausable)
        reactor.schedule(self._iface.start)
        log.info('Running group download reactor')
        reactor.run()
        # This download is complete so the object path is no longer
        # applicable.  Setting this to None will cause subsequent cancels to
        # be queued.
        self._iface = None
        log.info('Group download reactor done')
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
        # Now that everything succeeded, rename the temporary files.  Just to
        # be extra cautious, set up a context manager to safely remove all
        # temporary files in case of an error.  If there are no errors, then
        # there will be nothing to remove.
        with ExitStack() as resources:
            for tmp, dst in renames:
                resources.callback(safe_remove, tmp)
            for tmp, dst in renames:
                os.rename(tmp, dst)
            # We only get here if all the renames succeeded, so there will be
            # no temporary files to remove, so we can throw away the new
            # ExitStack, which holds all the removals.
            resources.pop_all()

    def cancel(self):
        """Cancel any current downloads."""
        if self._iface is None:
            # Since there's no download in progress right now, there's nothing
            # to cancel.  Setting this flag queues the cancel signal once the
            # reactor starts running again.  Yes, this is a bit weird, but if
            # we don't do it this way, the caller will immediately get a
            # Canceled exception, which isn't helpful because it's expecting
            # one when the next download begins.
            self._queued_cancel = True
        else:
            self._iface.cancel()

    def pause(self):
        """Pause the download, but only if one is in progress."""
        if self._iface is not None:
            self._iface.pause()

    def resume(self):
        """Resume the download, but only if one is in progress."""
        if self._iface is not None:
            self._iface.resume()
