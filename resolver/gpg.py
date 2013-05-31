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
    ]


import gnupg
import shutil
import tempfile

from contextlib import ExitStack


class Context:
    def __init__(self, *keyrings, blacklist=None):
        self._ctx = None
        self._withstack = ExitStack()
        self._keyrings = keyrings
        if blacklist is not None:
            # Extract all the blacklisted fingerprints.
            with Context(blacklist) as ctx:
                self._blacklisted_fingerprints = ctx.fingerprints
        else:
            self._blacklisted_fingerprints = set()

    def __enter__(self):
        try:
            # Use a temporary directory for the $GNUPGHOME, but be sure to
            # arrange for the tempdir to be deleted no matter what.
            home = tempfile.mkdtemp(prefix='.otaupdate')
            self._withstack.callback(shutil.rmtree, home)
            options = []
            for keyring in self._keyrings:
                options.extend(('--keyring', keyring))
            self._ctx = gnupg.GPG(gnupghome=home, options=options)
            self._withstack.callback(setattr, self, '_ctx', None)
        except:
            # Restore all context and re-raise the exception.
            self._withstack.close()
            raise
        else:
            return self

    def __exit__(self, *exc_details):
        self._withstack.close()
        # Don't swallow exceptions.
        return False

    @property
    def keys(self):
        return self._ctx.list_keys()

    @property
    def fingerprints(self):
        return set(info['fingerprint'] for info in self._ctx.list_keys())

    @property
    def key_ids(self):
        return set(info['keyid'] for info in self._ctx.list_keys())

    def verify(self, signature_path, data_path):
        with open(signature_path, 'rb') as sig_fp:
            verified = self._ctx.verify_file(sig_fp, data_path)
        # If the file is properly signed, we'll be able to get back a set of
        # fingerprints that signed the file.   From here we do a set operation
        # to see if the fingerprints are in the list of keys from all the
        # loaded-up keyrings.  If so, the signature succeeds.
        return verified.fingerprint in (self.fingerprints -
                                        self._blacklisted_fingerprints)
