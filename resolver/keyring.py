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

"""Downloading, verifying, and unpacking a keyring."""


__all__ = [
    'KeyringError',
    'get_keyring',
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


# Maps allowed types to a 3-tuple of the target url basename (relative to the
# base https server) the key in the config.gpg section naming the local
# keyring file name, and the name of the existing keyring which can sign the
# downloaded keyring.
_keyring_mappings = {
    'master': (None, 'archive_master', None),
    'system-image': ('/gpg/system-image', 'image_master', 'archive_master'),
    'signing': ('/gpg/signing', 'image_signing', 'image_master'),
    'device':
        ('/gpg/{channel}/{device}/device', 'vendor_signing', 'image_signing'),
    'blacklist': ('/gpg/blacklist', 'blacklist', 'image_master'),
    }


class KeyringError(Exception):
    """An error occurred getting the keyring."""

    def __init__(self, message):
        self.message = message


def get_keyring(keyring_type):
    """Download, verify, and unpack a keyring.

    First, the <type>.tar.xz and <type>.tar.xz.asc files are downloaded.
    Then the signature is checked against the keys in the appropriate
    signing keyrings.  If this fails, a KeyringError is raised and the
    files are deleted.

    If this succeeds, the tar.xz is unpacked, which should produce a
    keyring.gpg file containing the keyring, and a keyring.json file
    describing the keyring.  We load up the json file and verify that
    the keyring 'type' matches the type parameter and that the 'expiry'
    key, which names a UTC UNIX epoch timestamp, has not yet expired.
    Also, the 'model' key is checked - it is optional in the json file,
    and when it's missing, it means it applies to any model.

    If any of these condition occurred, a KeyringError is raised and the
    files are deleted.

    Assuming everything checks out, the keyring is saved in the
    appropriate file name and the file name is returned.

    :param keyring_type: The type of keyring file to download.  This can be
        one of 'master', 'system-image', 'signing', 'device', or 'blacklist'.
    :return: The path to the downloaded and verified keyring file.
    :raises Keyringerror: when any of the verifying attributes of the
        downloaded keyring fails.
    """
    # Calculate the urls to the .tar.xz and .asc files.
    template, config_keyring, config_signing = _keyring_mappings[keyring_type]
    url_prefix = template.format(channel=config.system.channel,
                                 device=config.system.device)
    url_base = urljoin(config.service.https_base, url_prefix)
    tarxz_src = url_base + '.tar.xz'
    ascxz_src = tarxz_src + '.asc'
    # Calculate the local paths to the temporary download files.
    tarxz_dst = os.path.join(
        config.system.tempdir, os.path.basename(tarxz_src))
    ascxz_dst = tarxz_dst + '.asc'
    with ExitStack() as stack:
        # Let FileNotFoundError percolate up.
        get_files([(tarxz_src, tarxz_dst),
                   (ascxz_src, ascxz_dst)])
        stack.callback(os.remove, tarxz_dst)
        stack.callback(os.remove, ascxz_dst)
        # See if there's an existing blacklist keyring.  Any keys in this
        # blacklist are ignored for signing purposes.
        blacklist = (config.gpg.blacklist
                     if os.path.exists(config.gpg.blacklist)
                     else None)
        signing_keyring = getattr(config.gpg, config_signing)
        with Context(signing_keyring, blacklist=blacklist) as ctx:
            if not ctx.verify(ascxz_dst, tarxz_dst):
                raise KeyringError('bad signature')
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
        json_type = data['type']
        if keyring_type != json_type:
            raise KeyringError(
                'keyring type mismatch; wanted: {}, got: {}'.format(
                    keyring_type, json_type))
        # Check the optional keys next.
        json_model = data.get('model')
        if json_model not in (config.system.device, None):
            raise KeyringError(
                'keyring model mismatch; wanted: {}, got: {}'.format(
                    config.system.device, json_model))
        expiry = data.get('expiry')
        if expiry is not None:
            # Get our current timestamp in UTC.
            timestamp = datetime.now(tz=timezone.utc).timestamp()
            if expiry < timestamp:
                # We've passed the expiration date for this keyring.
                raise KeyringError('expired keyring timestamp')
        # Everything is good, so copy the keyring.gpg file to its final
        # destination.  The original keyring.gpg file will be deleted when the
        # context manager exits.
        shutil.copy(keyring_gpg, getattr(config.gpg, config_keyring))
