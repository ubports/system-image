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
    'Record',
    ]


import os
import dbus
import logging

from collections import namedtuple
from contextlib import suppress
from io import StringIO
from pprint import pformat
from systemimage.config import config
from systemimage.reactor import Reactor
from systemimage.settings import Settings

# The systemimage.testing module will not be available on installed systems
# unless the system-image-dev binary package is installed, which is not usually
# the case.  Disable _print() debugging in that case.
def _print(*args, **kws):
    with suppress(ImportError):
        # We must import this here to avoid circular imports.
        from systemimage.testing.helpers import debug
        with debug(check_flag=True) as ddlog:
            ddlog(*args, **kws)


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


# A namedtuple is convenient here since we want to access items by their
# attribute names.  However, we also want to allow for the checksum to default
# to the empty string.  We do this by creating a prototypical record type and
# using _replace() to replace non-default values.  See the namedtuple
# documentation for details.
_Record = namedtuple('Record', 'url destination checksum')('', '', '')
_RecordType = type(_Record)

def Record(url, destination, checksum=''):
    return _Record._replace(
        url=url, destination=destination, checksum=checksum)


class DownloadReactor(Reactor):
    def __init__(self, bus, callback=None, pausable=False):
        super().__init__(bus)
        self._callback = callback
        self._pausable = pausable
        self.error = None
        self.canceled = False
        self.received = 0
        self.total = 0
        self.react_to('canceled')
        self.react_to('error')
        self.react_to('finished')
        self.react_to('paused')
        self.react_to('progress')
        self.react_to('resumed')
        self.react_to('started')

    def _do_started(self, signal, path, started):
        _print('STARTED:', started)

    def _do_finished(self, signal, path, local_paths):
        _print('FINISHED:', local_paths)
        self.quit()

    def _do_error(self, signal, path, error_message):
        _print('ERROR:', error_message)
        log.error(error_message)
        self.error = error_message
        self.quit()

    def _do_progress(self, signal, path, received, total):
        self.received = received
        self.total = total
        _print('PROGRESS:', received, total)
        if self._callback is not None:
            # Be defensive, so yes, use a bare except.  If an exception occurs
            # in the callback, log it, but continue onward.
            try:
                self._callback(received, total)
            except:
                log.exception('Exception in progress callback')

    def _do_canceled(self, signal, path, canceled):
        # Why would we get this signal if it *wasn't* canceled?  Anyway,
        # this'll be a D-Bus data type so converted it to a vanilla Python
        # boolean.
        _print('CANCELED:', canceled)
        self.canceled = bool(canceled)
        self.quit()

    def _do_paused(self, signal, path, paused):
        _print('PAUSE:', paused, self._pausable)
        if self._pausable and config.dbus_service is not None:
            # We could plumb through the `service` object from service.py (the
            # main entry point for system-image-dbus, but that's actually a
            # bit of a pain, so do the expedient thing and grab the interface
            # here.
            percentage = (int(self.received / self.total * 100.0)
                          if self.total > 0 else 0)
            config.dbus_service.UpdatePaused(percentage)

    def _do_resumed(self, signal, path, resumed):
        _print('RESUME:', resumed)
        # There currently is no UpdateResumed() signal.

    def _default(self, *args, **kws):
        _print('SIGNAL:', args, kws)


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

    def __repr__(self):
        return '<DBusDownloadManager at 0x{:x}>'.format(id(self))

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

        :params downloads: A list of `download records`, each of which may
            either be a 2-tuple where the first item is the url to download,
            and the second item is the destination file, or an instance of a
            `Record` namedtuple with attributes `url`, `destination`, and
            `checksum`.  The checksum may be the empty string.
        :type downloads: List of 2-tuples or `Record`s.
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
        # Convert the downloads items to download records.
        records = [item if isinstance(item, _RecordType) else Record(*item)
                   for item in downloads]
        destinations = set(record.destination for record in records)
        # Check for duplicate destinations, specifically for a local file path
        # coming from two different sources.  It's okay if there are duplicate
        # destination records in the download request, but each of those must
        # be specified by the same source url and have the same checksum.
        #
        # An easy quick check just asks if the set of destinations is smaller
        # than the total number of requested downloads.  It can't be larger.
        # If it *is* smaller, then there are some duplicates, however the
        # duplicates may be legitimate, so look at the details.
        #
        # Note though that we cannot pass duplicates destinations to udm,
        # so we have to filter out legitimate duplicates.  That's fine since
        # they really are pointing to the same file, and will end up in the
        # destination location.
        if len(destinations) < len(downloads):
            by_destination = dict()
            unique_downloads = set()
            for record in records:
                by_destination.setdefault(record.destination, set()).add(
                    record)
                unique_downloads.add(record)
            duplicates = []
            for dst, seen in by_destination.items():
                if len(seen) > 1:
                    # Tuples will look better in the pretty-printed output.
                    duplicates.append(
                        (dst, sorted(tuple(dup) for dup in seen)))
            if len(duplicates) > 0:
                raise DuplicateDestinationError(sorted(duplicates))
            # Uniquify the downloads.
            records = list(unique_downloads)
        bus = dbus.SystemBus()
        service = bus.get_object(DOWNLOADER_INTERFACE, '/')
        iface = dbus.Interface(service, MANAGER_INTERFACE)
        # Better logging of the requested downloads.
        fp = StringIO()
        print('[0x{:x}] Requesting group download:'.format(id(self)), file=fp)
        for record in records:
            if record.checksum == '':
                print('\t{} -> {}'.format(*record[:2]), file=fp)
            else:
                print('\t{} [{}] -> {}'.format(*record), file=fp)
        log.info('{}'.format(fp.getvalue()))
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
        DBusDownloadManager._set_gsm(self._iface, allow_gsm=allow_gsm)
        # Start the download.
        reactor = DownloadReactor(bus, self.callback, pausable)
        reactor.schedule(self._iface.start)
        log.info('[0x{:x}] Running group download reactor', id(self))
        reactor.run()
        # This download is complete so the object path is no longer
        # applicable.  Setting this to None will cause subsequent cancels to
        # be queued.
        self._iface = None
        log.info('[0x{:x}] Group download reactor done', id(self))
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
        # For sanity.
        for record in records:
            assert os.path.exists(record.destination), (
                'Missing destination: {}'.format(record))

    @staticmethod
    def _set_gsm(iface, *, allow_gsm):
        # This is a separate method for easier testing via mocks.
        iface.allowGSMDownload(allow_gsm)

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
