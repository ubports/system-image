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

from contextlib import ExitStack
from resolver.channel import Channels
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import Context, SignatureError
from resolver.keyring import get_keyring
from urllib.parse import urljoin


class State:
    def __init__(self):
        # Variables which manage state transitions.
        self._next = self._get_blacklist
        # Variables which represent things we've learned.
        self.blacklist = None
        self.channels = None

    def __iter__(self):
        return self

    def __next__(self):
        if self._next is None:
            raise StopIteration
        self._next()

    def _get_blacklist(self):
        """Get the blacklist keyring if there is one."""
        # The only way to know whether there is a blacklist or not is to try
        # to download it.  If it fails, there isn't one.
        try:
            get_keyring('blacklist')
        except FileNotFoundError:
            # There is no blacklist.
            pass
        else:
            self.blacklist = config.gpg.blacklist
        self._next = self._get_channel

    def _get_channel(self):
        """Get and verify the channels.json file."""
        channels_url = urljoin(config.service.https_base, 'channels.json')
        asc_url = urljoin(config.service.https_base, 'channels.json.asc')
        channels_path = os.path.join(config.system.tempdir, 'channels.json')
        asc_path = os.path.join(config.system.tempdir, 'channels.json.asc')
        get_files([
            (channels_url, channels_path),
            (asc_url, asc_path),
            ])
        with ExitStack() as stack:
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
        self._next = None
