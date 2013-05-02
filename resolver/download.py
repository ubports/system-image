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

# BAW 2013-04-25 TODO:
#
# - explicit certificate assertions for https required connections
# - explicit http checks for downloads that don't need https
# - checksum verification
# - connection pooling
#
# I'm sure there's more.

__all__ = [
    'Downloader',
    'get_files',
    ]


import os

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial
from urllib.parse import urljoin
from urllib.request import urlopen
from resolver.config import config
from resolver.helpers import atomic


# Parameterized for testing purposes.
CHUNK_SIZE = 4096


class Downloader:
    def __init__(self, url):
        self.url = url
        self._withstack = ExitStack()

    def __enter__(self):
        response = urlopen(self.url)
        self._withstack.push(response)
        # Allow the response object to be .read() from directly in the body of
        # the context manager.  This may have to change.
        return response

    def __exit__(self, *exc_details):
        self._withstack.pop_all().close()
        # Don't swallow exceptions.
        return False


def _get_one_file(download, callback=None):
    url, dst = download
    bytes_read = 0
    with Downloader(url) as response, atomic(dst, encoding=None) as out:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if len(chunk) == 0:
                break
            bytes_read += len(chunk)
            out.write(chunk)
            if callback is not None:
                callback(url, dst, bytes_read)
    # Return the actual absolute path to the destination file so it can be
    # cleaned up if any other download fails.
    return dst


def get_files(downloads, callback=None):
    """Download a bunch of files concurrently.

    The files named in `downloads` are downloaded in separate threads,
    concurrently using asynchronous I/O.  Occasionally, the callback is called
    to report on progress.  This function blocks until all files have been
    downloaded or an exception occurs.  In the latter case, the cache will be
    cleared of the files that succeeded and the exception will be re-raised.

    This means that 1) the function blocks until all files are downloaded, but
    at least we do that concurrently; 2) this is an all-or-nothing function.
    Either you get all the requested files or none of them.

    :param downloads: A list of 2-tuples where the first item is the full
        source url path relative to the configuration file's `[service]base`
        url, and the second item is the destination file relative to the
        configuration file's `[cache]directory` path.
    :param callback: If given, a function that's called every so often in all
        the download threads - so it must be prepared to be called
        asynchronously.  You don't have to worry about thread safety though
        because of the GIL.
    :type callback: A function that takes three arguments: the full source url
        including the base, the absolute path of the destination, and the
        total number of bytes read so far from this url.
    :raises: `urllib.error.URLError` and `TimeOutError`
    """
    function = partial(_get_one_file, callback=callback)
    if config.service.timeout <= timedelta():
        # E.g. -1s or 0s or 0d etc.
        timeout = None
    else:
        timeout = config.service.timeout.total_seconds()
    # Go through the list of download urls and destination files and make them
    # absolute.  This way, we have them here and the map function doesn't have
    # to do anything smart.
    cleanup_files = []
    abspath_downloads = []
    for url_source, dst_file in downloads:
        url = urljoin(config.service.base, url_source)
        dst = os.path.join(config.cache.directory, dst_file)
        cleanup_files.append(dst)
        abspath_downloads.append((url, dst))
    try:
        with ThreadPoolExecutor(max_workers=config.service.threads) as tpe:
            # All we need to do is iterate over the returned generator in
            # order to complete all the requests.  There's really nothing to
            # return.  Either all the files got downloaded, or they didn't.
            list(tpe.map(function, abspath_downloads, timeout=timeout))
    except:
        # If any exceptions occur, we want to delete files that downloaded
        # successfully.  The ones that failed will already have been deleted.
        # BAW 2013-05-01: I wish I could figure out how to do this with a
        # context manager.
        for dst in cleanup_files:
            try:
                os.remove(dst)
            except OSError:
                pass
        raise
