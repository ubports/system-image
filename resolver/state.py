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

"""Manage state transitions for updates."""

__all__ = [
    'State',
    ]


import os

from collections import deque
from contextlib import ExitStack
from functools import partial
from resolver.channel import Channels
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import Context, SignatureError
from resolver.index import Index
from resolver.keyring import get_keyring
from urllib.parse import urljoin


class State:
    def __init__(self):
        # Variables which manage state transitions.
        self._next = deque()
        self._next.append(self._get_blacklist)
        # Variables which represent things we've learned.
        self.blacklist = None
        self.channels = None
        self.index = None
        self.device_keyring = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            self._next.popleft()()
        except IndexError:
            raise StopIteration

    def _get_blacklist(self):
        """Get the blacklist keyring if there is one."""
        # The only way to know whether there is a blacklist or not is to try
        # to download it.  If it fails, there isn't one.
        url = 'gpg/blacklist.tar.xz'
        try:
            # I think it makes no sense to check the blacklist when we're
            # downloading a blacklist file.
            dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        except FileNotFoundError:
            # There is no blacklist.
            pass
        else:
            self.blacklist = dst
        self._next.append(self._get_channel)

    def _get_channel(self):
        """Get and verify the channels.json file."""
        channels_url = urljoin(config.service.https_base, 'channels.json')
        channels_path = os.path.join(config.system.tempdir, 'channels.json')
        asc_url = urljoin(config.service.https_base, 'channels.json.asc')
        asc_path = os.path.join(config.system.tempdir, 'channels.json.asc')
        with ExitStack() as stack:
            get_files([
                (channels_url, channels_path),
                (asc_url, asc_path),
                ])
            # Once we're done with them, we can remove these files.
            stack.callback(os.remove, channels_path)
            stack.callback(os.remove, asc_path)
            # The channels.json file must be signed with the SYSTEM IMAGE
            # SIGNING key.  There may or may not be a blacklist.
            ctx = stack.enter_context(
                Context(config.gpg.image_signing, blacklist=self.blacklist))
            if not ctx.verify(asc_path, channels_path):
                raise SignatureError
            # The signature was good.
            with open(channels_path, encoding='utf-8') as fp:
                self.channels = Channels.from_json(fp.read())
        # The next step will depend on whether there is a device keyring
        # available or not.  If there is, download and verify it now.
        device = getattr(
            # This device's channel.
            getattr(self.channels, config.system.channel),
            config.system.device)
        keyring = getattr(device, 'keyring', None)
        if keyring:
            self._next.append(partial(self._get_device_keyring, keyring))
        self._next.append(partial(self._get_index, device.index))

    def _get_device_keyring(self, keyring):
        keyring_url = urljoin(config.service.https_base, keyring.path)
        asc_url = urljoin(config.service.https_base, keyring.signature)
        self.device_keyring = get_keyring(
            'device', keyring_url, asc_url, 'image_signing', self.blacklist)

    def _get_index(self, index):
        """Get and verify the index.json file."""
        index_url = urljoin(config.service.https_base, index)
        asc_url = index_url + '.asc'
        index_path = os.path.join(config.system.tempdir, 'index.json')
        asc_path = index_path + '.asc'
        with ExitStack() as stack:
            get_files([
                (index_url, index_path),
                (asc_url, asc_path),
                ])
            stack.callback(os.remove, index_path)
            stack.callback(os.remove, asc_path)
            # Check the signature of the index.json file.  It will have been
            # signed by the device keyring if given, otherwise it will have
            # been signed by the image signing key.
            ctx = stack.enter_context(
                Context(config.gpg.image_signing
                        if self.device_keyring is None
                        else self.device_keyring, blacklist=self.blacklist))
            if not ctx.verify(asc_path, index_path):
                raise SignatureError
            # The signature was good.
            with open(index_path, encoding='utf-8') as fp:
                self.index = Index.from_json(fp.read())
