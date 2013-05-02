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

"""Update channels."""

__all__ = [
    'Channels',
    ]


import os
import json

from resolver.cache import Cache
from resolver.download import get_files
from resolver.gpg import Context, get_pubkey
from resolver.helpers import Bag, atomic
from urllib.parse import urljoin


class Channels(Bag):
    @classmethod
    def from_json(cls, data):
        mapping = json.loads(data)
        channels = {}
        for channel_name, index_data in mapping.items():
            channels[channel_name] = Bag(**index_data)
        return cls(**channels)


def load_channel(cache=None):
    """Load the channel data from the cache, or the web service if necessary.

    The channels.json.asc signature file is verified, and if it doesn't match,
    the cache remains empty and a FileNotFoundError is raised.
    """
    if cache is None:
        from resolver.config import config
        cache = Cache(config)
    channels_path = cache.get_path('channels.json')
    # If the file is already in the cache, there's no need to verify its
    # signature since anyone who can subvert the .json file can also subvert
    # the .json.asc signature file too.  Short-circuit for readability.
    if channels_path is not None:
        with open(channels_path, encoding='utf-8') as fp:
            return Channels.from_json(fp.read())
    # BAW 2013-04-26: This always downloads the phablet pubkey from the web
    # site too, but really, this should either be in the cache already,
    # retrieved from the cache, or in a hardcoded place on the file system.
    pubkey_path = get_pubkey(cache)
    # Download both the channels.json and signature file.  Store both data
    # files as temporary files in the cache directory.  Then verify the
    # signature.  If it matches, return a new Channels instance, otherwise
    # raise a FileNotFound exception and remove all the temporary files.
    config = cache.config
    channels_path = os.path.join(config.cache.directory, 'channels.json')
    asc_path = os.path.join(config.cache.directory, 'channels.json.asc')
    with atomic(channels_path) as cfp, atomic(asc_path) as afp:
        cfp.close()
        afp.close()
        get_files([
            (urljoin(config.service.base, 'channels.json'), cfp.name),
            (urljoin(config.service.base, 'channels.json.asc'), afp.name),
            ])
        with Context(pubkey_path) as ctx:
            # Check the signatures on the temporary files.
            if not ctx.verify(afp.name, cfp.name):
                # Raising this exception will unwind all the context managers,
                # deleting the temporary files and not writing the
                # channels.json{,.asc} files.
                raise FileNotFoundError
        # All is good.  We have now have channels.json{,.asc} verified and
        # available in the cache.  Create the return value.
        with open(cfp.name, encoding='utf-8') as fp:
            channels = Channels.from_json(fp.read())
        # BAW 2013-04-26: One potential problem: if we have an error updating
        # the cache, we probably now have two bogus keys in the timeout data.
        cache.update('channels.json')
        cache.update('channels.json.asc')
        return channels
