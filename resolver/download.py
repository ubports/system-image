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

# BAW 2013-04-25: This is a very simple and minimal implementation, sufficient
# for a prototype.  For a production system we will at least want to make the
# following changes:
#
# - asynchronous i/o so we won't block waiting for the files to download
# - explicit certificate assertions for https required connections
# - explicit http checks for downloads that don't need https
# - checksum verification
# - connection pooling
#
# I'm sure there's more.
#
# urllib3 or some other third party library, along with tulip/gevent or other
# such system (twisted seems like overkill?) will probably come in handy
# here.  For now, we'll stick to the stdlib.


__all__ = [
    'Downloader',
    ]


from contextlib import ExitStack
from urllib.request import urlopen


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
