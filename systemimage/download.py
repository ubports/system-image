# Copyright (C) 2013-2016 Canonical Ltd.
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
    'DuplicateDestinationError',
    'Record',
    'get_download_manager',
    ]


import os
import dbus
import logging

from collections import namedtuple
from io import StringIO
from pprint import pformat

try:
    import pycurl
except ImportError:                                 # pragma: no cover
    pycurl = None


log = logging.getLogger('systemimage')


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


class DownloadManagerBase:
    """Base class for all download managers."""

    def __init__(self):
        """
        :param callback: If given, a function that is called every so often
            during downloading.
        :type callback: A function that takes two arguments, the number
            of bytes received so far, and the total amount of bytes to be
            downloaded.
        """
        # This is a list of functions that are called every so often during
        # downloading.  Functions in this list take two arguments, the number
        # of bytes received so far, and the total amount of bytes to be
        # downloaded.
        self.callbacks = []
        self.total = 0
        self.received = 0
        self._queued_cancel = False

    def __repr__(self): # pragma: no cover
        return '<{} at 0x{:x}>'.format(self.__class__.__name__, id(self))

    def _get_download_records(self, downloads):
        """Convert the downloads items to download records."""
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
        # Note though that we cannot pass duplicates destinations to udm, so we
        # have to filter out legitimate duplicates.  That's fine since they
        # really are pointing to the same file, and will end up in the
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
        return records

    def _do_callback(self):
        # Be defensive, so yes, use a bare except.  If an exception occurs in
        # the callback, log it, but continue onward.
        for callback in self.callbacks:
            try:
                callback(self.received, self.total)
            except:
                log.exception('Exception in progress callback')

    def cancel(self):
        """Cancel any current downloads."""
        self._queued_cancel = True

    def pause(self):
        """Pause the download, but only if one is in progress."""
        pass                                        # pragma: no cover

    def resume(self):
        """Resume the download, but only if one is in progress."""
        pass                                        # pragma: no cover

    def _get_files(self, records, pausable, signal_started):
        raise NotImplementedError                   # pragma: no cover

    def get_files(self, downloads, *, pausable=False, signal_started=False):
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
        :param signal_started: A flag indicating whether the D-Bus
            DownloadStarted signal should be sent once the download has
            started.  Normally this is False, but it should be set to True
            when the update files are being downloaded (i.e. not for the
            metadata files).
        :type signal_started: bool
        :raises: FileNotFoundError if any download error occurred.  In
            this case, all download files are deleted.
        :raises: DuplicateDestinationError if more than one source url is
            downloaded to the same destination file.
        """
        if self._queued_cancel:
            # A cancel is queued, so don't actually download anything.
            raise Canceled
        if len(downloads) == 0:
            # Nothing to download.  See LP: #1245597.
            return
        records = self._get_download_records(downloads)
        # Better logging of the requested downloads.  However, we want the
        # entire block of multiline log output to appear under a single
        # timestamp.
        fp = StringIO()
        print('[0x{:x}] Requesting group download:'.format(id(self)), file=fp)
        for record in records:
            if record.checksum == '':
                print('\t{} -> {}'.format(*record[:2]), file=fp)
            else:
                print('\t{} [{}] -> {}'.format(*record), file=fp)
        log.info('{}'.format(fp.getvalue()))
        self._get_files(records, pausable, signal_started)

    @staticmethod
    def allow_gsm():
        """Allow downloads on GSM.

        This is a temporary override for the `auto_download` setting.
        If a download was attempted on wifi-only and not started because
        the device is on GSM, calling this issues a temporary override
        to allow downloads while on GSM, for download managers that
        support this (currently only UDM).
        """
        pass                                        # pragma: no cover


def get_download_manager(*args):
    # We have to avoid circular imports since both download managers import
    # various things from this module.
    from systemimage.curl import CurlDownloadManager
    from systemimage.udm import DOWNLOADER_INTERFACE, UDMDownloadManager
    # Detect if we have ubuntu-download-manager.
    #
    # Use PyCURL based downloader if no udm is found, or if the environment
    # variable is set.  However, if we're told to use PyCURL and it's
    # unavailable, throw an exception.
    cls = None
    use_pycurl = os.environ.get('SYSTEMIMAGE_PYCURL')
    if use_pycurl is None:
        # Auto-detect.  For backward compatibility, use udm if it's available,
        # otherwise use PyCURL.
        try:
            bus = dbus.SystemBus()
            bus.get_object(DOWNLOADER_INTERFACE, '/')
            udm_available = True
        except dbus.exceptions.DBusException:
            udm_available = False
        if udm_available:
            cls = UDMDownloadManager
        elif pycurl is None:
            raise ImportError('No module named {}'.format('pycurl'))
        else:
            cls = CurlDownloadManager
    else:
        cls = (CurlDownloadManager
               if use_pycurl.lower() in ('1', 'yes', 'true')
               else UDMDownloadManager)
    return cls(*args)
