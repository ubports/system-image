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

"""Handle GPG signature verification."""

__all__ = [
    'Context',
    'SignatureError',
    ]


import os
import gnupg
import hashlib
import tarfile

from contextlib import ExitStack
from systemimage.config import config
from systemimage.helpers import calculate_signature, temporary_directory


class SignatureError(Exception):
    """Exception raised when some signature fails to validate.

    Note that this exception isn't raised by Context.verify(); that method
    always returns a boolean.  This exception is used by other functions to
    signal that a .asc file did not match.
    """
    def __init__(self, signature_path, data_path,
                 keyrings=None, blacklist=None):
        super().__init__()
        self.signature_path = signature_path
        self.data_path = data_path
        self.keyrings = ([] if keyrings is None else keyrings)
        self.blacklist = blacklist
        # We have to calculate the checksums now, because it's possible that
        # the files will be temporary/atomic files, deleted when a context
        # manager exits.  I.e. the files aren't guaranteed to exist after this
        # constructor runs.
        #
        # Also, md5 is fine; this is not a security critical context, we just
        # want to be able to quickly and easily compare the file on disk
        # against the file on the server.
        with open(self.signature_path, 'rb') as fp:
            self.signature_checksum =  calculate_signature(fp, hashlib.md5)
        with open(self.data_path, 'rb') as fp:
            self.data_checksum = calculate_signature(fp, hashlib.md5)
        self.keyring_checksums = []
        for path in self.keyrings:
            with open(path, 'rb') as fp:
                checksum = calculate_signature(fp, hashlib.md5)
                self.keyring_checksums.append(checksum)
        if self.blacklist is None:
            self.blacklist_checksum = None
        else:
            with open(self.blacklist, 'rb') as fp:
                self.blacklist_checksum = calculate_signature(fp, hashlib.md5)

    def __str__(self):
        if self.blacklist is None:
            checksum_str = 'no blacklist'
            path_str = ''
        else:
            checksum_str = self.blacklist_checksum
            path_str = self.blacklist
        return """
    sig path : {0.signature_checksum}
               {0.signature_path}
    data path: {0.data_checksum}
               {0.data_path}
    keyrings : {0.keyring_checksums}
               {1}
    blacklist: {2} {3}
""".format(self, list(self.keyrings), checksum_str, path_str)



class Context:
    def __init__(self, *keyrings, blacklist=None):
        """Create a GPG signature verification context.

        :param keyrings: The list of keyrings to use for validating the
            signature on data files.
        :type keyrings: Sequence of .tar.xz keyring files, which will be
            unpacked to retrieve the actual .gpg keyring file.
        :param blacklist: The blacklist keyring, from which fingerprints to
            explicitly disallow are retrieved.
        :type blacklist: A .tar.xz keyring file, which will be unpacked to
            retrieve the actual .gpg keyring file.
        """
        self.keyring_paths = keyrings
        self.blacklist_path = blacklist
        self._ctx = None
        self._stack = ExitStack()
        self._keyrings = []
        # The keyrings must be .tar.xz files, which need to be unpacked and
        # the keyring.gpg files inside them cached, using their actual name
        # (based on the .tar.xz file name).  If we don't already have a cache
        # of the .gpg file, do the unpackaging and use the contained .gpg file
        # as the keyring.  Note that this class does *not* validate the
        # .tar.xz files.  That must be done elsewhere.
        for path in keyrings:
            base, dot, tarxz = os.path.basename(path).partition('.')
            assert dot == '.' and tarxz == 'tar.xz', (
                'Expected a .tar.xz path, got: {}'.format(path))
            keyring_path = os.path.join(config.tempdir, base + '.gpg')
            if not os.path.exists(keyring_path):
                with tarfile.open(path, 'r:xz') as tf:
                    tf.extract('keyring.gpg', config.tempdir)
                    os.rename(
                        os.path.join(config.tempdir, 'keyring.gpg'),
                        os.path.join(config.tempdir, keyring_path))
            self._keyrings.append(keyring_path)
        # Since python-gnupg doesn't do this for us, verify that all the
        # keyrings and blacklist files exist.  Yes, this introduces a race
        # condition, but I don't see any good way to eliminate this given
        # python-gnupg's behavior.
        for path in self._keyrings:
            if not os.path.exists(path):            # pragma: no cover
                raise FileNotFoundError(path)
        if blacklist is not None:
            if not os.path.exists(blacklist):
                raise FileNotFoundError(blacklist)
            # Extract all the blacklisted fingerprints.
            with Context(blacklist) as ctx:
                self._blacklisted_fingerprints = ctx.fingerprints
        else:
            self._blacklisted_fingerprints = set()

    def __enter__(self):
        try:
            # Use a temporary directory for the $GNUPGHOME, but be sure to
            # arrange for the tempdir to be deleted no matter what.
            home = self._stack.enter_context(
                temporary_directory(prefix='si-gnupghome',
                                    dir=config.tempdir))
            self._ctx = gnupg.GPG(gnupghome=home, keyring=self._keyrings)
            self._stack.callback(setattr, self, '_ctx', None)
        except:              # pragma: no cover
            # Restore all context and re-raise the exception.
            self._stack.close()
            raise
        else:
            return self

    def __exit__(self, *exc_details):
        self._stack.close()
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
        """Verify a GPG signature.

        This verifies that the data file signature is valid, given the
        keyrings and blacklist specified in the constructor.  Specifically, we
        use GPG to extract the fingerprint in the signature path, and compare
        it against the fingerprints in the keyrings, subtracting any
        fingerprints in the blacklist.

        :param signature_path: The file system path to the detached signature
            file for the data file.
        :type signature_path: str
        :param data_path: The file system path to the data file.
        :type data_path: str
        :return: bool
        """
        # For testing on some systems that are connecting to test servers, GPG
        # verification isn't possible.  The s-i-cli supports a switch to
        # disable all GPG checks.
        if config.skip_gpg_verification:
            return True
        with open(signature_path, 'rb') as sig_fp:
            verified = self._ctx.verify_file(sig_fp, data_path)
        # If the file is properly signed, we'll be able to get back a set of
        # fingerprints that signed the file.   From here we do a set operation
        # to see if the fingerprints are in the list of keys from all the
        # loaded-up keyrings.  If so, the signature succeeds.
        return verified.fingerprint in (self.fingerprints -
                                        self._blacklisted_fingerprints)

    def validate(self, signature_path, data_path):
        """Like .verify() but raises a SignatureError when invalid.

        :param signature_path: The file system path to the detached signature
            file for the data file.
        :type signature_path: str
        :param data_path: The file system path to the data file.
        :type data_path: str
        :return: None
        :raises SignatureError: when the signature cannot be verified.  Note
            that the exception will contain extra information, namely the
            keyrings involved in the verification, as well as the blacklist
            file if there is one.
        """
        if not self.verify(signature_path, data_path):
            raise SignatureError(signature_path, data_path,
                                 self.keyring_paths, self.blacklist_path)
