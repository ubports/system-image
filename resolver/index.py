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

"""Device/channel indexes."""

__all__ = [
    'Index',
    'load_index',
    ]


import os
import json

from contextlib import ExitStack
from datetime import datetime, timezone
from resolver.bag import Bag
from resolver.channel import load_channel
from resolver.config import config
from resolver.download import get_files
from resolver.helpers import ExtendedEncoder
from resolver.image import Image
from resolver.keyring import get_keyring
from urllib.parse import urljoin


IN_FMT = '%a %b %d %H:%M:%S %Z %Y'
OUT_FMT = '%a %b %d %H:%M:%S UTC %Y'


class Index(Bag):
    @classmethod
    def from_json(cls, data):
        """Parse the JSON data and produce an index."""
        mapping = json.loads(data)
        # Parse the global data, of which there is only the timestamp.  Even
        # though the string will contain 'UTC' (which we assert is so since we
        # can only handle UTC timestamps), strptime() will return a naive
        # datetime.  We'll turn it into an aware datetime in UTC, which is the
        # only thing that can possibly make sense.
        timestamp_str = mapping['global']['generated_at']
        assert 'UTC' in timestamp_str.split(), 'timestamps must be UTC'
        naive_generated_at = datetime.strptime(timestamp_str, IN_FMT)
        generated_at=naive_generated_at.replace(tzinfo=timezone.utc)
        global_ = Bag(generated_at=generated_at)
        # Parse the images.
        images = []
        for image_data in mapping['images']:
            files = image_data.pop('files', [])
            bundles = [Bag(**bundle_data) for bundle_data in files]
            images.append(Image(files=bundles, **image_data))
        return cls(global_=global_, images=images)

    def to_json(self):
        index = {
            'global': {
                'generated_at': self.global_.generated_at.strftime(OUT_FMT),
                },
            'images': [image.__original__ for image in self.images],
            }
        return json.dumps(index,
                          sort_keys=True, indent=4, separators=(',', ': '),
                          cls=ExtendedEncoder)


def load_index():
    """Load the index file.

    Download the current index file by first reading the channels file and
    chasing the index file link.

    :return: The new `Index` object.
    :rtype: Index
    :raises SignatureError: if the index.json file is not properly signed by
        the device signing (i.e. vendor) key if there is one, or the image
        signing key.
    """
    # Loading the channel will also load the blacklist, which will be
    # available on the path named by config.gpg.blacklist if there is one.
    channel = load_channel()
    # Calculate the url to the index.json and index.json.asc files, and
    # download them.
    device = getattr(getattr(channel, config.system.channel),
                     config.system.device)
    with ExitStack() as stack:
        index_url = urljoin(config.service.https_base, device.index)
        index_path = os.path.join(config.system.tempdir, 'index.json')
        downloads = [
            (index_url, index_path),
            (index_url + '.asc', index_path + '.asc'),
            ]
        # The temporary files can be removed when we're done with them.
        stack.callback(os.remove, index_path)
        stack.callback(os.remove, index_path + '.asc')
        # The index file might specify a device keyring.
        keyring = getattr(device, 'keyring', None)
        if keyring is not None:
            keyring_url = urljoin(config.service.https_base, keyring.path)
            keyring_path = os.path.join(
                config.system.tempdir, 'device-keyring.tar.xz')
            signature_url = urljoin(
                config.service.https_base, keyring.signature)
            signature_path = os.path.join(
                config.system.tempdir, 'device-keyring.tar.xz.asc')
            downloads.extend([
                (keyring_url, keyring_path),
                (signature_url, signature_path),
                ])
            stack.callback(os.remove, keyring_path)
            stack.callback(os.remove, signature_path)
    # If there is a device signing key, get that now.
    try:
        get_keyring('device')
        device_keyring = config.gpg.vendor_signing
    except FileNotFoundError:
        device_keyring = None
    # If there's already a blacklist key, use it.
    blacklist = (config.gpg.blacklist
                 if os.path.exists(config.gpg.blacklist)
                 else None)


    downloads = [(index_url, index_path),
                 (index_url + '.asc', index_path + '.asc')]
    

    get_files(downloads)
    # BAW 2013-05-03: validate the index using the keyring!
    with open(index_path, encoding='utf-8') as fp:
        return Index.from_json(fp.read())
