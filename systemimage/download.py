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
    'Downloader',
    'get_files',
    ]


import socket
import logging

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from ssl import CertificateError
from systemimage.config import config
from systemimage.helpers import atomic, safe_remove
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Parameterized for testing purposes.
CHUNK_SIZE = 4096
USER_AGENT = 'Ubuntu System Image Upgrade Client; Build {}'
log = logging.getLogger('systemimage')


class Downloader:
    def __init__(self, url, timeout=None):
        self.url = url
        # This is the hidden default for urlopen().
        self.timeout = (socket.getdefaulttimeout()
                        if timeout is None else timeout)
        self._stack = ExitStack()

    def __enter__(self):
        try:
            # Set a custom User-Agent which includes the system build number.
            headers = {'User-Agent': USER_AGENT.format(config.build_number)}
            request = Request(self.url, headers=headers)
            # Make sure to fallback to the system certificate store.
            return self._stack.enter_context(
                urlopen(request, timeout=self.timeout, cadefault=True))
        except:
            self._stack.close()
            raise

    def __exit__(self, *exc_details):
        self._stack.close()
        # Don't swallow exceptions.
        return False


def _get_one_file(args):
    timeout, url, dst, size, callback = args
    bytes_read = 0
    log.info('downloading %s -> %s', url, dst)
    with ExitStack() as stack:
        response = stack.enter_context(Downloader(url, timeout))
        out = stack.enter_context(atomic(dst, encoding=None))
        while True:
            chunk = response.read(CHUNK_SIZE)
            if len(chunk) == 0:
                break
            bytes_read += len(chunk)
            out.write(chunk)
            if callback is not None:
                args = [url, dst, bytes_read]
                if size is not None:
                    args.append(size)
                callback(*args)


def get_files(downloads, callback=None, sizes=None):
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
    :param callback: If given, a function that's called every so often in all
        the download threads - so it must be prepared to be called
        asynchronously.  You don't have to worry about thread safety though
        because of the GIL.
    :type callback: A function that takes three (optionally four) arguments:
        the full source url including the base, the absolute path of the
        destination, and the total number of bytes read so far from this url.
        The optional fourth argument is the total size of the source file, and
        is only present if the `sizes` argument was given (see below).
    :param sizes: Optional sequence of sizes of the files being downloaded.
        If given, then the callback is called with a fourth argument, which is
        the size of the source file.  `sizes` is unused if there is no
        callback; this option is primarily for better progress feedback.
    :param sizes: Sequence of integers which must be the same length as the
        number of arguments given in `download`.
    :raises: FileNotFoundError if any download error occurred.  In this case,
        all download files are deleted.

    The API is a little funky for backward compatibility reasons.
    """
    # Sanity check arguments.
    if sizes is not None:
        assert len(sizes) == len(downloads), (
            'sizes argument is different length than downloads')
    else:
        sizes = [None] * len(downloads)
    # Download all the files, blocking until we get them all.
    if config.service.timeout <= timedelta():
        # E.g. -1s or 0s or 0d etc.
        timeout = None
    else:
        timeout = config.service.timeout.total_seconds()
    # Repack the downloads so that the _get_one_file() function will be called
    # with the proper set of arguments.
    args = [(timeout, url, dst, size, callback)
            for (url, dst), size
            in zip(downloads, sizes)]
    with ExitStack() as stack:
        # Arrange for all the downloaded files to be remove when the stack
        # exits due to an exception.  It's okay if some of the files don't
        # exist.  If everything gets downloaded just fine, we'll clear the
        # stack *without* calling the close() method so that the files won't
        # be deleted.  This is why we run the ThreadPoolExecutor in its own
        # context manager.
        for url, path in downloads:
            stack.callback(safe_remove, path)
        with ThreadPoolExecutor(max_workers=config.service.threads) as tpe:
            # All we need to do is iterate over the returned generator in
            # order to complete all the requests.  There's really nothing to
            # return.  Either all the files got downloaded, or they didn't.
            #
            # BAW 2013-05-02: There is a subtle bug lurking here, caused by
            # the fact that the individual files are moved atomically, but
            # get_files() makes global atomic promises.  Let's say you're
            # downloading files A and B, but file A already exists.  File A
            # downloads just fine and gets moved into place.  The download of
            # file B fails though so it never gets moved into place, however
            # the except code below will proceed to remove the new A without
            # restoring the old A.
            #
            # In practice I think this won't hurt us because we shouldn't be
            # overwriting any existing files that we care about anyway.
            # Something to be aware of though.  The easiest fix is probably to
            # stash any existing files away and restore them if the download
            # fails, rather than os.remove()'ing them.
            try:
                list(tpe.map(_get_one_file, args))
            except (HTTPError, URLError, CertificateError):
                raise FileNotFoundError
            # Check all the signed files.  First, grab the blacklists file if
            # there is one available.
        # Everything's fine so do *not* delete the downloaded files.
        stack.pop_all()
