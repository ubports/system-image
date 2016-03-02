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
from systemimage.config import config
from systemimage.download import get_download_manager
from systemimage.gpg import Context
from systemimage.helpers import makedirs, safe_remove
from urllib.parse import urljoin


class KeyringError(Exception):
    """An error occurred getting the keyring."""

    def __init__(self, message):
        self.message = message


def get_keyring(keyring_type, urls, sigkr, blacklist=None):
    """Download, verify, and unpack a keyring.

    The keyring .tar.xz file and its signature file are downloaded.  The
    signature is verified against the keys in the signature keyring gpg
    file.  If this fails, a SignatureError is raised and the files are
    deleted.

    If this succeeds, the tar.xz is unpacked, which should produce a
    keyring.gpg file containing the keyring, and a keyring.json file
    describing the keyring.  We load up the json file and verify that
    the keyring 'type' matches the type parameter and that the 'expiry'
    key, which names a UTC UNIX epoch timestamp, has not yet expired.
    Also, the 'model' key is checked - it is optional in the json file,
    and when it's missing, it means it applies to any model.

    If any of these condition occurred, a KeyringError is raised and the
    files are deleted.

    Assuming everything checks out, the .gpg file is copied to the cache
    location for the unpacked keyring, and the downloaded .tar.xz and
    .tar.xz.asc files are moved into place.  All the other ancillary
    files are deleted.

    :param keyring_type: The type of keyring file to download.  This can be
        one of 'archive-master', 'image-master', 'image-signing',
        'device-signing', or 'blacklist'.
    :param url: Either a string naming the url to the source of the keyring
        .tar.xz file (in which case the url to the associated .asc file will
        be calculated), or a 2-tuple naming the .tar.xz and .tar.xz.asc files.
    :param sigkr: The local keyring file that should be used to verify the
        downloaded signature.
    :param blacklist: When given, this is the signature blacklist file.
    :raises SignatureError: when the keyring signature does not match.
    :raises KeyringError: when any of the other verifying attributes of the
        downloaded keyring fails.
    """
    # Calculate the urls to the .tar.xz and .asc files.
    if isinstance(urls, tuple):
        srcurl, ascurl = urls
    else:
        srcurl = urls
        ascurl = urls + '.asc'
    tarxz_src = urljoin(config.https_base, srcurl)
    ascxz_src = urljoin(config.https_base, ascurl)
    # Calculate the local paths to the temporary download files.  The
    # blacklist goes to the data partition and all the other files go to the
    # cache partition.
    dstdir = (config.updater.data_partition
              if keyring_type == 'blacklist'
              else config.updater.cache_partition)
    tarxz_dst = os.path.join(dstdir, 'keyring.tar.xz')
    ascxz_dst = tarxz_dst + '.asc'
    # Delete any files that were previously present.  The download manager
    # will raise an exception if it finds a file already there.
    safe_remove(tarxz_dst)
    safe_remove(ascxz_dst)
    with ExitStack() as stack:
        # Let FileNotFoundError percolate up.
        get_download_manager().get_files([
            (tarxz_src, tarxz_dst),
            (ascxz_src, ascxz_dst),
            ])
        stack.callback(os.remove, tarxz_dst)
        stack.callback(os.remove, ascxz_dst)
        signing_keyring = getattr(config.gpg, sigkr.replace('-', '_'))
        with Context(signing_keyring, blacklist=blacklist) as ctx:
            ctx.validate(ascxz_dst, tarxz_dst)
        # The signature is good, so now unpack the tarball, load the json file
        # and verify its contents.
        keyring_gpg = os.path.join(config.tempdir, 'keyring.gpg')
        keyring_json = os.path.join(config.tempdir, 'keyring.json')
        with tarfile.open(tarxz_dst, 'r:xz') as tf:
            tf.extractall(config.tempdir)
        stack.callback(os.remove, keyring_gpg)
        stack.callback(os.remove, keyring_json)
        with open(keyring_json, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        # Check the mandatory keys first.
        json_type = data['type']
        if keyring_type != json_type:
            raise KeyringError(
                'keyring type mismatch; wanted: {}, got: {}'.format(
                    keyring_type, json_type))
        # Check the optional keys next.
        json_model = data.get('model')
        if json_model not in (config.device, None):
            raise KeyringError(
                'keyring model mismatch; wanted: {}, got: {}'.format(
                    config.device, json_model))
        expiry = data.get('expiry')
        if expiry is not None:
            # Get our current timestamp in UTC.
            timestamp = datetime.now(tz=timezone.utc).timestamp()
            if expiry < timestamp:
                # We've passed the expiration date for this keyring.
                raise KeyringError('expired keyring timestamp')
        # Everything checks out.  We now have the generic keyring.tar.xz and
        # keyring.tar.xz.asc files inside the cache (or data, in the case of
        # the blacklist) partition, which is where they need to be for
        # recovery.
        #
        # These files need to be renamed to their actual <keyring-type>.tar.xz
        # and .asc file names.
        #
        # We also want copies of these latter files to live in /var/lib so
        # that we don't have to download them again if we don't need to.
        if keyring_type == 'blacklist':
            tarxz_path = os.path.join(
                config.updater.data_partition, 'blacklist.tar.xz')
        else:
            tarxz_path = getattr(config.gpg, keyring_type.replace('-', '_'))
        ascxz_path = tarxz_path + '.asc'
        makedirs(os.path.dirname(tarxz_path))
        safe_remove(tarxz_path)
        safe_remove(ascxz_path)
        shutil.copy(tarxz_dst, tarxz_path)
        shutil.copy(ascxz_dst, ascxz_path)
        # For all keyrings, copy the extracted .gpg file to the tempdir.  We
        # will always fallback to this path to avoid unpacking the .tar.xz
        # file every single time.
        gpg_path = os.path.join(config.tempdir, keyring_type + '.gpg')
        shutil.copy(keyring_gpg, gpg_path)
