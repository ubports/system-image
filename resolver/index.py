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
    'load_current_index',
    ]


import os
import json

from datetime import datetime, timezone
from resolver.bag import Bag
from resolver.cache import Cache
from resolver.channel import load_channel
from resolver.download import get_files
from resolver.helpers import ExtendedEncoder
from resolver.image import Image
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


def load_current_index(cache=None, *, force=False):
    """Load the current index file.

    Download the current index file by first reading the channels file and
    chasing the index file link.   The channels file may be cached; use that
    unless forced to download a new one.  The index.json file is always
    downloaded.

    The new `Index` object is returned.
    """
    if cache is None:
        from resolver.config import config
        cache = Cache(config)
    config = cache.config
    channel = load_channel(cache, force=force)
    device = getattr(getattr(channel, config.system.channel),
                     config.system.device)
    remote_index_path = urljoin(config.service.base, device.index)
    local_index_path = os.path.join(config.cache.directory,
                                    os.path.basename(device.index))
    downloads = [(remote_index_path, local_index_path)]
    keyring_path = getattr(device, 'keyring', None)
    if keyring_path is not None:
        remote_keyring_path = urljoin(config.service.base, keyring_path)
        local_keyring_path = os.path.join(config.cache.directory,
                                          os.path.basename(keyring_path))
        downloads.append((remote_keyring_path, local_keyring_path))
    get_files(downloads)
    # BAW 2013-05-03: validate the index using the keyring!
    with open(local_index_path, encoding='utf-8') as fp:
        return Index.from_json(fp.read())
