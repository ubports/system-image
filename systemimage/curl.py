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

"""Download files via PyCURL."""

__all__ = [
    'CurlDownloadManager',
    ]


import pycurl
import hashlib
import logging

from contextlib import ExitStack
from gi.repository import GLib
from systemimage.config import config
from systemimage.download import Canceled, DownloadManagerBase

log = logging.getLogger('systemimage')


# Some cURL defaults.  XXX pull these out of the configuration file.
CONNECTION_TIMEOUT = 120    # seconds
LOW_SPEED_LIMIT = 10
LOW_SPEED_TIME = 120        # seconds
MAX_REDIRECTS = 5
MAX_TOTAL_CONNECTIONS = 4
SELECT_TIMEOUT = 0.05       # 20fps


def _curl_debug(debug_type, debug_msg):             # pragma: no cover
    from systemimage.testing.helpers import debug
    with debug(end='') as ddlog:
        ddlog('PYCURL:', debug_type, debug_msg)


def make_testable(c):
    # The test suite needs to make the PyCURL object accept the testing
    # server's self signed certificate.  It will mock this function.
    pass                                            # pragma: no cover


class SingleDownload:
    def __init__(self, record):
        self.url, self.destination, self.expected_checksum = record
        self._checksum = None
        self._fp = None
        self._resources = ExitStack()

    def make_handle(self, *, HEAD):
        # If we're doing GET, record some more information.
        if not HEAD:
            self._checksum = hashlib.sha256()
        # Create the basic PyCURL object.
        c = pycurl.Curl()
        # Set the common options.
        c.setopt(pycurl.URL, self.url)
        c.setopt(pycurl.USERAGENT, config.user_agent)
        # If we're doing a HEAD, then we don't want the body of the
        # file.  Otherwise, set things up to write the body data to the
        # destination file.
        if HEAD:
            c.setopt(pycurl.NOBODY, 1)
        else:
            c.setopt(pycurl.WRITEDATA, self)
            self._fp = self._resources.enter_context(
                open(self.destination, 'wb'))
        # Set some limits.  XXX Pull these out of the configuration files.
        c.setopt(pycurl.FOLLOWLOCATION, 1)
        c.setopt(pycurl.MAXREDIRS, MAX_REDIRECTS)
        c.setopt(pycurl.CONNECTTIMEOUT, CONNECTION_TIMEOUT)
        # If the average transfer speed is below 10 bytes per second for 2
        # minutes, libcurl will consider the connection too slow and abort.
        ## c.setopt(pycurl.LOW_SPEED_LIMIT, LOW_SPEED_LIMIT)
        ## c.setopt(pycurl.LOW_SPEED_TIME, LOW_SPEED_TIME)
        # Fail on error codes >= 400.
        c.setopt(pycurl.FAILONERROR, 1)
        # Switch off the libcurl progress meters.  The multi that uses
        # this handle will set the transfer info function.
        c.setopt(pycurl.NOPROGRESS, 1)
        # ssl: no need to set SSL_VERIFYPEER, SSL_VERIFYHOST, CAINFO
        #      they all use sensible defaults
        #
        # Enable debugging.
        self._make_debuggable(c)
        # For the test suite.
        make_testable(c)
        return c

    def _make_debuggable(self, c):
        """Add some additional debugging options."""
        ## c.setopt(pycurl.VERBOSE, 1)
        ## c.setopt(pycurl.DEBUGFUNCTION, _curl_debug)
        pass

    def write(self, data):
        """Update the checksum and write the data out to the file."""
        self._checksum.update(data)
        self._fp.write(data)
        # Returning None implies that all bytes were written
        # successfully, so it's better to be explicit.
        return None

    def close(self):
        self._resources.close()

    @property
    def checksum(self):
        # If no checksum was expected, pretend none was gotten.  This
        # makes the verification step below a wee bit simpler.
        if self.expected_checksum == '':
            return ''
        return self._checksum.hexdigest()


class CurlDownloadManager(DownloadManagerBase):
    """The PyCURL based download manager."""

    def __init__(self, callback=None):
        super().__init__()
        if callback is not None:
            self.callbacks.append(callback)
        self._pausables = []
        self._paused = False

    def _get_files(self, records, pausable, signal_started):
        # Start by doing a HEAD on all the URLs so that we can get the total
        # target download size in bytes, at least as best as is possible.
        with ExitStack() as resources:
            handles = []
            multi = pycurl.CurlMulti()
            multi.setopt(
                pycurl.M_MAX_TOTAL_CONNECTIONS, MAX_TOTAL_CONNECTIONS)
            for record in records:
                download = SingleDownload(record)
                resources.callback(download.close)
                handle = download.make_handle(HEAD=True)
                handles.append(handle)
                multi.add_handle(handle)
                # .add_handle() does not bump the reference count, so we
                # need to keep the PyCURL object alive for the duration
                # of this download.
                resources.callback(multi.remove_handle, handle)
            self._perform(multi, handles)
            self.total = sum(
                handle.getinfo(pycurl.CONTENT_LENGTH_DOWNLOAD)
                for handle in handles)
        # Now do a GET on all the URLs.  This will write the data to the
        # destination file and collect the checksums.
        if signal_started and config.dbus_service is not None:
            config.dbus_service.DownloadStarted()
        with ExitStack() as resources:
            resources.callback(setattr, self, '_handles', None)
            downloads = []
            multi = pycurl.CurlMulti()
            multi.setopt(
                pycurl.M_MAX_TOTAL_CONNECTIONS, MAX_TOTAL_CONNECTIONS)
            for record in records:
                download = SingleDownload(record)
                downloads.append(download)
                resources.callback(download.close)
                handle = download.make_handle(HEAD=False)
                self._pausables.append(handle)
                multi.add_handle(handle)
                # .add_handle() does not bump the reference count, so we
                # need to keep the PyCURL object alive for the duration
                # of this download.
                resources.callback(multi.remove_handle, handle)
            self._perform(multi, self._pausables)
            # Verify internally calculated checksums.  The API requires
            # a FileNotFoundError to be raised when they don't match.
            # Since it doesn't matter which one fails, log them all and
            # raise the first one.
            first_mismatch = None
            for download in downloads:
                if download.checksum != download.expected_checksum:
                    log.error('Checksum mismatch.  got:{} != exp:{}: {}',
                              download.checksum, download.expected_checksum,
                              download.destination)
                    if first_mismatch is None:
                        first_mismatch = download
            if first_mismatch is not None:
                # For backward compatibility with ubuntu-download_manager.
                raise FileNotFoundError('HASH ERROR: {}'.format(
                    first_mismatch.destination))
        self._pausables = []

    def _do_once(self, multi, handles):
        status, active_count = multi.perform()
        if status == pycurl.E_CALL_MULTI_PERFORM:
            # Call .perform() again before calling select.
            return True
        elif status != pycurl.E_OK:
            # An error occurred in the multi, so be done with the
            # whole thing.  We can't get a description string out of
            # PyCURL though.  Just raise one of the urls.
            log.error('CurlMulti() error: {}', status)
            raise FileNotFoundError(handles[0].getinfo(pycurl.EFFECTIVE_URL))
        # The multi is okay, but it's possible there are errors pending on
        # the individual downloads; check those now.
        queued_count, ok_list, error_list = multi.info_read()
        if len(error_list) > 0:
            # It helps to have at least one URL in the FileNotFoundError.
            first_url = None
            log.error('Curl() errors encountered:')
            for c, code, message in error_list:
                url = c.getinfo(pycurl.EFFECTIVE_URL)
                if first_url is None:
                    first_url = url
                log.error('    {} ({}): {}', message, code, url)
            raise FileNotFoundError('{}: {}'.format(message, first_url))
        # For compatibility with .io_add_watch(), we return False if we want
        # to stop the callbacks, and True if we want to call back here again.
        return active_count > 0

    def _perform(self, multi, handles):
        # While we're performing the cURL downloads, we need to periodically
        # process D-Bus events, otherwise we won't be able to cancel downloads
        # or handle other interruptive events.  To do this, we grab the GLib
        # main loop context and then ask it to do an iteration over its events
        # once in a while.  It turns out that even if we're not running a D-Bus
        # main loop (i.e. during the in-process tests) periodically dispatching
        # into GLib doesn't hurt, so just do it unconditionally.
        self.received = 0
        context = GLib.main_context_default()
        while True:
            # Do the progress callback, but only if the current received size
            # is different than the last one.  Don't worry about in which
            # direction it's different.
            received = int(
                sum(c.getinfo(pycurl.SIZE_DOWNLOAD) for c in handles))
            if received != self.received:
                self._do_callback()
                self.received = received
            if not self._do_once(multi, handles):
                break
            multi.select(SELECT_TIMEOUT)
            # Let D-Bus events get dispatched, but only block if downloads are
            # paused.
            while context.iteration(may_block=self._paused):
                pass
            if self._queued_cancel:
                raise Canceled
        # One last callback, unconditionally.
        self.received = int(
            sum(c.getinfo(pycurl.SIZE_DOWNLOAD) for c in handles))
        self._do_callback()

    def pause(self):
        for c in self._pausables:
            c.pause(pycurl.PAUSE_ALL)
        self._paused = True
        # 2014-10-20 BAW: We could plumb through the `service` object from
        # service.py (the main entry point for system-image-dbus, but that's
        # actually a bit of a pain, so do the expedient thing and grab the
        # interface here.
        percentage = (int(self.received / self.total * 100.0)
                      if self.total > 0 else 0)
        config.dbus_service.UpdatePaused(percentage)

    def resume(self):
        self._paused = False
        for c in self._pausables:
            c.pause(pycurl.PAUSE_CONT)
