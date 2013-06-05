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

from contextlib import ExitStack
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import Context, SignatureError
from resolver.helpers import Bag
from resolver.keyring import get_keyring
from urllib.parse import urljoin


class Channels(Bag):
    @classmethod
    def from_json(cls, data):
        mapping = json.loads(data)
        channels = {}
        for channel_name, device in mapping.items():
            devices = {}
            for name, data in device.items():
                devices[name] = Bag(**data)
            channels[channel_name] = Bag(**devices)
        return cls(**channels)


def load_channel():
    """Load the channel data from the web service.

    The channels.json.asc signature file is verified, and if it doesn't match,
    a SignatureError is raised.

    :return: The current channel object.
    :rtype: Channels
    :raises SignatureError: if the channels.json file is not properly
        signed by the image signing key.
    """
    # Download the blacklist file, if there is one.
    get_keyring('blacklist')
    

    channels_url = urljoin(config.service.https_base, 'channels.json')
    asc_url = urljoin(config.service.https_base, 'channels.json.asc')
    channels_path = os.path.join(config.system.tempdir, 'channels.json')
    asc_path = os.path.join(config.system.tempdir, 'channels.json.asc')
    get_files([
        (channels_url, channels_path),
        (asc_url, asc_path),
        ])
    with ExitStack() as stack:
        ctx = stack.enter_context(Context(pubkey_path))
        if not ctx.verify(asc_path, channels_path):
            # The signature did not verify, so arrange for the .json and .asc
            # files to be removed before we raise the exception.
            stack.callback(os.remove, channels_path)
            stack.callback(os.remove, asc_path)
            raise FileNotFoundError
    # The signature was good.
    with open(channels_path, encoding='utf-8') as fp:
        return Channels.from_json(fp.read())
