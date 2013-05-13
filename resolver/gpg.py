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

"""Handle GPG signature verification."""

__all__ = [
    'Context',
    'get_pubkey',
    ]


import os
import gnupg
import shutil
import tempfile

from contextlib import ExitStack
from functools import partial
from resolver.config import config
from resolver.download import Downloader
from resolver.helpers import atomic
from urllib.parse import urljoin


class Context:
    def __init__(self, pubkey_path, home=None):
        self.pubkey_path = pubkey_path
        self.home = home
        self._ctx = None
        self._withstack = ExitStack()
        self.import_result = None

    def __enter__(self):
        try:
            # If any errors occur, pop the exit stack to clean up any
            # temporary directories.
            if self.home is None:
                # No $GNUPGHOME specified, so use a temporary directory, but
                # be sure to arrange for the tempdir to be deleted no matter
                # what.
                home = tempfile.mkdtemp(prefix='.otaupdate')
                self._withstack.callback(partial(shutil.rmtree, home))
            else:
                home = self.home
            self._ctx = gnupg.GPG(gnupghome=home)
            self._withstack.callback(partial(setattr, self, '_ctx', None))
            with open(self.pubkey_path, 'rb') as fp:
                self.import_result = self._ctx.import_keys(fp.read())
        except:
            # Restore all context and re-raise the exception.
            self._withstack.pop_all().close()
            raise
        else:
            return self

    def __exit__(self, *exc_details):
        self._withstack.pop_all().close()
        # Don't swallow exceptions.
        return False

    def verify(self, signature_path, data_path):
        with open(signature_path, 'rb') as sig_fp:
            verified = self._ctx.verify_file(sig_fp, data_path)
        # The fingerprints in the validly signed file must match the
        # fingerprint in the pubkey.
        return verified.fingerprint == self.import_result.fingerprints[0]


def get_pubkey():
    """Make sure we have the pubkey, downloading it if necessary."""
    # BAW 2013-04-26: Ultimately, it's likely that the pubkey will be
    # placed on the file system at install time.
    url = urljoin(config.service.http_base, 'phablet.pubkey.asc')
    pubkey_path = os.path.join(config.system.tempdir, 'phablet.pubkey.asc')
    # Don't use get_files() here because get_files() calls get_pubkey(), so
    # you'd end up with infinite recursion.  Use the lower level API.
    with Downloader(url) as response:
        pubkey = response.read().decode('utf-8')
    # Now, put the pubkey in the temporary directory The pubkey is ASCII
    # armored so the default utf-8 is good enough.
    with atomic(pubkey_path) as fp:
        fp.write(pubkey)
    return pubkey_path
