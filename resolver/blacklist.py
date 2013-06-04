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

"""Downloading, verifying, and unpacking the blacklist keyring."""


__all__ = [
    'get_blacklist',
    ]


import os
import json
import shutil
import tarfile

from contextlib import ExitStack
from datetime import datetime, timezone
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import Context
from urllib.parse import urljoin


def get_blacklist():
    """Download, verify, and unpack the blacklist keyring.

    First, the blacklist.tar.xz and blacklist.tar.xz.asc files are
    downloaded.  Then the signature is checked against the SYSTEM IMAGE
    MASTER key.  If this fails, a FileNotFoundError is raised and the
    files are deleted.

    If this succeeds, the tar.xz is unpacked, which should produce a
    .gpg file containing the keyring, and a .json file describing the
    keyring.  We load up the json file and verify that the keyring type
    is 'blacklist' and that the 'expiry' key, which names a UNIX epoch
    timestamp, has not yet expired.  Also, the 'model' key is checked - it is
    optional in the json file, and when it's missing, it means it applies to
    any model.

    If any of these condition occurred, a FileNotFoundError is raised
    and the files are deleted.

    Assuming everything checks out, the path to the blacklist.gpg file is
    returned.

    :raises FileNotFoundError: when any of the verifying attributes of the
        downloaded blacklist fails.
    """
    tarxz_src = urljoin(config.service.https_base, '/gpg/blacklist.tar.xz')
    ascxz_src = tarxz_src + '.asc'
    tarxz_dst = os.path.join(config.system.tempdir, 'blacklist.tar.xz')
    ascxz_dst = tarxz_dst + '.asc'
    with ExitStack() as stack:
        # Let FileNotFoundError percolate up.
        get_files([(tarxz_src, tarxz_dst),
                   (ascxz_src, ascxz_dst)])
        stack.callback(os.remove, tarxz_dst)
        stack.callback(os.remove, ascxz_dst)
        # There can't be a blacklist for this signature, since 1) it's the
        # blacklist file! and 2) the system image master never expires.
        with Context(config.gpg.image_master) as ctx:
            if not ctx.verify(ascxz_dst, tarxz_dst):
                raise FileNotFoundError('bad signature')
        # The signature is good, so now unpack the tarball, load the json file
        # and verify its contents.
        with tarfile.open(tarxz_dst, 'r:xz') as tf:
            tf.extractall(config.system.tempdir)
        keyring_gpg = os.path.join(config.system.tempdir, 'keyring.gpg')
        stack.callback(os.remove, keyring_gpg)
        stack.callback(os.remove,
                       os.path.join(config.system.tempdir, 'keyring.json'))
        json_path = os.path.join(config.system.tempdir, 'keyring.json')
        with open(json_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        # Check the mandatory keys first.
        if data.get('type') != 'blacklist':
            raise FileNotFoundError('bad keyring type')
        # Check the optional keys next.
        if data.get('model') not in (config.system.device, None):
            raise FileNotFoundError('non-matching device')
        expiry = data.get('expiry')
        if expiry is not None:
            # Get our current timestamp in UTC.
            timestamp = datetime.now(tz=timezone.utc).timestamp()
            if expiry < timestamp:
                # We've passed the expiration date for this keyring.
                raise FileNotFoundError('expired timestamp')
        # Everything is good, so copy the keyring.gpg file to blacklist.gpg.
        # The original keyring.gpg file will be deleted when the context
        # manager exits.
        shutil.copy(keyring_gpg, config.gpg.blacklist)
