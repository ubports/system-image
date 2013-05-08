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

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from functools import partial
from resolver.config import config
from resolver.helpers import atomic
from urllib.error import HTTPError
from urllib.request import urlopen


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


def get_files(downloads, callback=None, cache=None):
    """Download a bunch of files concurrently.

    The files named in `downloads` are downloaded in separate threads,
    concurrently using asynchronous I/O.  Occasionally, the callback is called
    to report on progress.  This function blocks until all files have been
    downloaded or an exception occurs.  In the latter case, the cache will be
    cleared of the files that succeeded and the exception will be re-raised.

    This means that 1) the function blocks until all files are downloaded, but
    at least we do that concurrently; 2) this is an all-or-nothing function.
    Either you get all the requested files or none of them.

    After all the files are successful downloaded, any file with both a .asc
    signature file and a matching non-.asc file are checked against the
    pubkey.  If any signatures fail, then a FileNotFoundError is raised and
    all files are deleted.

    :param downloads: A list of 2-tuples where the first item is the url to
        download, and the second item is the destination file.
    :param callback: If given, a function that's called every so often in all
        the download threads - so it must be prepared to be called
        asynchronously.  You don't have to worry about thread safety though
        because of the GIL.
    :type callback: A function that takes three arguments: the full source url
        including the base, the absolute path of the destination, and the
        total number of bytes read so far from this url.
    :raises: FileNotFoundError if any download error occurred.  In this case,
        all download files are deleted.
    """
    function = partial(_get_one_file, callback=callback)
    if config.service.timeout <= timedelta():
        # E.g. -1s or 0s or 0d etc.
        timeout = None
    else:
        timeout = config.service.timeout.total_seconds()
    try:
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
                list(tpe.map(function, downloads, timeout=timeout))
            except HTTPError:
                raise FileNotFoundError
            # Avoid circular references.
            from resolver.gpg import Context, get_pubkey
            # Check all the signed files.
            local_files = set(path for url, path in downloads)
            sig_files = set(path for path in local_files
                            if path.endswith('.asc'))
            check_sigs = []
            for sig in sig_files:
                data_file = os.path.splitext(sig)[0]
                if data_file in local_files:
                    check_sigs.append((sig, data_file))
            pubkey_path = get_pubkey(cache)
            with Context(pubkey_path) as ctx:
                for sig_file, data_file in check_sigs:
                    if not ctx.verify(sig_file, data_file):
                        raise FileNotFoundError
    except:
        # If any exceptions occur, we want to delete files that downloaded
        # successfully.  The ones that failed will already have been deleted.
        # BAW 2013-05-01: I wish I could figure out how to do this with a
        # context manager.
        for url, dst in downloads:
            try:
                os.remove(dst)
            except OSError:
                pass
        raise
