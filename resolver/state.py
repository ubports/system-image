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
import logging

from collections import deque
from contextlib import ExitStack
from functools import partial
from resolver.candidates import get_candidates, get_downloads
from resolver.channel import Channels
from resolver.config import config
from resolver.download import get_files
from resolver.gpg import Context, SignatureError
from resolver.index import Index
from resolver.keyring import KeyringError, get_keyring
from urllib.parse import urljoin


log = logging.getLogger('resolver')
COMMASPACE = ', '


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
        self.candidates = None
        self.winner = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            self._next.popleft()()
        except IndexError:
            # Do not chain the exception.
            raise StopIteration from None
        except:
            log.exception('uncaught exception in state machine')
            raise

    def _get_blacklist(self):
        """Get the blacklist keyring if there is one."""
        # The only way to know whether there is a blacklist or not is to try
        # to download it.  If it fails, there isn't one.
        url = 'gpg/blacklist.tar.xz'
        try:
            # I think it makes no sense to check the blacklist when we're
            # downloading a blacklist file.
            log.info('Looking for blacklist: %s',
                     urljoin(config.service.https_base, url))
            dst = get_keyring('blacklist', url, url + '.asc', 'image_master')
        except SignatureError:
            log.info('No signed blacklist found')
            # The blacklist wasn't signed by the system image master.  Maybe
            # there's a new system image master key?  Let's find out.
            self._next.appendleft(
                partial(self._get_master_key, self._get_blacklist))
            return
        except FileNotFoundError:
            # There is no blacklist.
            log.info('No blacklist found')
        else:
            # Move the keyring.gpg file to a safe place inside our temporary
            # directory.  It is the responsibility of the code running the
            # state machine to clear out the temporary directory.
            self.blacklist = os.path.join(
                config.system.tempdir, 'blacklist.gpg')
            os.rename(dst, self.blacklist)
            log.info('Local blacklist file: %s', self.blacklist)
        self._next.append(self._get_channel)

    def _get_channel(self):
        """Get and verify the channels.json file."""
        channels_url = urljoin(config.service.https_base, 'channels.json')
        channels_path = os.path.join(config.system.tempdir, 'channels.json')
        asc_url = urljoin(config.service.https_base, 'channels.json.asc')
        asc_path = os.path.join(config.system.tempdir, 'channels.json.asc')
        log.info('Looking for: %s', channels_url)
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
                # The signature on the channels.json file did not match.
                # Maybe there's a new image signing key on the server.  If a
                # new key *is* found, retry the current step.
                self._next.appendleft(
                    partial(self._get_signing_key, self._get_channel))
                log.info('channels.json not properly signed')
                return
            # The signature was good.
            log.info('Local channels file: %s', channels_path)
            with open(channels_path, encoding='utf-8') as fp:
                self.channels = Channels.from_json(fp.read())
        # The next step will depend on whether there is a device keyring
        # available or not.  If there is, download and verify it now.
        try:
            device = getattr(
                # This device's channel.
                getattr(self.channels, config.system.channel),
                config.system.device)
        except AttributeError:
            log.info('no matching channel/device: %s/%s',
                     config.system.channel, config.system.device)
            # Either our channel or device isn't described in the
            # channels.json file, so there's nothing more to do.
            return
        log.info('found channel/device entry: %s/%s',
                 config.system.channel, config.system.device)
        keyring = getattr(device, 'keyring', None)
        if keyring:
            self._next.append(partial(self._get_device_keyring, keyring))
        self._next.append(partial(self._get_index, device.index))

    def _get_device_keyring(self, keyring):
        keyring_url = urljoin(config.service.https_base, keyring.path)
        asc_url = urljoin(config.service.https_base, keyring.signature)
        log.info('getting device keyring: %s', keyring_url)
        self.device_keyring = get_keyring(
            'device', keyring_url, asc_url, 'image_signing',
            self.blacklist)
        # We don't need to set the next action because it's already been done.

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
            # Check the signature of the index.json file.  It may be signed by
            # either the device keyring (if one exists) or the image signing
            # key.
            keyrings = [config.gpg.image_signing]
            if self.device_keyring is not None:
                keyrings.append(self.device_keyring)
            ctx = stack.enter_context(
                Context(*keyrings, blacklist=self.blacklist))
            if not ctx.verify(asc_path, index_path):
                raise SignatureError
            # The signature was good.
            with open(index_path, encoding='utf-8') as fp:
                self.index = Index.from_json(fp.read())
        self._next.append(self._calculate_winner)

    def _calculate_winner(self):
        """Given an index, calculate the paths and score a winner."""
        # Store these as attributes for debugging and testing.
        self.candidates = get_candidates(self.index, config.build_number)
        self.winner = config.score.scorer().choose(self.candidates)
        self._next.append(self._download_files)

    def _download_files(self):
        """Download and verify all the winning upgrade path's files."""
        downloads = get_downloads(self.winner)
        local_files = set(dst for url, dst in downloads
                          if os.path.splitext(dst)[1] != '.asc')
        log.info('Files to download: %s', COMMASPACE.join(sorted(local_files)))
        # Now, verify the signatures of all the downloaded files.  If there is
        # a device key, the files can be signed by that or the imaging signing
        # key.
        keyrings = [config.gpg.image_signing]
        if self.device_keyring is not None:
            keyrings.append(self.device_keyring)
        get_files(downloads)
        with ExitStack() as stack:
            # Set things up to remove the files if a SignatureError gets
            # raised.  If the exception doesn't get raised, then everything's
            # okay and we'll clear the stack before the context manager exits
            # so none of the files will get removed.
            for path in local_files:
                stack.callback(os.remove, path)
                stack.callback(os.remove, path + '.asc')
            with Context(*keyrings, blacklist=self.blacklist) as ctx:
                for path in local_files:
                    if not ctx.verify(path + '.asc', path):
                        raise SignatureError
            # Everything is fine so nothing needs to be cleared.
            stack.pop_all()
        # There's nothing left to do, so don't push anything onto the deque.
        log.info('all files available in %s', config.system.tempdir)

    def _get_master_key(self, next_step):
        """Try to get and validate a new image master key.

        If there isn't one, throw a SignatureError.
        """
        url = urljoin(config.service.https_base, 'gpg/system-image.tar.xz')
        try:
            # The image signing key must be signed by the archive master.
            path = get_keyring(
                'system-image', url, url + '.asc',
                'archive_master', self.blacklist)
        except (FileNotFoundError, SignatureError, KeyringError):
            # No valid image master key could be found.  Don't chain this
            # exception.
            raise SignatureError from None
        # Copy the new key into place, then retry the previous step.
        os.rename(path, config.gpg.image_master)
        self._next.append(next_step)

    def _get_signing_key(self, next_step):
        """Try to get and validate a new image signing key.

        If there isn't one, throw a SignatureError.
        """
        url = urljoin(config.service.https_base, 'gpg/signing.tar.xz')
        try:
            # The image signing key must be signed by the image master.
            path = get_keyring(
                'signing', url, url + '.asc', 'image_master', self.blacklist)
        except (FileNotFoundError, SignatureError, KeyringError):
            # No valid image signing key could be found.  Don't chain this
            # exception.
            raise SignatureError from None
        # Copy the new key into place, then retry the previous step.
        os.rename(path, config.gpg.image_signing)
        self._next.append(next_step)
